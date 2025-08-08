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

    def build_authorize_url(self, email, redirect_uri):
    flow = Flow.from_client_secrets_file(self.client_secrets_file, scopes=self.scopes, redirect_uri=redirect_uri)
    state = f"drive:{email}"
    url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='false',  # avoid Google adding openid/userinfo automatically
        state=state
    )
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


    def upload_photo(self, email, filename, mime_type, data: bytes):
        svc = self._service(email)
        file_metadata = {'name': filename, 'parents': [self.upload_folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink, webContentLink').execute()
        file_id = file['id']
        svc.permissions().create(fileId=file_id, body={'type':'anyone','role':'reader'}).execute()
        return file_id, file.get('webViewLink'), file.get('webContentLink')
