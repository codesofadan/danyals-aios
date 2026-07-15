"""Chunk 2 gate: config + logging."""

from __future__ import annotations

import json

import pytest
import structlog
from pydantic import SecretStr

from app.config import ConfigError, Settings, validate_settings
from app.logging_setup import configure_logging, get_logger

_ENV_KEYS = [
    "APP_ENV",
    "LOG_LEVEL",
    "API_CORS_ORIGINS",
    "TRUSTED_HOSTS",
    "DATABASE_URL",
    "DATABASE_ADMIN_URL",
    "JWT_PRIVATE_KEY",
    "JWT_PUBLIC_KEY",
    "LOCAL_JWT_ISSUER",
    "JWT_AUDIENCE",
    "VAULT_MASTER_KEY",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "READINESS_TIMEOUT_SECONDS",
    "SENTRY_DSN",
]

# A complete set of the prod-required config, for the validate_settings tests.
_PROD_REQUIRED = {
    "database_url": "postgresql://authenticated:pw@localhost:5432/aios",
    "database_admin_url": "postgresql://service_role:pw@localhost:5432/aios",
    "jwt_private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n",
    "jwt_public_key": "-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----\n",
    "vault_master_key": "dmF1bHQtbWFzdGVyLWtleS0zMi1ieXRlcy1sb25nISE=",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make config tests hermetic regardless of the developer's shell env."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.unit
def test_defaults_load_without_env() -> None:
    s = Settings(_env_file=None)
    assert s.app_env == "dev"
    assert s.is_prod is False
    assert s.docs_enabled is True
    # separate Redis logical DBs: cache /0, broker /1, results /2
    assert s.redis_url.endswith("/0")
    assert s.celery_broker_url.endswith("/1")
    assert s.celery_result_backend.endswith("/2")


@pytest.mark.unit
def test_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("DATABASE_URL", "postgresql://authenticated:pw@localhost:5432/aios")
    monkeypatch.setenv("LOCAL_JWT_ISSUER", "aios-prod")
    s = Settings(_env_file=None)
    assert s.is_prod is True
    assert s.database_url == "postgresql://authenticated:pw@localhost:5432/aios"
    assert s.local_jwt_issuer == "aios-prod"


@pytest.mark.unit
def test_cors_origins_list_strips_and_drops_empties() -> None:
    s = Settings(_env_file=None, api_cors_origins="http://a.com, http://b.com ,")
    assert s.cors_origins_list == ["http://a.com", "http://b.com"]


@pytest.mark.unit
def test_log_level_is_normalized() -> None:
    s = Settings(_env_file=None, log_level="debug")
    assert s.log_level == "DEBUG"


@pytest.mark.unit
def test_secrets_are_masked() -> None:
    s = Settings(_env_file=None, vault_master_key="topsecret")
    assert isinstance(s.vault_master_key, SecretStr)
    assert "topsecret" not in repr(s)
    assert "topsecret" not in str(s.vault_master_key)
    assert s.vault_master_key.get_secret_value() == "topsecret"


@pytest.mark.unit
def test_local_migration_secrets_are_masked() -> None:
    # P6A dual-config secrets (own-JWT signing key + vault master key) must also
    # be SecretStr and never render in a repr / log.
    s = Settings(
        _env_file=None,
        jwt_private_key="PRIV_KEY_SECRET",
        vault_master_key="VAULT_MASTER_SECRET",
    )
    assert isinstance(s.jwt_private_key, SecretStr)
    assert isinstance(s.vault_master_key, SecretStr)
    dump = repr(s)
    assert "PRIV_KEY_SECRET" not in dump
    assert "VAULT_MASTER_SECRET" not in dump
    assert s.jwt_private_key.get_secret_value() == "PRIV_KEY_SECRET"
    assert s.vault_master_key.get_secret_value() == "VAULT_MASTER_SECRET"


@pytest.mark.unit
def test_local_settings_default_to_none() -> None:
    # The local-Postgres + auth settings default to None (a dev app boots without
    # them; validate_settings only fails on absence in prod).
    s = Settings(_env_file=None)
    assert s.database_url is None
    assert s.database_admin_url is None
    assert s.jwt_private_key is None
    assert s.jwt_public_key is None
    assert s.vault_master_key is None
    assert s.local_jwt_issuer == "aios"
    assert s.jwt_audience == "authenticated"


@pytest.mark.unit
def test_validate_prod_missing_raises() -> None:
    s = Settings(_env_file=None, app_env="prod")
    with pytest.raises(ConfigError):
        validate_settings(s)


@pytest.mark.unit
def test_validate_prod_blank_secret_raises() -> None:
    # blank env arrives as "" / SecretStr("") -> falsiness (not `is None`) must catch it
    s = Settings(_env_file=None, app_env="prod", **{**_PROD_REQUIRED, "jwt_private_key": ""})
    with pytest.raises(ConfigError):
        validate_settings(s)


@pytest.mark.unit
def test_validate_dev_missing_does_not_raise() -> None:
    s = Settings(_env_file=None, app_env="dev")
    validate_settings(s)  # warns, does not raise


@pytest.mark.unit
def test_validate_prod_complete_ok() -> None:
    s = Settings(_env_file=None, app_env="prod", **_PROD_REQUIRED)
    validate_settings(s)  # does not raise


@pytest.mark.unit
def test_json_logging_renders_json_with_request_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(_env_file=None, app_env="prod"))  # prod -> JSON renderer
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="req-123")
    get_logger("test.json").info("hello", foo="bar")
    structlog.contextvars.clear_contextvars()

    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello"
    assert payload["request_id"] == "req-123"
    assert payload["foo"] == "bar"
    assert payload["level"] == "info"


@pytest.mark.unit
def test_console_logging_does_not_error(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(_env_file=None, app_env="dev"))  # dev -> console renderer
    get_logger("test.console").info("hello", foo="bar")
    assert "hello" in capsys.readouterr().out


@pytest.mark.unit
def test_secret_never_appears_in_log(capsys: pytest.CaptureFixture[str]) -> None:
    s = Settings(_env_file=None, app_env="prod", vault_master_key="SUPERSECRETVALUE")
    configure_logging(s)
    # even if someone logs the masked secret, the plaintext must never reach stdout
    get_logger("test.secret").info("boot", vault_key=str(s.vault_master_key))
    assert "SUPERSECRETVALUE" not in capsys.readouterr().out
