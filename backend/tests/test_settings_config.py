"""Tests for app.config.settings.Settings environment parsing.

Regression coverage for the CORS_ORIGINS parsing bug: a plain
comma-separated (non-JSON) env value must be accepted. Before the NoDecode
fix, pydantic-settings tried to JSON-decode the list field from the env
source and raised SettingsError at import, crashing the whole backend.
"""

import pytest

from app.config.settings import Settings


@pytest.fixture(autouse=True)
def setup_database():
    """No-op override: settings tests need no database."""
    yield


@pytest.fixture(autouse=True)
def _clean_cors_env(monkeypatch):
    """Ensure a deterministic environment for each test."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-value-not-insecure-1234567890")


def test_single_origin_plain_string(monkeypatch):
    """A single non-JSON origin string parses into a one-element list."""
    monkeypatch.setenv("CORS_ORIGINS", "https://capado.lab.example.test")
    settings = Settings()
    assert settings.cors_origins == ["https://capado.lab.example.test"]


def test_comma_separated_origins(monkeypatch):
    """A comma-separated origin string parses into a list, trimming spaces."""
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://a.example.test, https://b.example.test",
    )
    settings = Settings()
    assert settings.cors_origins == [
        "https://a.example.test",
        "https://b.example.test",
    ]


def test_default_origins_when_unset():
    """Unset CORS_ORIGINS falls back to the localhost defaults."""
    settings = Settings()
    assert settings.cors_origins == [
        "http://localhost:3000",
        "http://localhost:5173",
    ]


def test_wildcard_rejected(monkeypatch):
    """A wildcard origin is rejected in favor of the localhost defaults."""
    monkeypatch.setenv("CORS_ORIGINS", "*")
    settings = Settings()
    assert "*" not in settings.cors_origins
    assert settings.cors_origins == [
        "http://localhost:3000",
        "http://localhost:5173",
    ]


def test_production_requires_secret(monkeypatch):
    """Production refuses to start without a strong JWT secret."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        Settings()


def test_cookie_secure_derived_from_environment(monkeypatch):
    """cookie_secure defaults to True in production, False otherwise."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "a-strong-production-secret-000000000000")
    assert Settings().refresh_cookie_secure is True

    monkeypatch.setenv("ENVIRONMENT", "development")
    assert Settings().refresh_cookie_secure is False
