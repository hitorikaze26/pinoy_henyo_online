import os

from dotenv import load_dotenv

load_dotenv()


def _cors_origins():
    raw = os.environ.get("CORS_ORIGINS", "*")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["*"]


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    JSON_SORT_KEYS = False
    CORS_ORIGINS = _cors_origins()
    PORT = int(os.environ.get("PORT", "5000"))
    DEVICE_HEARTBEAT_TIMEOUT = int(os.environ.get("DEVICE_HEARTBEAT_TIMEOUT", "60"))
    # Host-disconnect reconciliation: a game whose host has been absent for
    # longer than HOST_INACTIVITY_TIMEOUT seconds is marked EXPIRED (not deleted).
    HOST_INACTIVITY_TIMEOUT = int(os.environ.get("HOST_INACTIVITY_TIMEOUT", "900"))
    SWEEPER_INTERVAL = int(os.environ.get("SWEEPER_INTERVAL", "30"))
    QR_BASE_URL = os.environ.get("QR_BASE_URL", "https://pinoyhenyo.online")


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SECRET_KEY = BaseConfig.SECRET_KEY or "dev-secret-key-change-me"


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL") or "sqlite:///:memory:"
    CORS_ORIGINS = ["*"]


class ProductionConfig(BaseConfig):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}