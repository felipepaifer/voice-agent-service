from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

CONFIG_PATH = DATA_DIR / "config.json"
BOOKINGS_PATH = DATA_DIR / "bookings.json"
GOOGLE_TOKENS_PATH = DATA_DIR / "google_tokens.json"
GOOGLE_OAUTH_STATE_PATH = DATA_DIR / "google_oauth_state.json"
SESSION_REGISTRY_PATH = DATA_DIR / "session_registry.json"

API_PREFIX = "/api"
