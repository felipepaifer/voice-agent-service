from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.models.agent_persona import AgentPersona
from app.models.agent_tools import AgentTools


@dataclass
class AgentSettings:
    id: Optional[str]
    system_prompt: str
    persona: AgentPersona
    tools: AgentTools
    development: Dict[str, Any]
    scheduling: Dict[str, Any]
    notifications: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "persona": self.persona.to_dict(),
            "tools": self.tools.to_dict(),
            "development": self.development,
            "scheduling": self.scheduling,
            "notifications": self.notifications,
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "AgentSettings":
        return AgentSettings(
            id=payload.get("id"),
            system_prompt=str(payload.get("system_prompt", "")).strip(),
            persona=AgentPersona.from_dict(payload.get("persona", {})),
            tools=AgentTools.from_dict(payload.get("tools", {})),
            development=dict(payload.get("development", {})),
            scheduling=dict(payload.get("scheduling", {})),
            notifications={
                "default_phone": str(
                    dict(payload.get("notifications", {})).get("default_phone", "")
                ).strip(),
                "use_default_phone": bool(
                    dict(payload.get("notifications", {})).get(
                        "use_default_phone", False
                    )
                ),
                "require_phone_confirmation": bool(
                    dict(payload.get("notifications", {})).get(
                        "require_phone_confirmation", True
                    )
                ),
            },
        )
