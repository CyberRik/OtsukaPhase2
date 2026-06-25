"""Real Google Calendar booking for senpai's `schedule_meeting` tool.

Mirrors demo/gcal.py, but resolves the OAuth files from the **repo root**
(credentials.json / token.json) since that is where they are kept for the
workspace bridge. Isolated from impl.py so a missing google library or auth
failure can never break tool import. The single entry point `create_event(...)`
returns `(ok: bool, message: str)` — on any failure (no creds, no token,
network, API error) it returns `(False, reason)` and the caller falls back to a
simulated confirmation, so the workspace never breaks.

One-time setup (see demo/demo_script.md for the screenshots):
  1. Google Cloud Console → enable the Google Calendar API.
  2. Create an OAuth client ID (Desktop app) → save JSON as ./credentials.json.
  3. Add yourself as a test user on the OAuth consent screen.
  4. First call opens a browser consent once and writes ./token.json.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
# senpai/tools/gcal.py -> repo root is two parents up from the package dir.
_ROOT = Path(__file__).resolve().parents[2]
_CREDENTIALS = _ROOT / "credentials.json"
_TOKEN = _ROOT / "token.json"


def _get_credentials():
    """Load/refresh OAuth credentials, running the consent flow if needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if _TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not _CREDENTIALS.exists():
            raise FileNotFoundError(
                f"missing {_CREDENTIALS} (Google OAuth client). See demo/demo_script.md.")
        flow = InstalledAppFlow.from_client_secrets_file(str(_CREDENTIALS), SCOPES)
        creds = flow.run_local_server(port=0)
    _TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def create_event(title: str, date: str, start_time: str, duration_hours: float = 1,
                 attendees=None, description: str = "",
                 tz: str = "Asia/Tokyo") -> tuple[bool, str]:
    """Create a Google Calendar event. Returns (ok, message)."""
    try:
        from googleapiclient.discovery import build

        start_dt = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(hours=float(duration_hours or 1))
        attendees = attendees or []

        body = {
            "summary": title,
            "description": description or "",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": tz},
        }
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]

        service = build("calendar", "v3", credentials=_get_credentials(),
                        cache_discovery=False)
        event = service.events().insert(calendarId="primary", body=body).execute()

        link = event.get("htmlLink", "")
        return True, link
    except Exception as e:  # noqa: BLE001 — caller falls back to a simulated booking
        return False, f"calendar unavailable: {e}"
