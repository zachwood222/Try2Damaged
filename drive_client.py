# drive_client.py
import os
from pathlib import Path
from typing import Tuple, Optional

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

OPENID_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
]

def _sanitize(email: str) -> str:
    return email.replace("/", "_").replace("\\", "_").replace(":", "_")

# drive_client.py
import os
from pathlib import Path
from typing import Tuple, Optional
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

OPENID_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
]

def _sanitize(email: str) -> str:
    return email.replace("/", "_").replace("\\", "_").replace(":", "_")

class DriveManager:
    def __init__(self, client_secrets_file: str, token_dir: str = "tokens", scopes: Optional[list] = None):
        self.client_secrets_file = client_secrets_file
        self.token_dir = Path(token_dir)
        self.token_dir.mkdir(parents=True, exist_ok=True)
        self.scopes = scopes or OPENID_SCOPES

        data = Path(self.client_secrets_file).read_text(encoding="utf-8")
        if '"web"' not in data:
            raise ValueError("Your client_secret.json is not a Web application credential. Create a Web OAuth client in Google Cloud Console.")

    def _token_path(self, email: str) -> Path:
        return self.token_dir / f"{_sanitize(email)}.json"

    def build_authorize_url(self, email: str, redirect_uri: str) -> Tuple[str, str]:
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=self.scopes,
            redirect_uri=redirect_uri,
        )
        state = f"drive:{email}"
        authorization_url, flow_state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes=True,
            prompt="consent",
            state=state,
        )
        return authorization_url, flow_state

    def finish_authorize(self, email: str, authorization_response_url: str, redirect_uri: str, state: Optional[str] = None) -> bool:
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=self.scopes,
            redirect_uri=redirect_uri,
            state=state,
        )
        # Do NOT pass scope here; use the same scopes as the Flow
        flow.fetch_token(authorization_response=authorization_response_url)
        creds = flow.credentials
        self._token_path(email).write_text(creds.to_json(), encoding="utf-8")
        return True

    def load_credentials(self, email: str) -> Optional[Credentials]:
        token_file = self._token_path(email)
        if not token_file.exists():
            return None
        creds = Credentials.from_authorized_user_file(str(token_file), scopes=self.scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds

