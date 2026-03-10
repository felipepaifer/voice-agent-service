from flask import Blueprint

from app.constants import API_PREFIX
from app.controllers.agent_controller import start_session, trigger_sms


agent_bp = Blueprint("agent", __name__, url_prefix=f"{API_PREFIX}/agent")

agent_bp.post("/session")(start_session)
agent_bp.post("/call")(trigger_sms)
