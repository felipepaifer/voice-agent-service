from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class Booking:
    id: Optional[str]
    listing_id: str
    datetime: str
    name: str
    phone: str
    user_id: Optional[str] = None
    calendar_event_id: Optional[str] = None
    calendar_event_url: Optional[str] = None

    def to_dict(self) -> Dict[str, str]:
        payload: Dict[str, str] = {
            "listing_id": self.listing_id,
            "datetime": self.datetime,
            "name": self.name,
            "phone": self.phone,
        }
        if self.user_id:
            payload["user_id"] = self.user_id
        if self.calendar_event_id:
            payload["calendar_event_id"] = self.calendar_event_id
        if self.calendar_event_url:
            payload["calendar_event_url"] = self.calendar_event_url
        return payload
