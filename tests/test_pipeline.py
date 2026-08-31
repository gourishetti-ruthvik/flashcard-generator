from __future__ import annotations

from pathlib import Path

import pytest

from flashcards import pipeline
from flashcards.client import GeminiError
from flashcards.config import Settings
from flashcards.models import Flashcard


class FakeClient:
    """Stands in for GeminiClient; the pipeline only needs these three members."""

    def __init__(self, cards: list[Flashcard] | None = None, fail: bool = False) -> None:
        self._cards = cards if cards is not None else [_card("Q?")]
        self._fail = fail
        self.prompts: list[str] = []
        self.request_count = 0
        self.cache_hits = 0

    def generate_cards(self, prompt: str) -> list[Flashcard]:
        self.prompts.append(prompt)
        self.request_count += 1
        if self._fail:
            raise GeminiError("finish_reason=MAX_TOKENS")
        return list(self._cards)


def _card(question: str, answer: str = "A sufficiently long answer.") -> Flashcard:
    return Flashcard(question=question, answer=answer, topic="T", difficulty="easy")


@pytest.fixture
def notes(tmp_path: Path) -> Path:
    directory = tmp_path / "notes"
    directory.mkdir()
    (directory / "a.md").write_text("# Alpha\n\nAlpha body text.", encoding="utf-8")
    (directory / "b.md").write_text("# Beta\n\nBeta body text.", encoding="utf-8")
    return directory


def test_one_request_per_chunk(notes: Path, settings: Settings) -> None:
    client = FakeClient()
    result = pipeline.run(pipeline.collect_chunks(notes, settings), settings, client)
    assert len(result.chunks) == 2
    assert client.request_count == 2


def test_chunks_carry_their_source_file(notes: Path, settings: Settings) -> None:
    result = pipeline.run(pipeline.collect_chunks(notes, settings), settings, FakeClient())
    assert sorted(c.source_path.name for c in result.chunks) == ["a.md", "b.md"]
    assert sorted(c.heading for c in result.chunks) == ["Alpha", "Beta"]


def test_limit_caps_the_number_of_chunks(notes: Path, settings: Settings) -> None:
    client = FakeClient()
    result = pipeline.run(pipeline.collect_chunks(notes, settings), settings, client, limit=1)
    assert len(result.chunks) == 1
    assert client.request_count == 1


def test_unusable_cards_are_counted_not_emitted(
    notes: Path, settings: Settings
) -> None:
    client = FakeClient(
        cards=[_card("What is X?"), _card("According to the text, what is X?")]
    )
    result = pipeline.run(pipeline.collect_chunks(notes, settings), settings, client)
    assert len(result.cards) == 2  # one kept per chunk
    assert result.dropped == 2


def test_a_failing_chunk_does_not_abort_the_run(
    notes: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    calls = {"n": 0}
    original = client.generate_cards

    def fail_first(prompt: str) -> list[Flashcard]:
        calls["n"] += 1
        if calls["n"] == 1:
            client.request_count += 1
            raise GeminiError("finish_reason=SAFETY")
        return original(prompt)

    monkeypatch.setattr(client, "generate_cards", fail_first)
    result = pipeline.run(pipeline.collect_chunks(notes, settings), settings, client)

    assert len(result.failures) == 1
    assert "SAFETY" in result.failures[0]
    assert len(result.cards) == 1  # the surviving chunk still produced a card


def test_prompt_carries_the_chunk_text(notes: Path, settings: Settings) -> None:
    client = FakeClient()
    pipeline.run(pipeline.collect_chunks(notes, settings), settings, client)
    assert any("Alpha body text." in prompt for prompt in client.prompts)


def test_counters_come_from_the_client(notes: Path, settings: Settings) -> None:
    client = FakeClient()
    client.cache_hits = 7
    result = pipeline.run(pipeline.collect_chunks(notes, settings), settings, client)
    assert result.requests == client.request_count
    assert result.cache_hits == 7


def test_source_may_be_a_single_file(notes: Path, settings: Settings) -> None:
    result = pipeline.run(pipeline.collect_chunks(notes / "a.md", settings), settings, FakeClient())
    assert len(result.chunks) == 1


def test_chunks_from_text_splits_on_headings(settings: Settings) -> None:
    chunks = pipeline.chunks_from_text(
        "# One\n\nAlpha body.\n\n# Two\n\nBeta body.", settings
    )
    assert [c.heading for c in chunks] == ["One", "Two"]


def test_chunks_from_text_strips_markdown(settings: Settings) -> None:
    chunks = pipeline.chunks_from_text("# H\n\n**bold** and `code`", settings)
    assert chunks[0].text == "bold and code"


def test_chunks_from_text_names_the_source(settings: Settings) -> None:
    # The stem feeds the exporter's source tag, so pasted input still gets one.
    default = pipeline.chunks_from_text("# H\n\nbody", settings)
    named = pipeline.chunks_from_text("# H\n\nbody", settings, name="lecture7")
    assert default[0].source_path.stem == "pasted"
    assert named[0].source_path.stem == "lecture7"


def test_chunks_from_text_on_empty_input(settings: Settings) -> None:
    assert pipeline.chunks_from_text("", settings) == []
    assert pipeline.chunks_from_text("   \n\n  ", settings) == []
