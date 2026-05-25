"""Google OAuth helper. Handles the one-time browser auth and token refresh."""
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from src.config import settings


# Scopes describe what permissions we're asking for.
# readonly is the principle of least privilege - we only need to read.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_credentials() -> Credentials:
    """
    Returns valid Google credentials.

    First run: opens a browser for you to grant permission, saves token.json.
    Subsequent runs: loads token.json and refreshes if needed.
    """
    creds = None
    token_path = settings.google_token_path

    # Load existing token if we have one
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # If creds are missing or invalid, refresh or re-auth
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("No valid credentials, starting OAuth flow...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(settings.google_credentials_path), SCOPES
            )
            # This opens a browser window for the user to authorize
            creds = flow.run_local_server(port=0)

        # Save for next time
        token_path.write_text(creds.to_json())
        print(f"Token saved to {token_path}")

    return creds
