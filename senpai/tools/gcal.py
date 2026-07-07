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
        try:
            creds.refresh(Request())
        except Exception:  # noqa: BLE001 — token revoked/expired: redo consent
            creds = None
    if not (creds and creds.valid):
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


def list_events(date: str, tz: str = "Asia/Tokyo") -> tuple[bool, list[dict]]:
    """List the day's events from the primary Google Calendar.

    Returns (ok, events) where each event is {"start": "HH:MM" | "終日",
    "summary": str}. On any failure returns (False, []) and the caller falls
    back to simulated data, mirroring create_event's contract.
    """
    try:
        from googleapiclient.discovery import build

        day = datetime.strptime(date, "%Y-%m-%d")
        # Day bounds expressed in the target timezone (JST has no DST).
        offset = "+09:00" if tz == "Asia/Tokyo" else "Z"
        time_min = day.strftime(f"%Y-%m-%dT00:00:00{offset}")
        time_max = (day + timedelta(days=1)).strftime(f"%Y-%m-%dT00:00:00{offset}")

        service = build("calendar", "v3", credentials=_get_credentials(),
                        cache_discovery=False)
        resp = service.events().list(
            calendarId="primary", timeMin=time_min, timeMax=time_max,
            singleEvents=True, orderBy="startTime", timeZone=tz,
            maxResults=25,
        ).execute()

        events = []
        for item in resp.get("items", []):
            start = item.get("start", {})
            if "dateTime" in start:
                # e.g. 2026-07-07T10:00:00+09:00 -> 10:00
                when = start["dateTime"][11:16]
            else:
                when = "終日"  # all-day event
            events.append({"start": when, "summary": item.get("summary", "(無題)")})
        return True, events
    except Exception:  # noqa: BLE001 — caller falls back to simulated data
        return False, []
