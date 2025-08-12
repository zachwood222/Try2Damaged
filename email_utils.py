from markupsafe import escape

def build_notification_html(item, photos):
    def a(url, text):
        return f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(text)}</a>'
    photo_links = '<p>(No photos found)</p>'
    if photos:
        photo_links = '<ul>' + ''.join(f'<li>{a(p.web_view_link, p.filename)}</li>' for p in photos) + '</ul>'
    html = f"""
    <h3>New Damage/Credit/Replacement Email Tracked</h3>
    <p><b>From:</b> {escape(item.sender)}<br>
       <b>Subject:</b> {escape(item.subject)}<br>
       <b>Date:</b> {escape(item.date)}<br>
       <b>Account:</b> {escape(item.account_email)}</p>
    <p><b>Snippet:</b> {escape(item.snippet or '')}</p>
    <p><b>Photos:</b>{photo_links}</p>
    <p>Open in tracker: <a href="/detail/{item.id}">View Item</a></p>
    """
    return html

def build_daily_summary_html(items):
    if not items:
        return '<p>No new items today.</p>'
    rows = ''.join(f"<tr><td>{escape(i.date)}</td><td>{escape(i.sender)}</td><td>{escape(i.subject)}</td><td>{escape(i.status.value)}</td></tr>" for i in items)
    return f"""
    <h3>Daily Damage Summary</h3>
    <table border="1" cellpadding="6" cellspacing="0">
      <thead><tr><th>Date</th><th>From</th><th>Subject</th><th>Status</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """
