import io, pathlib
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

class DriveManager:
    def __init__(self, client_secrets_file, tokens_dir, scopes, upload_folder_id):
        self.client_secrets_file = client_secrets_file
        self.tokens_dir = pathlib.Path(tokens_dir)
        self.scopes = scopes
        self.upload_folder_id = upload_folder_id

    def _token_path(self, email):
        safe = email.replace('@','_at_')
        return self.tokens_dir / f"token_{safe}.json"

    def _load_credentials(self, email):
        p = self._token_path(email)
        if not p.exists():
            return None
        creds = Credentials.from_authorized_user_file(str(p), self.scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds

    def is_connected(self, email):
        c = self._load_credentials(email)
        return bool(c and c.valid)

    def build_authorize_url(self, email, redirect_uri):
        flow = Flow.from_client_secrets_file(self.client_secrets_file, scopes=self.scopes, redirect_uri=redirect_uri)
        state = f"drive:{email}"
        url, _ = flow.authorization_url(access_type='offline', include_granted_scopes='false', state=state)
        return url, state

    def finish_authorize(self, email, code, redirect_uri, returned_scope=None):
        flow = Flow.from_client_secrets_file(self.client_secrets_file, scopes=self.scopes, redirect_uri=redirect_uri)
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
            raise RuntimeError(f"No Drive credentials for {email}. Connect via UI.")
        return build('drive', 'v3', credentials=creds)

    def upload_photo(self, email, filename, mime_type, data: bytes):
        svc = self._service(email)
        file_metadata = {'name': filename, 'parents': [self.upload_folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type or 'application/octet-stream', resumable=False)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink, webContentLink').execute()
        file_id = file['id']
        svc.permissions().create(fileId=file_id, body={'type':'anyone','role':'reader'}).execute()
        return file_id, file.get('webViewLink'), file.get('webContentLink')
