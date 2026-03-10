from flask import Blueprint

from app.constants import API_PREFIX
from app.controllers.admin_controller import (
    get_config,
    google_callback,
    google_connect,
    google_disconnect,
    google_status,
    update_config,
)
from app.middlewares import require_api_key


admin_bp = Blueprint("admin", __name__, url_prefix=f"{API_PREFIX}/admin")

admin_bp.get("/config")(require_api_key(get_config))
admin_bp.post("/config")(require_api_key(update_config))
admin_bp.post("/google/connect")(require_api_key(google_connect))
admin_bp.get("/google/status")(require_api_key(google_status))
admin_bp.post("/google/disconnect")(require_api_key(google_disconnect))
admin_bp.get("/google/callback")(google_callback)
