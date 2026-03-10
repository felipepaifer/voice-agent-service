import logging
import re
from typing import Dict

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from app.config import AppConfig

logger = logging.getLogger(__name__)


def _normalize_phone(phone: str) -> str:
    raw = (phone or "").strip()
    if not raw:
        return ""
    has_plus = raw.startswith("+")
    digits_only = re.sub(r"\D", "", raw)
    if not digits_only:
        return ""
    return f"+{digits_only}" if has_plus else digits_only


def _is_e164(phone: str) -> bool:
    # Basic E.164 validation: + followed by 7-15 digits.
    return bool(re.fullmatch(r"\+[1-9]\d{6,14}", (phone or "").strip()))


def send_sms_confirmation(
    phone: str, message: str, permission_granted: bool
) -> Dict:
    if not permission_granted:
        return {
            "status": "blocked",
            "reason": "Permission not granted for SMS.",
        }

    normalized_phone = _normalize_phone(phone)

    sms_message = (message or "").strip()

    if not normalized_phone or not sms_message:
        return {"status": "failed", "reason": "Phone and message required."}
    if not _is_e164(normalized_phone):
        return {
            "status": "invalid_phone",
            "reason": "Phone must be in E.164 format, for example +12125551234.",
        }
    config = None
    try:
        from flask import current_app

        config = current_app.config
    except Exception:
        config = None

    if config is None:
        config = AppConfig().__dict__

    account_sid = config.get("TWILIO_ACCOUNT_SID", "")
    auth_token = config.get("TWILIO_AUTH_TOKEN", "")
    from_number = config.get("TWILIO_FROM_NUMBER", "")

    if not (account_sid and auth_token and from_number):
        return {
            "status": "mocked",
            "message": "Twilio not configured. SMS not sent.",
        }

    if not _is_e164(from_number):
        return {
            "status": "provider_misconfigured",
            "reason": "TWILIO_FROM_NUMBER must be a valid E.164 phone number.",
        }

    client = Client(account_sid, auth_token)
    try:
        sms = client.messages.create(
            to=normalized_phone,
            from_=from_number,
            body=sms_message,
        )
    except TwilioRestException as exc:
        logger.warning(
            "Twilio SMS failed code=%s status=%s msg=%s",
            getattr(exc, "code", None),
            getattr(exc, "status", None),
            str(exc),
        )
        return {
            "status": "provider_rejected",
            "reason": str(exc),
            "code": getattr(exc, "code", None),
        }
    except Exception as exc:
        logger.exception("Unexpected SMS failure")
        return {"status": "failed", "reason": f"Unexpected SMS error: {exc}"}

    return {"status": "sent", "sid": sms.sid}
