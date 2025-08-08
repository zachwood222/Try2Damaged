import os
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import url_for
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from models import Base, EmailItem, Photo, Status
from config import load_config
from gmail_client import GmailManager
from drive_client import DriveManager
from token_store import DBTokenStore
from tasks import scan_gmail_accounts, send_daily_summary

CFG = load_config()



app = Flask(__name__)

app.secret_key = CFG['FLASK_SECRET_KEY']

# Database
engine = create_engine(CFG['DATABASE_URL'], future=True)
Base.metadata.create_all(engine)
Session = scoped_session(sessionmaker(bind=engine, autoflush=False))

# Token store backed by DB (no disk required on Render free tier)
token_store = DBTokenStore(Session)

# Google managers
gmail_mgr = GmailManager(
    client_secrets_file=CFG['GOOGLE_CLIENT_SECRETS'],
    token_store=token_store,
    scopes=CFG['OAUTH_SCOPES'].split()
)
drive_mgr = DriveManager(
    client_secrets_file=CFG['GOOGLE_CLIENT_SECRETS'],
    token_store=token_store,
    scopes=CFG['OAUTH_SCOPES'].split(),
    upload_folder_id=CFG['DRIVE_UPLOAD_FOLDER_ID']
)

@app.teardown_appcontext
def shutdown_session(exception=None):
    Session.remove()

@app.route('/')
def index():
    session = Session()
    q = session.query(EmailItem).order_by(EmailItem.created_at.desc())
    status = request.args.get('status')
    kw = request.args.get('q', '').strip()
    if status in {'NEW','RESOLVED','CREDIT_RECEIVED'}:
        q = q.filter(EmailItem.status == Status[status])
    if kw:
        like = f"%{kw}%"
        q = q.filter((EmailItem.subject.ilike(like)) | (EmailItem.snippet.ilike(like)) | (EmailItem.sender.ilike(like)))
    items = q.limit(300).all()

    connected_gmails = gmail_mgr.list_connected_accounts()
    has_drive = drive_mgr.is_connected(CFG['SERVICE_GOOGLE_ACCOUNT'])

    return render_template('index.html', items=items, kw=kw, status=status,
                           monitored=[a for a in CFG['MONITORED_GMAIL_ACCOUNTS'].split(',') if a],
                           connected_gmails=connected_gmails,
                           drive_connected=has_drive,
                           service_account=CFG['SERVICE_GOOGLE_ACCOUNT'],
                           config=CFG)

@app.route('/detail/<int:item_id>')
def detail(item_id):
    session = Session()
    item = session.get(EmailItem, item_id)
    if not item:
        flash('Item not found', 'warning')
        return redirect(url_for('index'))
    return render_template('detail.html', item=item)

@app.route('/status/<int:item_id>/<new_status>', methods=['POST'])
def update_status(item_id, new_status):
    session = Session()
    item = session.get(EmailItem, item_id)
    if not item:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    if new_status not in {'NEW','RESOLVED','CREDIT_RECEIVED'}:
        return jsonify({'ok': False, 'error': 'Bad status'}), 400
    item.status = Status[new_status]
    session.commit()
    return jsonify({'ok': True, 'status': new_status})

@app.route('/connect/gmail')
def connect_gmail():
    account = request.args.get('account')
    if not account:
        flash('Missing ?account=email', 'warning')
        return redirect(url_for('index'))
    redirect_uri = url_for('oauth2callback', _external=True)
    authorization_url, state = gmail_mgr.build_authorize_url(account, redirect_uri=redirect_uri)
    return redirect(authorization_url)

@app.route('/connect/drive')
def connect_drive():
    account = CFG['SERVICE_GOOGLE_ACCOUNT']
    redirect_uri = url_for('oauth2callback', _external=True)
    authorization_url, state = drive_mgr.build_authorize_url(account, redirect_uri=redirect_uri)
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    code = request.args.get('code')
    state = request.args.get('state')
    returned_scope = request.args.get('scope')  # <-- capture scopes Google actually granted
    if not code or not state:
        flash('OAuth failed: missing code/state', 'danger')
        return redirect(url_for('index'))
    redirect_uri = url_for('oauth2callback', _external=True)
    try:
        if state.startswith('gmail:'):
            email = state.split(':',1)[1]
            gmail_mgr.finish_authorize(email, code, redirect_uri=redirect_uri, returned_scope=returned_scope)
            flash(f'Gmail connected for {email}', 'success')
        elif state.startswith('drive:'):
            email = state.split(':',1)[1]
            drive_mgr.finish_authorize(email, code, redirect_uri=redirect_uri, returned_scope=returned_scope)
            flash(f'Drive connected for {email}', 'success')
        else:
            flash('Unknown OAuth state', 'danger')
    except Exception as e:
        flash(f'OAuth callback error: {e}', 'danger')
    return redirect(url_for('index'))
    

    redirect_uri = url_for('oauth2callback', _external=True)

    if state.startswith('gmail:'):
        email = state.split(':',1)[1]
        gmail_mgr.finish_authorize(email, code, redirect_uri=redirect_uri)
        flash(f'Gmail connected for {email}', 'success')
    elif state.startswith('drive:'):
        email = state.split(':',1)[1]
        drive_mgr.finish_authorize(email, code, redirect_uri=redirect_uri)
        flash(f'Drive connected for {email}', 'success')
    else:
        flash('Unknown OAuth state', 'danger')
    return redirect(url_for('index'))


@app.route('/tasks/scan')
def task_scan():
    secret = request.args.get('secret')
    if secret != CFG['TASKS_SECRET']:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
    session = Session()
    try:
        count = scan_gmail_accounts(session, gmail_mgr, drive_mgr, CFG)
        session.commit()
        return jsonify({'ok': True, 'updated': count})
    except Exception as e:
        session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        session.close()

@app.route('/tasks/daily-summary')
def task_daily_summary():
    secret = request.args.get('secret')
    if secret != CFG['TASKS_SECRET']:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
    session = Session()
    try:
        sent = send_daily_summary(session, gmail_mgr, CFG)
        return jsonify({'ok': True, 'sent': sent})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        session.close()

if __name__ == '__main__':
    app.run(debug=False)
