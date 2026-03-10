import json
from threading import Lock
from typing import Any, Dict

from app.constants import CONFIG_PATH, DATA_DIR
from app.models.agent_settings import AgentSettings
from app.models.config import DEFAULT_CONFIG


_lock = Lock()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, Any]:
    return load_config_model().to_dict()


def load_config_model() -> AgentSettings:
    _ensure_data_dir()
    if not CONFIG_PATH.exists():
        default_settings = AgentSettings.from_dict(DEFAULT_CONFIG)
        save_config_model(default_settings)
        return default_settings

    with _lock, CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return AgentSettings.from_dict(json.load(handle))


def save_config(config: Dict[str, Any]) -> None:
    save_config_model(AgentSettings.from_dict(config))


def save_config_model(config: AgentSettings) -> None:
    _ensure_data_dir()
    with _lock, CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config.to_dict(), handle, indent=2)


def sanitize_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    config = load_config_model()

    if "system_prompt" in payload and isinstance(payload["system_prompt"], str):
        config.system_prompt = payload["system_prompt"].strip()

    persona = payload.get("persona", {})
    if isinstance(persona, dict):
        config.persona.name = (persona.get("name") or config.persona.name).strip()
        config.persona.greeting = (
            persona.get("greeting") or config.persona.greeting
        ).strip()
        config.persona.voice = (persona.get("voice") or config.persona.voice).strip()

    tools = payload.get("tools", {})
    if isinstance(tools, dict):
        for key in config.tools.to_dict():
            if isinstance(tools.get(key), bool):
                setattr(config.tools, key, tools[key])
        if not config.tools.schedule_viewing:
            config.tools.check_availability = False
            config.tools.google_calendar_mcp = False
            config.tools.send_sms_confirmation = False

    development = payload.get("development", {})
    if isinstance(development, dict):
        existing = dict(config.development or {})
        for key in (
            "id",
            "name",
            "city",
            "address",
            "description",
            "story",
            "neighborhood",
        ):
            if isinstance(development.get(key), str) and development.get(key).strip():
                existing[key] = development[key].strip()

        if isinstance(development.get("starting_price"), (int, float)):
            existing["starting_price"] = development["starting_price"]

        amenities = development.get("amenities")
        if isinstance(amenities, list):
            existing["amenities"] = [
                str(item).strip() for item in amenities if str(item).strip()
            ]
        nearby = development.get("nearby")
        if isinstance(nearby, list):
            existing["nearby"] = [str(item).strip() for item in nearby if str(item).strip()]
        config.development = existing

    scheduling = payload.get("scheduling", {})
    if isinstance(scheduling, dict):
        existing = dict(config.scheduling or {})
        if isinstance(scheduling.get("timezone"), str) and scheduling.get(
            "timezone"
        ).strip():
            existing["timezone"] = scheduling["timezone"].strip()

        for key in ("start_hour", "end_hour", "slot_minutes"):
            value = scheduling.get(key)
            if isinstance(value, int):
                existing[key] = value
        config.scheduling = existing

    notifications = payload.get("notifications", {})
    if isinstance(notifications, dict):
        existing = dict(config.notifications or {})
        if isinstance(notifications.get("default_phone"), str):
            existing["default_phone"] = notifications["default_phone"].strip()
        for key in ("use_default_phone", "require_phone_confirmation"):
            value = notifications.get(key)
            if isinstance(value, bool):
                existing[key] = value
        config.notifications = existing

    return config.to_dict()
