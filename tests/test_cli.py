from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from flashcards.cli import app, ration_line
from flashcards.config import Settings

runner = CliRunner()


@pytest.fixture
def notes(tmp_path: Path) -> Path:
    directory = tmp_path / "notes"
    directory.mkdir()
    (directory / "a.md").write_text("# Alpha\n\nAlpha body.", encoding="utf-8")
    (directory / "b.md").write_text("# Beta\n\nBeta body.", encoding="utf-8")
    return directory


@pytest.fixture(autouse=True)
def _use_test_settings(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    # Keeps the CLI off the real .env, so no test can pick up a live key.
    monkeypatch.setattr("flashcards.cli.load_settings", lambda: settings)


def test_dry_run_makes_no_requests(notes: Path) -> None:
    result = runner.invoke(app, ["generate", str(notes), "--dry-run"])
    assert result.exit_code == 0
    assert "chunks: 2" in result.stdout
    assert "estimated requests: 2" in result.stdout
    assert "requests made: 0" in result.stdout


def test_dry_run_never_builds_a_client(
    notes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_: object, **__: object) -> None:
        raise AssertionError("--dry-run must not touch the API")

    monkeypatch.setattr("flashcards.cli.GeminiClient", explode)
    assert runner.invoke(app, ["generate", str(notes), "--dry-run"]).exit_code == 0


def test_dry_run_respects_limit(notes: Path) -> None:
    result = runner.invoke(app, ["generate", str(notes), "--dry-run", "--limit", "1"])
    assert "chunks: 1" in result.stdout
    assert "estimated requests: 1" in result.stdout


def test_missing_source_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(app, ["generate", str(tmp_path / "nope"), "--dry-run"])
    assert result.exit_code != 0


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "flashcards" in result.stdout


def test_dry_run_reports_the_daily_ration(tmp_path: Path) -> None:
    """The cap is the binding constraint on this tier and used to be invisible
    until a run failed halfway through."""
    notes = tmp_path / "n.md"
    notes.write_text("# H\n\nSome body text here for the chunker.", encoding="utf-8")
    result = runner.invoke(app, ["generate", str(notes), "--dry-run"])
    assert result.exit_code == 0
    assert "ration:" in result.stdout and "of 20 spent today" in result.stdout


def test_the_ration_line_counts_down(settings: Settings) -> None:
    from flashcards import client as client_mod

    client_mod.record_spend(settings, 8)
    line = ration_line(settings)
    assert "8 of 20 spent today, 12 left" in line
    assert "resets in" in line
