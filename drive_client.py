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
    def __init__(
        self,
        client_secrets_file: str = None,
        token_dir: str = "tokens",
        scopes: Optional[list] = None,
    ):
        self.client_secrets_file = client_secrets_file or os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "client_secret.json")
        self.token_dir = Path(token_dir)
        self.token_dir.mkdir(parents=True, exist_ok=True)
        self.scopes = scopes or OPENID_SCOPES

        if not Path(self.client_secrets_file).exists():
            raise FileNotFoundError(f"Missing Google client secrets at {self.client_secrets_file}")

    def _token_path(self, email: str) -> Path:
        return self.token_dir / f"{_sanitize(email)}.json"

    # ---- YOU CALLED THIS IN YOUR ROUTE ----
    def build_authorize_url(self, email: str, redirect_uri: str) -> Tuple[str, str]:
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=self.scopes,
            redirect_uri=redirect_uri,
        )
        state = f"drive:{email}"
        authorization_url, flow_state = flow.authorization_url(
            access_type="offline",          # get refresh token
            include_granted_scopes=True,    # boolean True (not string)
            prompt="consent",               # ensures refresh token is returned
            state=state,
        )
        return authorization_url, flow_state  # you can also return state if desired

    # ---- YOU CALLED THIS IN YOUR CALLBACK ----
    def finish_authorize(self, email: str, authorization_response_url: str, redirect_uri: str, state: Optional[str] = None) -> bool:
        flow = Flow.from_client_secrets_file(
            self.client_secrets_file,
            scopes=self.scopes,
            redirect_uri=redirect_uri,
            state=state,
        )
        # Important: don't pass scope here; use the same scopes as the Flow
        flow.fetch_token(authorization_response=authorization_response_url)

        creds = flow.credentials
        self._token_path(email).write_text(creds.to_json())
        return True

    # Optional helper: load/refresh credentials later when calling APIs
    def load_credentials(self, email: str) -> Optional[Credentials]:
        token_file = self._token_path(email)
        if not token_file.exists():
            return None
        creds = Credentials.from_authorized_user_file(str(token_file), scopes=self.scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_file.write_text(creds.to_json())
        return creds
