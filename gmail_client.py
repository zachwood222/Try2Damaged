import base64
from email.mime.text import MIMEText
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
    def __init__(self, client_secrets_file, token_store, scopes):
        self.client_secrets_file = client_secrets_file
        self.token_store = token_store
        self.scopes = scopes

    def list_connected_accounts(self):
        return self.token_store.list_accounts()

    def _service(self, email):
        creds = self.token_store.load(email, self.scopes)
        if not creds or not creds.valid:
            raise RuntimeError(f"No Gmail credentials for {email}. Connect via UI.")
        return build('gmail', 'v1', credentials=creds)

    def build_authorize_url(self, email, redirect_uri):
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=self.scopes,
            redirect_uri=redirect_uri,
        )
        state = f"gmail:{email}"
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='false',  # avoid Google adding openid/userinfo automatically
            state=state
        )
        return auth_url, state

    def finish_authorize(self, email, code, redirect_uri, returned_scope=None):
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=self.scopes,
            redirect_uri=redirect_uri,
        )
        # Pass back the returned_scope to avoid oauthlib scope-mismatch 500s
        if returned_scope:
            flow.fetch_token(code=code, scope=returned_scope)
        else:
            flow.fetch_token(code=code)
        creds = flow.credentials
        with open(self._token_path(email), 'w') as f:
            f.write(creds.to_json())
        return True

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
            if not mime.startswith('image/'):
                if not any(filename.lower().endswith(ext) for ext in ['.jpg','.jpeg','.png','.heic','.gif','.webp']):
                    continue
            att_id = body.get('attachmentId')
            if not att_id:
                continue
            att = svc.users().messages().attachments().get(userId='me', messageId=message['id'], id=att_id).execute()
            data = base64.urlsafe_b64decode(att['data'])
            attachments.append({'filename': filename, 'mimeType': mime, 'data': data, 'size': str(len(data))})
        return attachments

    def send_email(self, sender_email, to_emails, subject, html_body):
        svc = self._service(sender_email)
        if isinstance(to_emails, str):
            to_emails = [to_emails]
        for to in to_emails:
            message = _create_message(sender_email, to, subject, html_body)
            svc.users().messages().send(userId='me', body=message).execute()
