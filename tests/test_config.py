from pathlib import Path

import pytest

from ebay_tracker.config import ConfigError, load_settings, read_env_file


def test_read_env_file_parses_quotes_and_comments(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nEBAY_CLIENT_ID = 'abc'\nEBAY_CLIENT_SECRET=\"x=y\"\nnot a pair\n"
    )

    assert read_env_file(env_file) == {
        "EBAY_CLIENT_ID": "abc",
        "EBAY_CLIENT_SECRET": "x=y",
    }


def test_environment_variables_override_env_file(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("EBAY_CLIENT_ID=from-file\nEBAY_CLIENT_SECRET=file-secret\n")

    settings = load_settings(env={"EBAY_CLIENT_ID": "from-env"}, env_file=env_file)

    assert settings.client_id == "from-env"
    assert settings.client_secret == "file-secret"


def test_defaults_without_any_configuration(tmp_path: Path):
    settings = load_settings(env={}, env_file=tmp_path / "missing.env")

    assert settings.environment == "production"
    assert settings.api_base_url == "https://api.ebay.com"
    assert settings.marketplace == "EBAY_US"
    assert settings.webhook_url is None
    with pytest.raises(ConfigError):
        settings.require_credentials()


def test_sandbox_uses_sandbox_base_url(tmp_path: Path):
    settings = load_settings(
        env={"EBAY_ENVIRONMENT": "Sandbox"}, env_file=tmp_path / "missing.env"
    )

    assert settings.api_base_url == "https://api.sandbox.ebay.com"


def test_invalid_environment_is_rejected(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_settings(
            env={"EBAY_ENVIRONMENT": "staging"}, env_file=tmp_path / "missing.env"
        )
