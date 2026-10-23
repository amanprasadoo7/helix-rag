import pytest
from pydantic import ValidationError

from helix.config import Settings


def settings_without_env_file(**overrides: str) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_defaults() -> None:
    settings = settings_without_env_file()

    assert settings.app_env == "local"
    assert settings.log_level == "INFO"
    assert settings.api_port == 8000


def test_invalid_app_env_is_rejected_at_startup() -> None:
    with pytest.raises(ValidationError):
        settings_without_env_file(app_env="not-an-env")


def test_invalid_log_level_is_rejected_at_startup() -> None:
    with pytest.raises(ValidationError):
        settings_without_env_file(log_level="LOUD")


def test_environment_variable_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HELIX_API_PORT", "8010")

    settings = Settings(_env_file=None)

    assert settings.api_port == 8010


def test_postgres_dsn_is_built_from_parts() -> None:
    settings = settings_without_env_file()

    assert settings.postgres_dsn == "postgresql://helix:helix_dev_password@127.0.0.1:5432/helix"


def test_service_urls_are_built_from_parts() -> None:
    settings = settings_without_env_file()

    assert settings.redis_url == "redis://127.0.0.1:6379/0"
    assert settings.qdrant_url == "http://127.0.0.1:6333"
    assert settings.minio_endpoint == "http://127.0.0.1:9100"


def test_passwords_are_masked_in_repr() -> None:
    settings = settings_without_env_file()

    text = repr(settings)

    assert "helix_dev_password" not in text
    assert "helix_minio_dev_password" not in text
