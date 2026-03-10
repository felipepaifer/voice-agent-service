from functools import wraps
from typing import Iterable

from flask import current_app, jsonify, request


def require_api_key(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        api_key = current_app.config.get("ADMIN_API_KEY")
        if not api_key:
            return view_func(*args, **kwargs)

        provided = request.headers.get("x-api-key", "")
        if provided != api_key:
            return jsonify({"error": "Unauthorized"}), 401

        return view_func(*args, **kwargs)

    return wrapper


def validate_json(required_keys: Iterable[str]):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not request.is_json:
                return jsonify({"error": "Expected JSON body"}), 400
            payload = request.get_json(silent=True) or {}
            missing = [key for key in required_keys if key not in payload]
            if missing:
                return (
                    jsonify({"error": "Missing required fields", "fields": missing}),
                    400,
                )
            return view_func(*args, **kwargs)

        return wrapper

    return decorator
