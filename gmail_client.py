import base64, pathlib
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

def _create_message(sender, to, subject, html_body):
    msg = MIMEText(html_body, 'html')
    msg['To'] = to
    msg['From'] = sender
    msg['Subject'] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {'raw': raw}

class GmailManager:
    def __init__(self, client_secrets_file, tokens_dir, scopes):
        self.client_secrets_file = client_secrets_file
        self.tokens_dir = pathlib.Path(tokens_dir)
        self.scopes = scopes

    def _token_path(self, email):
        safe = email.replace('@','_at_')
        return self.tokens_dir / f"token_{safe}.json"

    def list_connected_accounts(self):
        return [p.name.replace('token_','').replace('_at_','@').replace('.json','') for p in self.tokens_dir.glob('token_*.json')]

    def _load_credentials(self, email):
        token_path = self._token_path(email)
        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), self.scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds

    def is_connected(self, email):
        creds = self._load_credentials(email)
        return bool(creds and creds.valid)

    def build_authorize_url(self, email, redirect_uri):
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=self.scopes,
            redirect_uri=redirect_uri,
        )
        state = f"gmail:{email}"
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='false',
            state=state
        )
        return auth_url, state

    def finish_authorize(self, email, code, redirect_uri, returned_scope=None):
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=self.scopes,
            redirect_uri=redirect_uri,
        )
        if returned_scope:
            flow.fetch_token(code=code, scope=returned_scope)
        else:
            flow.fetch_token(code=code)
        creds = flow.credentials
        with open(self._token_path(email), 'w') as f:
            f.write(creds.to_json())
        return True

    def _service(self, email):
        creds = self._load_credentials(email)
        if not creds:
            raise RuntimeError(f"No Gmail credentials for {email}. Connect via UI.")
        return build('gmail', 'v1', credentials=creds)

    def search_messages(self, email, query, max_results=25):
        svc = self._service(email)
        resp = svc.users().messages().list(userId='me', q=query, maxResults=max_results).execute()
        return resp.get('messages', [])

    def get_message(self, email, msg_id):
        svc = self._service(email)
        return svc.users().messages().get(userId='me', id=msg_id, format='full').execute()

    def fetch_attachments(self, email, message):
        svc = self._service(email)
        attachments = []
        payload = message.get('payload', {})
        parts = payload.get('parts') or [payload]
        for part in parts:
            mime = part.get('mimeType','')
            body = part.get('body', {})
            filename = part.get('filename')
            if not filename:
                continue
            if not (mime.startswith('image/') or any(filename.lower().endswith(ext) for ext in ['.jpg','.jpeg','.png','.heic','.gif','.webp'])):
                continue
            att_id = body.get('attachmentId')
            if not att_id:
                continue
            att = svc.users().messages().attachments().get(userId='me', messageId=message['id'], id=att_id).execute()
            import base64 as b64
            data = b64.urlsafe_b64decode(att['data'])
            attachments.append({
                'filename': filename,
                'mimeType': mime or 'application/octet-stream',
                'data': data,
                'size': str(len(data))
            })
        return attachments

    def send_email(self, sender_email, to_emails, subject, html_body):
        svc = self._service(sender_email)
        if isinstance(to_emails, str):
            to_emails = [to_emails]
        for to in to_emails:
            message = _create_message(sender_email, to, subject, html_body)
            svc.users().messages().send(userId='me', body=message).execute()
