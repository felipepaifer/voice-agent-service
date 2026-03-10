from flask import Blueprint

from app.constants import API_PREFIX
from app.controllers.agent_controller import start_session, trigger_sms
from app.middlewares import require_api_key


agent_bp = Blueprint("agent", __name__, url_prefix=f"{API_PREFIX}/agent")

agent_bp.post("/session")(require_api_key(start_session))
agent_bp.post("/call")(require_api_key(trigger_sms))
