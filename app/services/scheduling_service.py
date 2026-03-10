import json
from datetime import datetime, timedelta
from threading import RLock
from typing import Dict, List
from zoneinfo import ZoneInfo

from app.constants import BOOKINGS_PATH, DATA_DIR
from app.models.booking import Booking
from app.services.config_service import load_config
from app.services.google_calendar_service import create_calendar_event


_lock = RLock()


def _ensure_bookings_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not BOOKINGS_PATH.exists():
        BOOKINGS_PATH.write_text("[]", encoding="utf-8")


def list_bookings() -> List[Dict]:
    _ensure_bookings_file()
    with _lock, BOOKINGS_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _scheduling_policy() -> Dict:
    scheduling = dict(load_config().get("scheduling", {}))
    return {
        "timezone": str(scheduling.get("timezone", "America/Los_Angeles")),
        "start_hour": int(scheduling.get("start_hour", 9)),
        "end_hour": int(scheduling.get("end_hour", 20)),
        "slot_minutes": int(scheduling.get("slot_minutes", 60)),
    }


def _development_id() -> str:
    development = dict(load_config().get("development", {}))
    return str(development.get("id", "DEV-LA-001"))


def _parse_datetime(value: str, timezone: str) -> datetime:
    clean_value = (value or "").strip()
    accepted_formats = (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    )
    for fmt in accepted_formats:
        try:
            parsed = datetime.strptime(clean_value, fmt)
            return parsed.replace(tzinfo=ZoneInfo(timezone))
        except ValueError:
            continue
    raise ValueError("Invalid datetime format. Use YYYY-MM-DD HH:MM.")


def _slot_is_valid(scheduled_at: datetime, policy: Dict) -> bool:
    start_hour = policy["start_hour"]
    end_hour = policy["end_hour"]
    slot_minutes = policy["slot_minutes"]

    if scheduled_at.minute % slot_minutes != 0:
        return False
    if scheduled_at.second != 0 or scheduled_at.microsecond != 0:
        return False

    appointment_start = scheduled_at.hour + (scheduled_at.minute / 60)
    appointment_end = appointment_start + (slot_minutes / 60)
    return appointment_start >= start_hour and appointment_end <= end_hour


def _slot_key(scheduled_at: datetime) -> str:
    return scheduled_at.strftime("%Y-%m-%d %H:%M")


def is_slot_available(slot_datetime: str) -> bool:
    policy = _scheduling_policy()
    timezone = policy["timezone"]
    requested_at = _parse_datetime(slot_datetime, timezone)
    if not _slot_is_valid(requested_at, policy):
        return False

    target = _slot_key(requested_at)
    for booking in list_bookings():
        existing_raw = str(booking.get("datetime", ""))
        try:
            existing_at = _parse_datetime(existing_raw, timezone)
        except ValueError:
            # Skip malformed historical records.
            continue
        if _slot_key(existing_at) == target:
            return False
    return True


def schedule_viewing(
    listing_id: str,
    datetime: str,
    name: str,
    phone: str,
    user_id: str = "",
    create_calendar_event_enabled: bool = True,
) -> Dict:
    _ensure_bookings_file()
    policy = _scheduling_policy()
    timezone = policy["timezone"]

    try:
        requested_at = _parse_datetime(datetime, timezone)
    except ValueError as exc:
        return {"status": "invalid_datetime", "error": str(exc)}

    if not _slot_is_valid(requested_at, policy):
        return {
            "status": "outside_schedule_window",
            "error": "Viewings are available in 60-minute slots from 09:00 to 20:00.",
        }

    normalized_slot = _slot_key(requested_at)
    booking = Booking(
        id=None,
        listing_id=listing_id or _development_id(),
        datetime=normalized_slot,
        name=name,
        phone=phone,
        user_id=user_id.strip() or None,
        calendar_event_id=None,
        calendar_event_url=None,
    )

    slot_minutes = int(policy["slot_minutes"])
    slot_end = requested_at.replace(second=0, microsecond=0) + timedelta(
        minutes=slot_minutes
    )

    development = dict(load_config().get("development", {}))
    title = f"Viewing - {development.get('name', 'Development')}"
    description = f"Client: {name}"
    location = str(development.get("address", "")).strip()
    if create_calendar_event_enabled:
        calendar_result = create_calendar_event(
            user_id=user_id,
            title=title,
            description=description,
            location=location,
            start_iso=requested_at.isoformat(),
            end_iso=slot_end.isoformat(),
            timezone=timezone,
        )
    else:
        calendar_result = {
            "status": "skipped",
            "reason": "google_calendar_tool_disabled",
        }
    if calendar_result.get("status") not in {"created", "skipped"}:
        return {
            "status": "calendar_event_failed",
            "error": "Could not create calendar event. Booking not committed.",
            "calendar": calendar_result,
        }
    if calendar_result.get("status") == "created":
        booking.calendar_event_id = str(calendar_result.get("event_id") or "")
        booking.calendar_event_url = str(calendar_result.get("html_link") or "")

    with _lock:
        bookings = list_bookings()
        for existing in bookings:
            existing_raw = str(existing.get("datetime", ""))
            try:
                existing_at = _parse_datetime(existing_raw, timezone)
            except ValueError:
                continue
            if _slot_key(existing_at) == normalized_slot:
                return {
                    "status": "slot_unavailable",
                    "error": "That time is already booked. Please choose another slot.",
                }

        bookings.append(booking.to_dict())
        with BOOKINGS_PATH.open("w", encoding="utf-8") as handle:
            json.dump(bookings, handle, indent=2)

    return {"status": "scheduled", "calendar": calendar_result, **booking.to_dict()}
