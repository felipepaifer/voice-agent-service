from flask import jsonify, request

from app.services.config_service import load_config, save_config, sanitize_config
from app.services.google_calendar_service import (
    build_connect_url,
    disconnect_user,
    finalize_oauth_callback,
    get_connection_status,
)


def get_config():
    config = load_config()
    return jsonify(config)


def update_config():
    payload = request.get_json(silent=True) or {}
    updated = sanitize_config(payload)
    save_config(updated)
    return jsonify({"status": "ok", "config": updated})


def google_connect():
    payload = request.get_json(silent=True) or {}
    user_id = str(payload.get("user_id", "")).strip()
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400
    try:
        auth_url = build_connect_url(user_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"auth_url": auth_url})


def google_callback():
    code = str(request.args.get("code", "")).strip()
    state = str(request.args.get("state", "")).strip()
    result = finalize_oauth_callback(code=code, state=state)
    if result.get("status") != "connected":
        return (
            "<!doctype html><html><body><h3>Google Calendar connection failed.</h3>"
            "<p>You can close this window and try again.</p>"
            "<script>"
            "try {"
            "if (window.opener) {"
            "window.opener.postMessage({type:'google-calendar-oauth',status:'error'}, '*');"
            "window.close();"
            "}"
            "} catch (e) {}"
            "</script>"
            "</body></html>",
            400,
            {"Content-Type": "text/html; charset=utf-8"},
        )
    return (
        "<!doctype html><html><body><h3>Google Calendar connected.</h3>"
        "<p>You can close this window.</p>"
        "<script>"
        "try {"
        "if (window.opener) {"
        "window.opener.postMessage({type:'google-calendar-oauth',status:'connected'}, '*');"
        "window.close();"
        "}"
        "} catch (e) {}"
        "</script>"
        "</body></html>",
        200,
        {"Content-Type": "text/html; charset=utf-8"},
    )


def google_status():
    user_id = str(request.args.get("user_id", "")).strip()
    status = get_connection_status(user_id)
    return jsonify(status)


def google_disconnect():
    payload = request.get_json(silent=True) or {}
    user_id = str(payload.get("user_id", "")).strip()
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400
    result = disconnect_user(user_id)
    if result.get("status") == "error":
        return jsonify(result), 400
    return jsonify(result)
