from datetime import datetime, timedelta
from sqlalchemy import select
from models import EmailItem, Photo, Status
from email_utils import build_notification_html, build_daily_summary_html

KEYWORDS_QUERY = 'newer_than:14d ("damage" OR "credit" OR "replacement")'

def scan_gmail_accounts(session, gmail_mgr, drive_mgr, CFG):
    updated = 0
    accounts = [a.strip() for a in CFG['MONITORED_GMAIL_ACCOUNTS'].split(',') if a.strip()]
    service_account = CFG['SERVICE_GOOGLE_ACCOUNT']

    for account in accounts:
        msgs = gmail_mgr.search_messages(account, KEYWORDS_QUERY, max_results=100)
        for m in msgs:
            msg_id = m['id']
            exists = session.query(EmailItem).filter_by(gmail_message_id=msg_id).first()
            if exists:
                continue
            full = gmail_mgr.get_message(account, msg_id)
            headers = {h['name'].lower(): h['value'] for h in full.get('payload', {}).get('headers', [])}
            sender = headers.get('from','(unknown)')
            subject = headers.get('subject','(no subject)')
            date = headers.get('date','')
            snippet = full.get('snippet','')

            item = EmailItem(
                gmail_message_id=msg_id,
                thread_id=full.get('threadId'),
                account_email=account,
                sender=sender,
                subject=subject,
                date=date,
                snippet=snippet,
                status=Status.NEW
            )
            session.add(item); session.flush()

            atts = gmail_mgr.fetch_attachments(account, full)
            photos = []
            for att in atts:
                try:
                    import hashlib
                    fid, view, content = drive_mgr.upload_photo(service_account, att['filename'], att['mimeType'], att['data'])
                    sha = hashlib.sha256(att['data']).hexdigest()
                    p = Photo(email_item_id=item.id, filename=att['filename'], mime_type=att['mimeType'], size=att['size'],
                              drive_file_id=fid, web_view_link=view, web_content_link=content, sha256=sha)
                    session.add(p); photos.append(p)
                except Exception as e:
                    print('Drive upload error:', e)

            try:
                html = build_notification_html(item, photos)
                tos = [t.strip() for t in CFG['NOTIFY_EMAILS'].split(',') if t.strip()]
                gmail_mgr.send_email(CFG['SERVICE_GOOGLE_ACCOUNT'], tos, subject=f"Damage Tracker: {subject}", html_body=html)
            except Exception as e:
                print('Notification send error:', e)

            updated += 1

    return updated

def send_daily_summary(session, gmail_mgr, CFG):
    since = datetime.utcnow() - timedelta(days=1)
    items = session.query(EmailItem).filter(EmailItem.created_at >= since).order_by(EmailItem.created_at.desc()).all()
    from email_utils import build_daily_summary_html
    html = build_daily_summary_html(items)
    tos = [t.strip() for t in CFG['NOTIFY_EMAILS'].split(',') if t.strip()]
    try:
        gmail_mgr.send_email(CFG['SERVICE_GOOGLE_ACCOUNT'], tos, subject="Damage Tracker: Daily Summary", html_body=html)
        return True
    except Exception as e:
        print('Daily summary send error:', e)
        return False
