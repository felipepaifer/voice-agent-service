from flask import Flask
from flask_cors import CORS

from app.config import AppConfig
from app.routes.admin import admin_bp
from app.routes.agent import agent_bp


def create_app() -> Flask:
    app = Flask(__name__)
    settings = AppConfig()
    app.config.from_object(settings)
    origins = [
        origin.strip()
        for origin in settings.FRONTEND_ORIGINS.split(",")
        if origin.strip()
    ]
    if settings.FRONTEND_ORIGIN and settings.FRONTEND_ORIGIN not in origins:
        origins.append(settings.FRONTEND_ORIGIN)

    CORS(app, resources={r"/api/*": {"origins": origins}})

    app.register_blueprint(admin_bp)
    app.register_blueprint(agent_bp)

    return app
