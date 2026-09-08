"""Regression tests for environment-aware configuration.

Covers the localhost / LAN / Cloudflare-online deployment split added to
config.py:

- DEPLOY_MODE resolution (env + FLASK_CONFIG fallback),
- deterministic testing config (immune to a local backend/.env),
- non-predictable development SECRET_KEY,
- production CORS wildcard refusal.
"""

import config
import pytest
from app import create_app


@pytest.fixture()
def app():
    test_app = create_app("testing")
    yield test_app


# ---------------------------------------------------------------------------
# Deployment-mode resolution
# ---------------------------------------------------------------------------


def test_deploy_mode_from_env(monkeypatch):
    for mode in ("local", "lan", "online"):
        monkeypatch.setenv("DEPLOY_MODE", mode)
        assert config._deploy_mode() == mode


def test_deploy_mode_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "LAN")
    assert config._deploy_mode() == "lan"


def test_deploy_mode_falls_back_to_production_flask_config(monkeypatch):
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    monkeypatch.setenv("FLASK_CONFIG", "production")
    assert config._deploy_mode() == "online"


def test_deploy_mode_defaults_to_local(monkeypatch):
    monkeypatch.delenv("DEPLOY_MODE", raising=False)
    monkeypatch.setenv("FLASK_CONFIG", "development")
    assert config._deploy_mode() == "local"


def test_deploy_mode_ignores_unknown_values(monkeypatch):
    monkeypatch.setenv("DEPLOY_MODE", "bogus")
    monkeypatch.setenv("FLASK_CONFIG", "production")
    assert config._deploy_mode() == "online"


def test_base_qr_url_defaults_to_empty():
    assert config.BaseConfig.QR_BASE_URL == ""


# ---------------------------------------------------------------------------
# Determinism / security
# ---------------------------------------------------------------------------


def test_development_secret_is_not_predictable():
    assert config.DevelopmentConfig.SECRET_KEY
    assert len(config.DevelopmentConfig.SECRET_KEY) == 64
    assert config.DevelopmentConfig.SECRET_KEY != "dev-secret-key-change-me"


def test_development_debug_is_enabled():
    assert config.DevelopmentConfig.DEBUG is True


def test_production_debug_is_disabled():
    assert config.ProductionConfig.DEBUG is False


def test_testing_config_is_deterministic(app):
    # A local backend/.env must never shape the test run.
    assert app.config["RATE_LIMIT_MULTIPLIER"] == 1
    assert app.config["HOST_INACTIVITY_TIMEOUT"] == 900
    assert app.config["DEVICE_HEARTBEAT_TIMEOUT"] == 60
    assert app.config["DEVICE_HEARTBEAT_GRACE_MULTIPLIER"] == 3
    assert app.config["SECRET_KEY"] == "test-secret-key"
    assert app.config["QR_BASE_URL"] == ""


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def test_cors_origins_parse_csv(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    assert config._cors_origins() == ["https://a.example", "https://b.example"]


def test_production_cors_refuses_wildcard(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "")
    assert config._cors_origins(allow_wildcard=False) == []


def test_production_cors_allows_explicit_origins(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS", "https://game.example.com,https://game.example.org"
    )
    assert config._cors_origins(allow_wildcard=False) == [
        "https://game.example.com",
        "https://game.example.org",
    ]