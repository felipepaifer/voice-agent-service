import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)


@dataclass
class AppConfig:
    ENV: str = os.getenv("FLASK_ENV", "development")
    DEBUG: bool = os.getenv("FLASK_DEBUG", "true").lower() == "true"
    API_PREFIX: str = os.getenv("API_PREFIX", "/api")
    PORT: int = int(os.getenv("PORT", "8000"))
    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    FRONTEND_ORIGINS: str = os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )

    LIVEKIT_URL: str = os.getenv("LIVEKIT_URL", "")
    LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "")
    LIVEKIT_API_SECRET: str = os.getenv("LIVEKIT_API_SECRET", "")

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_LLM_MODEL: str = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")
    OPENAI_STT_MODEL: str = os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
    OPENAI_REALTIME_ENABLED: bool = (
        os.getenv("OPENAI_REALTIME_ENABLED", "true").lower() == "true"
    )
    OPENAI_REALTIME_MODEL: str = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime")
    OPENAI_REALTIME_VOICE: str = os.getenv("OPENAI_REALTIME_VOICE", "marin")
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
    ELEVENLABS_DEFAULT_VOICE_ID: str = os.getenv("ELEVENLABS_DEFAULT_VOICE_ID", "")
    ELEVENLABS_TTS_MODEL: str = os.getenv("ELEVENLABS_TTS_MODEL", "eleven_turbo_v2_5")
    ELEVENLABS_STREAMING_LATENCY: int = int(
        os.getenv("ELEVENLABS_STREAMING_LATENCY", "1")
    )

    AGENT_MIN_ENDPOINTING_DELAY: float = float(
        os.getenv("AGENT_MIN_ENDPOINTING_DELAY", "0.05")
    )
    AGENT_MAX_ENDPOINTING_DELAY: float = float(
        os.getenv("AGENT_MAX_ENDPOINTING_DELAY", "0.20")
    )
    AGENT_MIN_INTERRUPTION_DURATION: float = float(
        os.getenv("AGENT_MIN_INTERRUPTION_DURATION", "0.25")
    )

    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER: str = os.getenv("TWILIO_FROM_NUMBER", "")

    CELERY_TASK_ALWAYS_EAGER: bool = (
        os.getenv("CELERY_TASK_ALWAYS_EAGER", "true").lower() == "true"
    )

    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "")
    GOOGLE_OAUTH_CLIENT_ID: str = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    GOOGLE_OAUTH_CLIENT_SECRET: str = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    GOOGLE_OAUTH_REDIRECT_URI: str = os.getenv(
        "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/admin/google/callback"
    )
    GOOGLE_CALENDAR_SCOPES: str = os.getenv(
        "GOOGLE_CALENDAR_SCOPES", "https://www.googleapis.com/auth/calendar.events"
    )
