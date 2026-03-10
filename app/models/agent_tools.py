from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class AgentTools:
    id: Optional[str]
    search_listings: bool
    check_availability: bool
    schedule_viewing: bool
    google_calendar_mcp: bool
    send_sms_confirmation: bool

    def to_dict(self) -> Dict[str, bool]:
        return {
            "search_listings": self.search_listings,
            "check_availability": self.check_availability,
            "schedule_viewing": self.schedule_viewing,
            "google_calendar_mcp": self.google_calendar_mcp,
            "send_sms_confirmation": self.send_sms_confirmation,
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "AgentTools":
        return AgentTools(
            id=payload.get("id"),
            search_listings=bool(payload.get("search_listings", True)),
            check_availability=bool(payload.get("check_availability", True)),
            schedule_viewing=bool(payload.get("schedule_viewing", True)),
            google_calendar_mcp=bool(payload.get("google_calendar_mcp", True)),
            send_sms_confirmation=bool(payload.get("send_sms_confirmation", True)),
        )
