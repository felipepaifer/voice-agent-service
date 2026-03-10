import uuid

from flask import jsonify, request

from app.services.livekit_service import create_session_token
from app.services.session_context_service import remember_session_user
from app.services.sms_service import send_sms_confirmation


def start_session():
    payload = request.get_json(silent=True) or {}
    room_hint = str(payload.get("room") or "real-estate-demo").strip()
    room = f"{room_hint}-{uuid.uuid4().hex[:8]}"
    user_id = str(payload.get("user_id") or "").strip()
    identity = (
        str(payload.get("identity") or "").strip() or f"caller-{uuid.uuid4().hex[:8]}"
    )

    session = create_session_token(room=room, identity=identity)

    if user_id:
        remember_session_user(room=room, user_id=user_id)

    return jsonify(session)


def trigger_sms():
    payload = request.get_json(silent=True) or {}
    phone = payload.get("phone", "")
    message = payload.get("message", "")
    permission_granted = payload.get("permission_granted", False)

    result = send_sms_confirmation(
        phone=phone, message=message, permission_granted=permission_granted
    )
    
    return jsonify(result)
