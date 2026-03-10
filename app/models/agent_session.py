from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class AgentSession:
    id: Optional[str]
    room: str
    identity: str
    url: str
    token: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, str]:
        payload: Dict[str, str] = {
            "room": self.room,
            "identity": self.identity,
            "url": self.url,
        }
        if self.token:
            payload["token"] = self.token
        if self.error:
            payload["error"] = self.error
        return payload
