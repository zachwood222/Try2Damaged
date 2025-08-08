from models import OAuthToken
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

class DBTokenStore:
    """Stores Google OAuth tokens in the database (works on Render free tier)."""
    def __init__(self, SessionFactory):
        self.SessionFactory = SessionFactory

    def list_accounts(self):
        s = self.SessionFactory()
        try:
            rows = s.query(OAuthToken.email).distinct().all()
            return [r[0] for r in rows]
        finally:
            s.close()

    def load(self, email, scopes):
        s = self.SessionFactory()
        try:
            row = s.query(OAuthToken).filter_by(email=email).first()
            if not row:
                return None
            creds = Credentials.from_authorized_user_info(eval(row.token_json), scopes=scopes)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.save(email, row.provider, creds)
            return creds
        finally:
            s.close()

    def save(self, email, provider, creds: Credentials):
        s = self.SessionFactory()
        try:
            data = creds.to_json()
            row = s.query(OAuthToken).filter_by(email=email, provider=provider).first()
            if row:
                row.token_json = data
            else:
                row = OAuthToken(email=email, provider=provider, token_json=data)
                s.add(row)
            s.commit()
        finally:
            s.close()
