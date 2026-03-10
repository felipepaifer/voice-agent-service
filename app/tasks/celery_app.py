from celery import Celery

from app.config import AppConfig


def make_celery() -> Celery:
    config = AppConfig()
    celery = Celery(
        "tasks",
        broker="memory://",
        backend="cache+memory://",
    )
    celery.conf.task_always_eager = config.CELERY_TASK_ALWAYS_EAGER
    return celery


celery_app = make_celery()
