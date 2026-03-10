import json
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict

from app.constants import DATA_DIR, SESSION_REGISTRY_PATH


_lock = RLock()


def _ensure_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SESSION_REGISTRY_PATH.exists():
        SESSION_REGISTRY_PATH.write_text("{}", encoding="utf-8")


def _load_store() -> Dict[str, Any]:
    _ensure_store()
    with SESSION_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        content = handle.read().strip() or "{}"
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_store(payload: Dict[str, Any]) -> None:
    with SESSION_REGISTRY_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def remember_session_user(room: str, user_id: str) -> None:
    normalized_room = (room or "").strip()
    normalized_user_id = (user_id or "").strip()
    if not normalized_room or not normalized_user_id:
        return

    with _lock:
        payload = _load_store()
        payload[normalized_room] = {
            "user_id": normalized_user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_store(payload)


def get_user_id_for_room(room: str) -> str | None:
    normalized_room = (room or "").strip()
    if not normalized_room:
        return None
    with _lock:
        payload = _load_store()
        entry = payload.get(normalized_room, {})
    user_id = entry.get("user_id")
    if isinstance(user_id, str) and user_id.strip():
        return user_id.strip()
    return None
