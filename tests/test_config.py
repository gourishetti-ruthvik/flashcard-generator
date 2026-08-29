from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from flashcards.config import ConfigError, Settings, load_settings


def test_reads_key_from_env_file(env_file: Path) -> None:
    settings = load_settings(env_file)
    assert settings.api_key.get_secret_value() == "test-key-not-real"


def test_missing_key_raises_config_error(tmp_path: Path) -> None:
    empty = tmp_path / ".env"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        load_settings(empty)


def test_blank_key_raises_config_error(tmp_path: Path) -> None:
    blank = tmp_path / ".env"
    blank.write_text("GEMINI_API_KEY=   \n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(blank)


def test_env_file_beats_ambient_variable(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "ambient-should-lose")
    settings = load_settings(env_file)
    assert settings.api_key.get_secret_value() == "test-key-not-real"


def test_api_key_never_appears_in_repr(env_file: Path) -> None:
    settings = load_settings(env_file)
    assert "test-key-not-real" not in repr(settings)
    assert "test-key-not-real" not in str(settings)


def test_verified_defaults(env_file: Path) -> None:
    settings = load_settings(env_file)
    assert settings.model_id == "gemini-2.5-flash"
    assert settings.thinking_budget == 0
    assert settings.requests_per_minute == 15
    assert settings.chunk_target_tokens == 800


def test_overrides_are_applied(env_file: Path) -> None:
    settings = load_settings(env_file, requests_per_minute=5)
    assert settings.requests_per_minute == 5


def test_settings_are_frozen(env_file: Path) -> None:
    settings = load_settings(env_file)
    with pytest.raises(ValidationError):
        settings.model_id = "something-else"


def test_out_of_range_temperature_rejected(env_file: Path) -> None:
    with pytest.raises(ValidationError):
        load_settings(env_file, temperature=9.0)


def test_settings_requires_api_key() -> None:
    with pytest.raises(ValidationError):
        Settings()
