import io
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

class DriveManager:
    def __init__(self, client_secrets_file, token_store, scopes, upload_folder_id):
        self.client_secrets_file = client_secrets_file
        self.token_store = token_store
        self.scopes = scopes
        self.upload_folder_id = upload_folder_id

    def is_connected(self, email):
        creds = self.token_store.load(email, self.scopes)
        return bool(creds and creds.valid)

    def _service(self, email):
        creds = self.token_store.load(email, self.scopes)
        if not creds or not creds.valid:
            raise RuntimeError(f"No Drive credentials for {email}. Connect via UI.")
        return build('drive', 'v3', credentials=creds)

    from google_auth_oauthlib.flow import Flow
from pathlib import Path

def build_authorize_url(self, email, redirect_uri):
    flow = Flow.from_client_secrets_file(
        self.client_secrets_file,
        scopes=self.scopes,              # must match finish_authorize
        redirect_uri=redirect_uri,
    )
    state = f"drive:{email}"
    authorization_url, flow_state = flow.authorization_url(
        access_type="offline",           # get refresh_token
        include_granted_scopes=True,     # boolean, not string
        prompt="consent",                # ensures refresh_token
        state=state,
    )
    # You can return flow_state if you want to verify in the callback.
    return authorization_url, state

def finish_authorize(self, email, code, redirect_uri, returned_scope=None):
    flow = Flow.from_client_secrets_file(
        self.client_secrets_file,
        scopes=self.scopes,              # EXACT same list as above
        redirect_uri=redirect_uri,
        # state=<retrieve the saved state if you’re verifying CSRF>
    )
    # IMPORTANT: do NOT pass scope here
    flow.fetch_token(code=code)

    creds = flow.credentials
    token_path = Path(self._token_path(email))
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return True


    def upload_photo(self, email, filename, mime_type, data: bytes):
        svc = self._service(email)
        file_metadata = {'name': filename, 'parents': [self.upload_folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink, webContentLink').execute()
        file_id = file['id']
        svc.permissions().create(fileId=file_id, body={'type':'anyone','role':'reader'}).execute()
        return file_id, file.get('webViewLink'), file.get('webContentLink')
