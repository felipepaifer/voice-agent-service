from typing import Dict

from flask import current_app
from livekit import api

from app.models.agent_session import AgentSession


def create_session_token(room: str, identity: str) -> Dict:
    api_key = current_app.config.get("LIVEKIT_API_KEY", "")
    api_secret = current_app.config.get("LIVEKIT_API_SECRET", "")
    url = current_app.config.get("LIVEKIT_URL", "")

    if not (api_key and api_secret and url):
        return AgentSession(
            id=None,
            room=room,
            identity=identity,
            url=url,
            error="LiveKit is not configured.",
        ).to_dict()

    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )

    return AgentSession(
        id=None,
        room=room,
        identity=identity,
        url=url,
        token=token,
    ).to_dict()
