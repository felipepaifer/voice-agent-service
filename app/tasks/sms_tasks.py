from app.tasks.celery_app import celery_app
from app.services.sms_service import send_sms_confirmation


@celery_app.task
def send_sms_task(phone: str, message: str, permission_granted: bool):
    return send_sms_confirmation(
        phone=phone,
        message=message,
        permission_granted=permission_granted,
    )
