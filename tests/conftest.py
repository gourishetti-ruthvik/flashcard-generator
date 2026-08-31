from __future__ import annotations

import sys
from pathlib import Path

import pytest

from flashcards.config import Settings, load_settings

# app.py sits at the repo root rather than inside the package, because Hugging
# Face Spaces expects to find it there.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def _isolate_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cleared so a developer's real shell credentials can never leak into a test
    # run, and so no test can accidentally make a live API call.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / ".env"
    path.write_text("GEMINI_API_KEY=test-key-not-real\n", encoding="utf-8")
    return path


@pytest.fixture
def settings(env_file: Path, tmp_path: Path) -> Settings:
    # cache_dir points into tmp_path so tests never read or write the real
    # .llm_cache, which would make them order-dependent.
    return load_settings(env_file, cache_dir=tmp_path / "cache")
