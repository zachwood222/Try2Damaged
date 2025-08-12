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


# app.py (snippets)
import os
from flask import Flask, request, session, redirect, url_for
from drive_client import DriveManager

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")

drive_mgr = DriveManager(
    client_secrets_file=os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "client_secret.json"),
    token_dir=os.getenv("GOOGLE_TOKEN_DIR", "tokens"),
)

@app.route("/connect/drive")
def connect_drive():
    email = request.args.get("email", "default@example.com")
    # MUST exactly match one of your Google Console Authorized redirect URIs:
    redirect_uri = url_for("oauth2callback_drive", _external=True, _scheme="https")
    auth_url, flow_state = drive_mgr.build_authorize_url(email, redirect_uri)
    session["oauth_email"] = email
    session["oauth_state"] = flow_state
    return redirect(auth_url)

@app.route("/oauth2callback/drive")
def oauth2callback_drive():
    if "error" in request.args:
        return f"Google error: {request.args['error']}", 400

    email = session.get("oauth_email", "default@example.com")
    redirect_uri = url_for("oauth2callback_drive", _external=True, _scheme="https")
    # Use the full callback URL for fetch_token:
    authorization_response_url = request.url
    state = session.get("oauth_state")

    try:
        drive_mgr.finish_authorize(email, authorization_response_url, redirect_uri, state=state)
        return "Drive connected! You can close this tab."
    except Exception as e:
        app.logger.exception("OAuth callback failed")
        return f"Callback failed: {e}", 500



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
