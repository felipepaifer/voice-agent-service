import json
import secrets
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict

from flask import current_app
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow

from app.constants import DATA_DIR, GOOGLE_OAUTH_STATE_PATH, GOOGLE_TOKENS_PATH


_store_lock = RLock()
_state_lock = RLock()


def _ensure_file(path, default_payload: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(default_payload, encoding="utf-8")


def _load_json_dict(path, default_payload: str) -> Dict[str, Any]:
    _ensure_file(path, default_payload)
    with path.open("r", encoding="utf-8") as handle:
        raw = handle.read().strip() or default_payload
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _save_json_dict(path, payload: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _oauth_scopes() -> list[str]:
    scope_string = str(current_app.config.get("GOOGLE_CALENDAR_SCOPES", "")).strip()
    return [scope.strip() for scope in scope_string.split(",") if scope.strip()]


def _oauth_client_config() -> Dict[str, Any]:
    client_id = str(current_app.config.get("GOOGLE_OAUTH_CLIENT_ID", "")).strip()
    client_secret = str(
        current_app.config.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    ).strip()
    redirect_uri = str(current_app.config.get("GOOGLE_OAUTH_REDIRECT_URI", "")).strip()
    if not client_id or not client_secret or not redirect_uri:
        raise ValueError(
            "Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID, "
            "GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REDIRECT_URI."
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def _flow(state: str | None = None) -> Flow:
    config = _oauth_client_config()
    redirect_uri = str(current_app.config.get("GOOGLE_OAUTH_REDIRECT_URI", "")).strip()
    flow = Flow.from_client_config(
        config,
        scopes=_oauth_scopes(),
        state=state,
        redirect_uri=redirect_uri,
    )
    return flow


def _credentials_to_payload(credentials: Credentials) -> Dict[str, Any]:
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or []),
        "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_tokens() -> Dict[str, Any]:
    with _store_lock:
        return _load_json_dict(GOOGLE_TOKENS_PATH, "{}")


def _save_tokens(payload: Dict[str, Any]) -> None:
    with _store_lock:
        _save_json_dict(GOOGLE_TOKENS_PATH, payload)


def _load_states() -> Dict[str, Any]:
    with _state_lock:
        return _load_json_dict(GOOGLE_OAUTH_STATE_PATH, "{}")


def _save_states(payload: Dict[str, Any]) -> None:
    with _state_lock:
        _save_json_dict(GOOGLE_OAUTH_STATE_PATH, payload)


def build_connect_url(user_id: str) -> str:
    if not user_id.strip():
        raise ValueError("Missing user_id")
    state_token = secrets.token_urlsafe(32)
    flow = _flow(state=state_token)
    code_verifier = secrets.token_urlsafe(64)
    flow.code_verifier = code_verifier
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    states = _load_states()
    states[state_token] = {
        "user_id": user_id.strip(),
        "code_verifier": code_verifier,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_states(states)
    return auth_url


def finalize_oauth_callback(code: str, state: str) -> Dict[str, Any]:
    if not code or not state:
        return {"status": "error", "error": "Missing code/state"}

    states = _load_states()
    state_entry = states.get(state)
    if not state_entry:
        return {"status": "error", "error": "Invalid or expired OAuth state"}

    user_id = str(state_entry.get("user_id", "")).strip()
    code_verifier = str(state_entry.get("code_verifier", "")).strip()
    if not user_id:
        return {"status": "error", "error": "State did not include user"}
    if not code_verifier:
        return {"status": "error", "error": "Missing OAuth code verifier in state"}

    flow = _flow(state=state)
    flow.code_verifier = code_verifier
    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials
    except Exception:
        return {"status": "error", "error": "Failed to exchange OAuth code for token"}

    tokens = _load_tokens()
    existing = tokens.get(user_id, {})
    payload = _credentials_to_payload(credentials)
    if not payload.get("refresh_token") and isinstance(existing, dict):
        previous_refresh = existing.get("refresh_token")
        if isinstance(previous_refresh, str) and previous_refresh:
            payload["refresh_token"] = previous_refresh
    tokens[user_id] = payload
    _save_tokens(tokens)
    states.pop(state, None)
    _save_states(states)
    return {"status": "connected", "user_id": user_id}


def get_connection_status(user_id: str) -> Dict[str, Any]:
    normalized_user_id = (user_id or "").strip()
    if not normalized_user_id:
        return {"connected": False, "error": "Missing user_id"}
    tokens = _load_tokens()
    entry = tokens.get(normalized_user_id)
    if not isinstance(entry, dict):
        return {"connected": False}
    return {
        "connected": True,
        "scopes": entry.get("scopes", []),
        "expiry": entry.get("expiry"),
    }


def disconnect_user(user_id: str) -> Dict[str, Any]:
    normalized_user_id = (user_id or "").strip()
    if not normalized_user_id:
        return {"status": "error", "error": "Missing user_id"}
    tokens = _load_tokens()
    tokens.pop(normalized_user_id, None)
    _save_tokens(tokens)
    return {"status": "disconnected", "user_id": normalized_user_id}


def _credentials_from_user(user_id: str) -> Credentials | None:
    tokens = _load_tokens()
    entry = tokens.get(user_id)
    if not isinstance(entry, dict):
        return None

    expiry = entry.get("expiry")
    parsed_expiry = None
    if isinstance(expiry, str) and expiry:
        try:
            parsed_expiry = datetime.fromisoformat(expiry)
        except ValueError:
            parsed_expiry = None

    creds = Credentials(
        token=entry.get("token"),
        refresh_token=entry.get("refresh_token"),
        token_uri=entry.get("token_uri"),
        client_id=entry.get("client_id"),
        client_secret=entry.get("client_secret"),
        scopes=entry.get("scopes"),
    )
    if parsed_expiry:
        creds.expiry = parsed_expiry

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tokens[user_id] = _credentials_to_payload(creds)
        _save_tokens(tokens)
    return creds


def create_calendar_event(
    *,
    user_id: str,
    title: str,
    description: str,
    location: str = "",
    start_iso: str,
    end_iso: str,
    timezone: str,
) -> Dict[str, Any]:
    normalized_user_id = (user_id or "").strip()
    if not normalized_user_id:
        return {"status": "skipped", "reason": "missing_user_id"}

    creds = _credentials_from_user(normalized_user_id)
    if not creds:
        return {"status": "skipped", "reason": "google_not_connected"}

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    event = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": timezone},
        "end": {"dateTime": end_iso, "timeZone": timezone},
    }
    normalized_location = (location or "").strip()
    if normalized_location:
        event["location"] = normalized_location
    created = (
        service.events()  # noqa: E1101
        .insert(calendarId="primary", body=event)
        .execute()
    )
    return {
        "status": "created",
        "provider": "google_calendar",
        "event_id": created.get("id"),
        "html_link": created.get("htmlLink"),
    }
