from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class AgentPersona:
    id: Optional[str]
    name: str
    greeting: str
    voice: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "greeting": self.greeting,
            "voice": self.voice,
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "AgentPersona":
        return AgentPersona(
            id=payload.get("id"),
            name=str(payload.get("name", "Alex")),
            greeting=str(
                payload.get(
                    "greeting",
                    "Hi, this is Alex with Riverside Realty. How can I help?",
                )
            ),
            voice=str(payload.get("voice", "Rachel")),
        )
