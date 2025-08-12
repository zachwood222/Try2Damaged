import json, requests, os

def send_webhook(event: str, payload: dict):
    url = os.getenv('WEBHOOK_URL') or os.getenv('KENECT_WEBHOOK_URL')
    if not url:
        return False, 'No WEBHOOK_URL / KENECT_WEBHOOK_URL configured'
    headers = {'Content-Type': 'application/json'}
    token = os.getenv('WEBHOOK_TOKEN') or os.getenv('KENECT_API_KEY')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        r = requests.post(url, headers=headers, data=json.dumps({'event': event, 'payload': payload}))
        return r.ok, f'{r.status_code}'
    except Exception as e:
        return False, str(e)
