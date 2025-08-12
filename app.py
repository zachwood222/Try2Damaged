import io, csv, os, pathlib, json, hashlib
from decimal import Decimal
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import create_engine, func
from sqlalchemy.orm import scoped_session, sessionmaker
from models import Base, EmailItem, Photo, Status, ActivityLog
from config import load_config
from gmail_client import GmailManager
from drive_client import DriveManager
from tasks import scan_gmail_accounts, send_daily_summary
from email_utils import build_notification_html, build_daily_summary_html
from utils_email import render_template as render_email_template
from utils_webhook import send_webhook

CFG = load_config()

# Optional vendor portals mapping via env JSON
VENDOR_PORTALS = {}
try:
    if os.getenv('VENDOR_PORTALS_JSON'):
        VENDOR_PORTALS = json.loads(os.getenv('VENDOR_PORTALS_JSON'))
except Exception as e:
    print('Invalid VENDOR_PORTALS_JSON:', e)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = CFG['FLASK_SECRET_KEY']
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

engine = create_engine(CFG['DATABASE_URL'], future=True)
Base.metadata.create_all(engine)
Session = scoped_session(sessionmaker(bind=engine, autoflush=False))

TOKENS_DIR = pathlib.Path(os.environ.get("TOKENS_DIR", "/tmp/tokens")); TOKENS_DIR.mkdir(parents=True, exist_ok=True)
gmail_mgr = GmailManager(CFG['GOOGLE_CLIENT_SECRETS'], TOKENS_DIR, CFG['OAUTH_SCOPES'].split())
drive_mgr = DriveManager(CFG['GOOGLE_CLIENT_SECRETS'], TOKENS_DIR, CFG['OAUTH_SCOPES'].split(), CFG['DRIVE_UPLOAD_FOLDER_ID'])

def log_activity(session, item_id, actor, action, details=''):
    a = ActivityLog(email_item_id=item_id, actor=actor, action=action, details=details)
    session.add(a)

@app.teardown_appcontext
def shutdown_session(exception=None):
    Session.remove()

@app.route('/')
def index():
    session = Session()
    q = session.query(EmailItem).order_by(EmailItem.created_at.desc())
    status = request.args.get('status')
    kw = request.args.get('q', '').strip()
    tag = request.args.get('tag','').strip().lower()
    if status and status in Status.__members__:
        q = q.filter(EmailItem.status == Status[status])
    if kw:
        like = f"%{kw}%"
        q = q.filter((EmailItem.subject.ilike(like)) | (EmailItem.snippet.ilike(like)) | (EmailItem.sender.ilike(like)) | (EmailItem.vendor.ilike(like)) | (EmailItem.order_number.ilike(like)) | (EmailItem.sku.ilike(like)) | (EmailItem.customer.ilike(like)) | (EmailItem.tags.ilike(like)))
    if tag:
        q = q.filter(EmailItem.tags.ilike(f"%{tag}%"))
    items = q.limit(1000).all()

    connected_gmails = gmail_mgr.list_connected_accounts()
    has_drive = drive_mgr.is_connected(CFG['SERVICE_GOOGLE_ACCOUNT'])

    # tag cloud
    all_tags = []
    for it in session.query(EmailItem.tags).filter(EmailItem.tags.isnot(None)).all():
        for t in (it[0] or '').split(','):
            t = t.strip()
            if t: all_tags.append(t)
    tag_counts = {}
    for t in all_tags:
        tag_counts[t] = tag_counts.get(t,0)+1
    tag_list = sorted(tag_counts.items(), key=lambda x: (-x[1], x[0]))[:30]

    return render_template('index.html', items=items, kw=kw, status=status,
                           statuses=list(Status.__members__.keys()),
                           monitored=[a for a in CFG['MONITORED_GMAIL_ACCOUNTS'].split(',') if a],
                           connected_gmails=connected_gmails,
                           drive_connected=has_drive,
                           service_account=CFG['SERVICE_GOOGLE_ACCOUNT'],
                           config=CFG,
                           tag=tag,
                           tags=tag_list)

@app.route('/new', methods=['GET','POST'])
def new_item():
    session = Session()
    if request.method == 'POST':
        f = request.form
        item = EmailItem(
            gmail_message_id=None,
            thread_id=None,
            account_email=None,
            sender=f.get('sender') or f.get('customer'),
            subject=f.get('subject') or f"DAMAGE: {f.get('sku','').strip()}",
            date=f.get('date') or '',
            snippet=f.get('notes','')[:500],
            vendor=f.get('vendor') or None,
            order_number=f.get('order_number') or None,
            sku=f.get('sku') or None,
            customer=f.get('customer') or None,
            notes=f.get('notes') or None,
            cost_estimate=Decimal(f.get('cost_estimate') or '0') if f.get('cost_estimate') else None,
            credit_amount=Decimal(f.get('credit_amount') or '0') if f.get('credit_amount') else None,
            assignee=f.get('assignee') or None,
            tags=f.get('tags') or None,
            status=Status[f.get('status')] if f.get('status') in Status.__members__ else Status.NEW
        )
        session.add(item); session.flush()

        files = request.files.getlist('photos')
        uploaded = 0
        for up in files:
            if not up or up.filename == '':
                continue
            data = up.read()
            sha = hashlib.sha256(data).hexdigest()
            try:
                fid, view, content = drive_mgr.upload_photo(CFG['SERVICE_GOOGLE_ACCOUNT'], up.filename, up.mimetype or 'application/octet-stream', data)
                p = Photo(email_item_id=item.id, filename=up.filename, mime_type=up.mimetype, size=str(len(data)),
                          drive_file_id=fid, web_view_link=view, web_content_link=content, sha256=sha)
                session.add(p); uploaded += 1
                log_activity(session, item.id, 'web', 'UPLOAD', f"{up.filename} sha256={sha[:12]}...")
            except Exception as e:
                print('Manual photo upload error:', e)
        log_activity(session, item.id, 'web', 'CREATE', f'Initial status {item.status.value}')
        session.commit()
        flash(f'New damage created (#{item.id}). Photos uploaded: {uploaded}', 'success')
        return redirect(url_for('detail', item_id=item.id))
    return render_template('new.html', statuses=list(Status.__members__.keys()))

@app.route('/detail/<int:item_id>')
def detail(item_id):
    session = Session()
    item = session.get(EmailItem, item_id)
    if not item:
        flash('Item not found', 'warning')
        return redirect(url_for('index'))
    vendor_portal = None
    if item.vendor and item.vendor in VENDOR_PORTALS:
        vendor_portal = VENDOR_PORTALS[item.vendor]
    acts = session.query(ActivityLog).filter(ActivityLog.email_item_id==item.id).order_by(ActivityLog.at.desc()).limit(200).all()
    return render_template('detail.html', item=item, statuses=list(Status.__members__.keys()), vendor_portal=vendor_portal, activities=acts)

@app.route('/items/<int:item_id>/note', methods=['POST'])
def add_note(item_id):
    session = Session()
    item = session.get(EmailItem, item_id)
    if not item:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    note = request.form.get('note','').strip()
    if not note:
        return jsonify({'ok': False, 'error': 'Empty note'}), 400
    item.notes = (item.notes + "\n" if item.notes else "") + note
    log_activity(session, item.id, 'web', 'NOTE', note[:2000])
    session.commit()
    return jsonify({'ok': True})

@app.route('/status/<int:item_id>/<new_status>', methods=['POST'])
def update_status(item_id, new_status):
    session = Session()
    item = session.get(EmailItem, item_id)
    if not item:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    if new_status not in Status.__members__:
        return jsonify({'ok': False, 'error': 'Bad status'}), 400
    old = item.status.value
    item.status = Status[new_status]
    log_activity(session, item.id, 'web', 'STATUS', f'{old} -> {new_status}')

    # auto-emails
    try:
        if new_status == 'APPROVED':
            send_templated_email('vendor_claim_request.html', item, item.photos)
        if new_status == 'CREDIT_RECEIVED':
            send_templated_email('credit_received_notice.html', item, item.photos)
        if new_status == 'CREDIT_USED':
            send_templated_email('credit_used_notice.html', item, item.photos)
    except Exception as e:
        print('Auto-email failed:', e)

    # webhook
    ok, info = send_webhook('status.changed', {'item_id': item.id, 'from': old, 'to': new_status})
    if not ok: print('Webhook warn:', info)

    session.commit()
    return jsonify({'ok': True, 'status': new_status})

@app.route('/items/<int:item_id>/update', methods=['POST'])
def update_item(item_id):
    session = Session()
    item = session.get(EmailItem, item_id)
    if not item:
        flash('Item not found', 'warning')
        return redirect(url_for('index'))
    f = request.form
    fields = ['vendor','order_number','sku','customer','assignee','tags','notes']
    changed = []
    for fld in fields:
        val = f.get(fld)
        if val is not None and val != getattr(item, fld):
            changed.append(f'{fld}:{getattr(item,fld)}→{val}')
            setattr(item, fld, val)
    if f.get('cost_estimate'):
        item.cost_estimate = Decimal(f.get('cost_estimate')); changed.append('cost_estimate updated')
    if f.get('credit_amount'):
        item.credit_amount = Decimal(f.get('credit_amount')); changed.append('credit_amount updated')
    if f.get('status') in Status.__members__:
        old = item.status.value
        item.status = Status[f.get('status')]
        changed.append(f'status {old}->{item.status.value}')
    log_activity(session, item.id, 'web', 'FIELD_UPDATE', '; '.join(changed)[:2000])
    session.commit()
    flash('Item updated.', 'success')
    return redirect(url_for('detail', item_id=item.id))

@app.route('/bulk/status', methods=['POST'])
def bulk_status():
    session = Session()
    ids = request.form.get('ids','').split(',')
    target = request.form.get('status')
    if not ids or not target or target not in Status.__members__:
        return jsonify({'ok': False, 'error': 'Bad request'}), 400
    ids = [int(i) for i in ids if i.strip().isdigit()]
    updated = 0
    for i in ids:
        item = session.get(EmailItem, i)
        if not item: continue
        old = item.status.value
        item.status = Status[target]
        log_activity(session, item.id, 'web', 'STATUS', f'{old} -> {target} (bulk)')
        updated += 1
    session.commit()
    return jsonify({'ok': True, 'updated': updated})

@app.route('/export.csv')
def export_csv():
    session = Session()
    q = session.query(EmailItem).order_by(EmailItem.created_at.desc())
    status = request.args.get('status')
    if status and status in Status.__members__:
        q = q.filter(EmailItem.status == Status[status])
    rows = q.all()
    def gen():
        cols = ['id','created_at','status','vendor','order_number','sku','customer','subject','sender','date','credit_amount','cost_estimate','assignee','tags']
        yield ','.join(cols)+'\n'
        for r in rows:
            vals = [
                str(r.id),
                r.created_at.isoformat(),
                r.status.value,
                r.vendor or '',
                r.order_number or '',
                r.sku or '',
                r.customer or '',
                (r.subject or '').replace(',',' '),
                (r.sender or '').replace(',',' '),
                r.date or '',
                str(r.credit_amount or ''),
                str(r.cost_estimate or ''),
                r.assignee or '',
                (r.tags or '').replace(',','|'),
            ]
            yield ','.join(vals)+'\n'
    return Response(gen(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="damage_export.csv"'})

@app.route('/reports/vendors')
def report_vendors():
    session = Session()
    rows = session.query(
        EmailItem.vendor.label('vendor'),
        func.count(EmailItem.id),
        func.sum(EmailItem.credit_amount)
    ).group_by(EmailItem.vendor).all()

    recv = session.query(EmailItem.vendor, func.sum(EmailItem.credit_amount)).filter(EmailItem.status==Status.CREDIT_RECEIVED).group_by(EmailItem.vendor).all()
    used = session.query(EmailItem.vendor, func.sum(EmailItem.credit_amount)).filter(EmailItem.status==Status.CREDIT_USED).group_by(EmailItem.vendor).all()
    recv_map = {v or '': (amt or 0) for v, amt in recv}
    used_map = {v or '': (amt or 0) for v, amt in used}

    data = []
    for v, cnt, total in rows:
        vn = v or '(Unknown)'
        r = float(recv_map.get(v or '', 0) or 0)
        u = float(used_map.get(v or '', 0) or 0)
        bal = r - u
        data.append({'vendor': vn, 'count': cnt or 0, 'total': float(total or 0), 'credits_received': r, 'credits_used': u, 'balance': bal})
    data.sort(key=lambda x: (-x['balance'], x['vendor']))
    return render_template('report_vendors.html', rows=data)

# --- OAuth connect/finish with dynamic redirect and scope passthrough ---
from flask import url_for
@app.route('/connect/gmail')
def connect_gmail():
    account = request.args.get('account')
    if not account:
        flash('Missing ?account=email', 'warning')
        return redirect(url_for('index'))
    try:
        redirect_uri = url_for('oauth2callback', _external=True)
        authorization_url, state = gmail_mgr.build_authorize_url(account, redirect_uri=redirect_uri)
        return redirect(authorization_url)
    except Exception as e:
        flash(f'OAuth setup error (Gmail): {e}', 'danger')
        return redirect(url_for('index'))

@app.route('/connect/drive')
def connect_drive():
    account = CFG['SERVICE_GOOGLE_ACCOUNT']
    if not account:
        flash('SERVICE_GOOGLE_ACCOUNT is not set.', 'danger')
        return redirect(url_for('index'))
    try:
        redirect_uri = url_for('oauth2callback', _external=True)
        authorization_url, state = drive_mgr.build_authorize_url(account, redirect_uri=redirect_uri)
        return redirect(authorization_url)
    except Exception as e:
        flash(f'OAuth setup error (Drive): {e}', 'danger')
        return redirect(url_for('index'))

@app.route('/oauth2callback')
def oauth2callback():
    code = request.args.get('code')
    state = request.args.get('state')
    returned_scope = request.args.get('scope')
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

# Email template helpers and routes
EMAIL_TEMPLATES_DIR = os.environ.get('EMAIL_TEMPLATES_DIR', os.path.join(os.path.dirname(__file__), 'email_templates'))
DEFAULT_FROM = os.environ.get('EMAIL_FROM', CFG.get('SERVICE_GOOGLE_ACCOUNT'))
DEFAULT_TO = os.environ.get('EMAIL_TO_DEFAULT', CFG.get('NOTIFY_EMAILS'))  # comma-separated fallback

def send_templated_email(template_name: str, item, photos):
    context = {'item': item, 'photos': photos or [], 'service_account': CFG['SERVICE_GOOGLE_ACCOUNT']}
    html = render_email_template(EMAIL_TEMPLATES_DIR, template_name, context)
    subject = f"Damage Tracker: {item.vendor or ''} {item.order_number or ''} {item.sku or ''}".strip()
    tos = [t.strip() for t in (DEFAULT_TO or '').split(',') if t.strip()]
    gmail_mgr.send_email(DEFAULT_FROM, tos, subject=subject, html_body=html)
    return True

@app.route('/items/<int:item_id>/email/preview/<template_name>')
def email_preview(item_id, template_name):
    session = Session()
    item = session.get(EmailItem, item_id)
    if not item:
        return 'Not found', 404
    html = render_email_template(EMAIL_TEMPLATES_DIR, template_name, {'item': item, 'photos': item.photos, 'service_account': CFG['SERVICE_GOOGLE_ACCOUNT']})
    return html

@app.route('/items/<int:item_id>/email/send/<template_name>', methods=['POST'])
def email_send(item_id, template_name):
    session = Session()
    item = session.get(EmailItem, item_id)
    if not item:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    try:
        send_templated_email(template_name, item, item.photos)
        log_activity(session, item.id, 'web', 'EMAIL', f'sent template {template_name}')
        ok, info = send_webhook('email.sent', {'item_id': item.id, 'template': template_name, 'vendor': item.vendor, 'order_number': item.order_number})
        if not ok: print('Webhook warn:', info)
        session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# Cron tasks with secret
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
