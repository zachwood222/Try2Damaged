import os
import os, secrets, urllib.parse, requests
from flask import Flask, redirect, request, session, url_for, abort
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from models import Base, EmailItem, Photo, Status
from config import load_config
from gmail_client import GmailManager
from drive_client import DriveManager
from token_store import DBTokenStore
from tasks import scan_gmail_accounts, send_daily_summary

# --- Load config FIRST ---
CFG = load_config()

# --- Now we can safely use CFG ---
DRIVE_REDIRECT_URI = CFG.get('GOOGLE_DRIVE_REDIRECT_URI')

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
app.secret_key = CFG['FLASK_SECRET_KEY']

# --- Database ---
engine = create_engine(CFG['DATABASE_URL'], future=True)
Base.metadata.create_all(engine)
Session = scoped_session(sessionmaker(bind=engine, autoflush=False))

# --- Token store ---
token_store = DBTokenStore(Session)

# --- Google managers ---
gmail_mgr = GmailManager(
    client_secrets_file=CFG['GOOGLE_CLIENT_SECRETS'],
    token_store=token_store,
    scopes=CFG['OAUTH_SCOPES'].split()
)

drive_mgr = DriveManager(
    client_secrets_file=CFG['GOOGLE_CLIENT_SECRETS'],
    token_dir=CFG.get('GOOGLE_TOKEN_DIR', 'tokens'),
    scopes=CFG['OAUTH_SCOPES'].split()
)

@app.teardown_appcontext
def shutdown_session(exception=None):
    Session.remove()

@app.route('/')
def index():
    session_db = Session()
    q = session_db.query(EmailItem).order_by(EmailItem.created_at.desc())

    status = request.args.get('status')
    kw = request.args.get('q', '').strip()

    if status in {'NEW', 'RESOLVED', 'CREDIT_RECEIVED'}:
        q = q.filter(EmailItem.status == Status[status])

    if kw:
        like = f"%{kw}%"
        q = q.filter(
            (EmailItem.subject.ilike(like)) |
            (EmailItem.snippet.ilike(like)) |
            (EmailItem.sender.ilike(like))
        )

    items = q.limit(300).all()

    connected_gmails = gmail_mgr.list_connected_accounts()

    service_account = CFG.get('SERVICE_GOOGLE_ACCOUNT') or ''
    # Drive connection = token exists/loads
    try:
        has_drive = bool(service_account and drive_mgr.load_credentials(service_account))
    except Exception:
        has_drive = False

    return render_template(
        'index.html',
        items=items,
        kw=kw,
        status=status,
        monitored=[a.strip() for a in CFG['MONITORED_GMAIL_ACCOUNTS'].split(',') if a.strip()],
        connected_gmails=connected_gmails,
        drive_connected=has_drive,
        service_account=service_account,
        config=CFG
    )

@app.route('/detail/<int:item_id>')
def detail(item_id):
    session_db = Session()
    item = session_db.get(EmailItem, item_id)
    if not item:
        flash('Item not found', 'warning')
        return redirect(url_for('index'))
    return render_template('detail.html', item=item)

@app.route('/status/<int:item_id>/<new_status>', methods=['POST'])
def update_status(item_id, new_status):
    session_db = Session()
    item = session_db.get(EmailItem, item_id)
    if not item:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    if new_status not in {'NEW', 'RESOLVED', 'CREDIT_RECEIVED'}:
        return jsonify({'ok': False, 'error': 'Bad status'}), 400
    item.status = Status[new_status]
    session_db.commit()
    return jsonify({'ok': True, 'status': new_status})

# ---- Gmail OAuth ----
@app.route('/connect/gmail')
def connect_gmail():
    account = request.args.get('account')
    if not account:
        flash('Missing ?account=email', 'warning')
        return redirect(url_for('index'))

    # If your Gmail callback endpoint is named differently, update 'oauth2callback'
    redirect_uri = url_for('oauth2callback', _external=True, _scheme='https')
    authorization_url, state = gmail_mgr.build_authorize_url(account, redirect_uri=redirect_uri)
    session['gmail_state'] = state
    session['gmail_account'] = account
    return redirect(authorization_url)

# ---- Drive OAuth ----
@app.route("/connect/drive")
def connect_drive():
    email = request.args.get("email") or CFG.get('SERVICE_GOOGLE_ACCOUNT') or "default@example.com"
    try:
        # MUST match an Authorized redirect URI in Google Cloud Console
        redirect_uri = url_for("oauth2callback_drive", _external=True, _scheme="https")
        auth_url, flow_state = drive_mgr.build_authorize_url(email, redirect_uri)
        session["oauth_email"] = email
        session["oauth_state"] = flow_state
        return redirect(auth_url)
    except Exception as e:
        app.logger.exception("Connect /drive failed")
        return f"Connect failed: {e}", 500

@app.route("/oauth2callback/drive")
def oauth2callback_drive():
    if "error" in request.args:
        return f"Google error: {request.args['error']}", 400

    email = session.get("oauth_email") or CFG.get('SERVICE_GOOGLE_ACCOUNT') or "default@example.com"
    redirect_uri = url_for("oauth2callback_drive", _external=True, _scheme="https")
    authorization_response_url = request.url
    state = session.get("oauth_state")

    try:
        drive_mgr.finish_authorize(email, authorization_response_url, redirect_uri, state=state)
        flash("Google Drive connected.", "success")
        return redirect(url_for("index"))
    except Exception as e:
        app.logger.exception("OAuth callback (Drive) failed")
        return f"Callback failed: {e}", 500

# ---- Tasks (cron/webhook endpoints) ----
@app.route('/tasks/scan')
def task_scan():
    secret = request.args.get('secret')
    if secret != CFG['TASKS_SECRET']:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401

    session_db = Session()
    try:
        count = scan_gmail_accounts(session_db, gmail_mgr, drive_mgr, CFG)
        session_db.commit()
        return jsonify({'ok': True, 'updated': count})
    except Exception as e:
        session_db.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        session_db.close()

@app.route('/tasks/daily-summary')
def task_daily_summary():
    secret = request.args.get('secret')
    if secret != CFG['TASKS_SECRET']:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401

    session_db = Session()
    try:
        sent = send_daily_summary(session_db, gmail_mgr, CFG)
        return jsonify({'ok': True, 'sent': sent})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        session_db.close()

# Simple health check for Render
@app.route('/healthz')
def healthz():
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(debug=False)
