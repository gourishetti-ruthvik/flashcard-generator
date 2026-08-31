from __future__ import annotations

import csv
from pathlib import Path

import pytest
from google.genai import errors

import app
from flashcards.config import ConfigError, Settings
from flashcards.models import Flashcard

NOTES = "# Tokenization\n\nTokenization splits text into smaller units."


def _card(question: str = "What is tokenization?") -> Flashcard:
    return Flashcard(
        question=question,
        answer="Splitting text into smaller units called tokens.",
        topic="Natural Language Processing",
        difficulty="easy",
    )


class FakeClient:
    def __init__(self, cards: list[Flashcard] | None = None) -> None:
        self._cards = cards if cards is not None else [_card()]
        self.request_count = 0
        self.cache_hits = 0

    def generate_cards(self, prompt: str) -> list[Flashcard]:
        self.request_count += 1
        return list(self._cards)


@pytest.fixture(autouse=True)
def _wire_app(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "GeminiClient", lambda _: FakeClient())


# --- input gathering -------------------------------------------------------


def test_pasted_text_becomes_chunks(settings: Settings) -> None:
    chunks = app.gather_chunks(NOTES, None, settings)
    assert len(chunks) == 1
    assert chunks[0].heading == "Tokenization"
    assert chunks[0].source_path.stem == "pasted"


def test_uploaded_files_are_read(tmp_path: Path, settings: Settings) -> None:
    note = tmp_path / "embeddings.md"
    note.write_text("# Embeddings\n\nVectors for words.", encoding="utf-8")
    chunks = app.gather_chunks("", [str(note)], settings)
    # The filename becomes the source tag, so cards stay traceable in Anki.
    assert chunks[0].source_path.stem == "embeddings"


def test_text_and_files_combine(tmp_path: Path, settings: Settings) -> None:
    note = tmp_path / "extra.md"
    note.write_text("# Extra\n\nMore body text.", encoding="utf-8")
    chunks = app.gather_chunks(NOTES, [str(note)], settings)
    assert {c.source_path.stem for c in chunks} == {"pasted", "extra"}


def test_blank_input_yields_nothing(settings: Settings) -> None:
    assert app.gather_chunks("   ", None, settings) == []


# --- preview ---------------------------------------------------------------


def test_preview_reports_chunks_and_spends_nothing() -> None:
    message = app.preview(NOTES, None, 5)
    assert "1 chunks" in message
    assert "No API calls were made" in message


def test_preview_never_builds_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(_: object) -> None:
        raise AssertionError("preview must not touch the API")

    monkeypatch.setattr(app, "GeminiClient", explode)
    assert "chunks" in app.preview(NOTES, None, 5)


def test_preview_on_empty_input_is_friendly() -> None:
    assert "Nothing to do" in app.preview("", None, 5)


# --- generate --------------------------------------------------------------


def test_generate_returns_rows_status_and_csv() -> None:
    rows, status, csv_path = app.generate(NOTES, None, 5, False)

    assert rows == [
        [
            "What is tokenization?",
            "Splitting text into smaller units called tokens.",
            "Natural Language Processing",
            "easy",
        ]
    ]
    assert "1 cards" in status
    assert Path(csv_path).exists()


def test_csv_is_importable(tmp_path: Path) -> None:
    _, _, csv_path = app.generate(NOTES, None, 5, False)
    with Path(csv_path).open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.reader(handle) if not row[0].startswith("#")]
    assert rows[0][0] == "What is tokenization?"
    assert rows[0][2] == "Natural_Language_Processing easy pasted"


def test_limit_caps_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(app, "GeminiClient", lambda _: client)
    long_notes = "\n\n".join(f"# H{n}\n\nBody number {n} here." for n in range(5))
    app.generate(long_notes, None, 2, False)
    assert client.request_count == 2


def _two_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        app, "GeminiClient", lambda _: FakeClient([_card("First?"), _card("Second?")])
    )


def test_missing_dedupe_extra_is_reported_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _two_cards(monkeypatch)

    def unavailable(*_: object, **__: object) -> None:
        raise app.dedupe.DedupeUnavailable("sentence-transformers is not installed")

    monkeypatch.setattr(app.dedupe, "deduplicate", unavailable)
    rows, status, csv_path = app.generate(NOTES, None, 5, True)

    assert len(rows) == 2  # cards survive even though dedupe could not run
    assert "Dedupe skipped" in status
    assert csv_path is not None


def test_duplicates_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    # The encoder is stubbed rather than loaded: the real one downloads weights
    # from the HF Hub, and tests must not touch the network.
    _two_cards(monkeypatch)
    monkeypatch.setattr(
        app.dedupe,
        "deduplicate",
        lambda entries, *_, **__: ([entries[0]], [entries[1]]),
    )
    rows, status, _ = app.generate(NOTES, None, 5, True)

    assert len(rows) == 1
    assert "duplicates 1" in status


def test_dedupe_short_circuits_on_a_single_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One card cannot have a duplicate, so the encoder is never loaded at all.
    def explode(*_: object, **__: object) -> None:
        raise AssertionError("dedupe should not run for a single card")

    monkeypatch.setattr(app.dedupe, "load_encoder", explode)
    _, status, _ = app.generate(NOTES, None, 5, True)
    assert "Dedupe skipped" not in status


def test_quota_error_becomes_a_readable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Exhausted(FakeClient):
        def generate_cards(self, prompt: str) -> list[Flashcard]:
            raise errors.ClientError(429, {"error": {"message": "quota"}})

    monkeypatch.setattr(app, "GeminiClient", lambda _: Exhausted())
    rows, status, csv_path = app.generate(NOTES, None, 5, False)
    assert rows == []
    assert "429" in status
    assert csv_path is None


def test_missing_secret_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def unconfigured() -> Settings:
        raise ConfigError("GEMINI_API_KEY is not set")

    monkeypatch.setattr(app, "load_settings", unconfigured)
    rows, status, csv_path = app.generate(NOTES, None, 5, False)
    assert rows == []
    assert "Not configured" in status
    assert csv_path is None


def test_generate_on_empty_input_is_friendly() -> None:
    rows, status, csv_path = app.generate("", None, 5, False)
    assert rows == []
    assert "Nothing to do" in status
    assert csv_path is None
