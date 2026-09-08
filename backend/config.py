import os
import secrets

from dotenv import load_dotenv

load_dotenv()


def _cors_origins(allow_wildcard=True):
    """Parse CORS_ORIGINS (comma-separated) into a list of origins.

    Dev/testing fall back to ``["*"]`` when unset. Production
    (``allow_wildcard=False``) must enumerate explicit origins: an unset or
    empty CORS_ORIGINS yields an empty list so cross-origin browser requests
    are refused rather than allowed from anywhere.
    """
    raw = os.environ.get("CORS_ORIGINS", "")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if origins:
        return origins
    return ["*"] if allow_wildcard else []


def _deploy_mode(flask_config=None):
    """Resolve the deployment mode from DEPLOY_MODE env or FLASK_CONFIG.

    Returns one of: 'local', 'lan', 'online'.
    """
    raw = os.environ.get("DEPLOY_MODE", "").strip().lower()
    if raw in ("local", "lan", "online"):
        return raw
    cfg = flask_config or os.environ.get("FLASK_CONFIG", "development")
    if cfg == "production":
        return "online"
    return "local"


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    JSON_SORT_KEYS = False
    CORS_ORIGINS = _cors_origins()
    PORT = int(os.environ.get("PORT", "5000"))
    DEVICE_HEARTBEAT_TIMEOUT = int(os.environ.get("DEVICE_HEARTBEAT_TIMEOUT", "60"))
    DEVICE_HEARTBEAT_GRACE_MULTIPLIER = int(os.environ.get("DEVICE_HEARTBEAT_GRACE_MULTIPLIER", "3"))
    HOST_INACTIVITY_TIMEOUT = int(os.environ.get("HOST_INACTIVITY_TIMEOUT", "900"))
    SWEEPER_INTERVAL = int(os.environ.get("SWEEPER_INTERVAL", "30"))
    QR_BASE_URL = os.environ.get("QR_BASE_URL", "")
    DEPLOY_MODE = _deploy_mode()
    RATE_LIMIT_MULTIPLIER = int(os.environ.get("RATE_LIMIT_MULTIPLIER", "1"))
    # --- AI word generator (Google Gemini, backend-only) ---
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    AI_MAX_WORDS_PER_REQUEST = int(os.environ.get("AI_MAX_WORDS_PER_REQUEST", "20"))
    AI_REQUEST_COOLDOWN_SECONDS = int(os.environ.get("AI_REQUEST_COOLDOWN_SECONDS", "5"))
    AI_MAX_REQUESTS_PER_MINUTE = int(os.environ.get("AI_MAX_REQUESTS_PER_MINUTE", "5"))


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SECRET_KEY = BaseConfig.SECRET_KEY or secrets.token_hex(32)


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL") or "sqlite:///:memory:"
    CORS_ORIGINS = ["*"]
    # Keep tests deterministic — the local backend/.env (RATE_LIMIT_MULTIPLIER,
    # HOST_INACTIVITY_TIMEOUT, …) must never shape the testing config.
    RATE_LIMIT_MULTIPLIER = 1
    HOST_INACTIVITY_TIMEOUT = 900
    DEVICE_HEARTBEAT_TIMEOUT = 60
    DEVICE_HEARTBEAT_GRACE_MULTIPLIER = 3
    # No live AI calls in tests — tests monkeypatch the word generator instead.
    GEMINI_API_KEY = ""
    GEMINI_MODEL = "gemini-2.0-flash"
    AI_MAX_WORDS_PER_REQUEST = 20
    AI_REQUEST_COOLDOWN_SECONDS = 5
    AI_MAX_REQUESTS_PER_MINUTE = 5


class ProductionConfig(BaseConfig):
    DEBUG = False
    CORS_ORIGINS = _cors_origins(allow_wildcard=False)


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}