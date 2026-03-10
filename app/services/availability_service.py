from datetime import datetime, timedelta
from typing import List
from zoneinfo import ZoneInfo

from app.services.config_service import load_config
from app.services.scheduling_service import list_bookings

def check_availability(listing_id: str, date: str) -> List[str]:
    scheduling = dict(load_config().get("scheduling", {}))
    timezone = str(scheduling.get("timezone", "America/Los_Angeles"))
    start_hour = int(scheduling.get("start_hour", 9))
    end_hour = int(scheduling.get("end_hour", 20))
    slot_minutes = int(scheduling.get("slot_minutes", 60))

    try:
        day = datetime.strptime((date or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return []
    start_of_window = datetime(
        day.year, day.month, day.day, start_hour, 0, tzinfo=ZoneInfo(timezone)
    )
    last_start_hour = end_hour - (slot_minutes // 60)
    last_start = datetime(
        day.year, day.month, day.day, last_start_hour, 0, tzinfo=ZoneInfo(timezone)
    )

    booked = set()
    for booking in list_bookings():
        value = str(booking.get("datetime", "")).strip()
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(value, fmt).replace(
                    tzinfo=ZoneInfo(timezone)
                )
                booked.add(parsed.strftime("%Y-%m-%d %H:%M"))
                break
            except ValueError:
                continue

    slots: List[str] = []
    current = start_of_window
    while current <= last_start:
        key = current.strftime("%Y-%m-%d %H:%M")
        if key not in booked:
            slots.append(key)
        current += timedelta(minutes=slot_minutes)

    return slots
