from __future__ import annotations

import json
from pathlib import Path

import pytest

from flashcards import benchmark
from flashcards.client import GeminiError
from flashcards.config import Settings
from flashcards.models import Chunk, Flashcard

CARD_JSON = {
    "question": "What is tokenization?",
    "answer": "Splitting text into tokens.",
    "topic": "NLP",
    "difficulty": "easy",
}


def chunk(index: int = 0) -> Chunk:
    return Chunk(
        text="body", source_path=Path("notes/a.md"), heading="H", index=index
    )


class FakeClient:
    def __init__(self, text: str | list[str] = "", cards_error: bool = False) -> None:
        self._texts = [text] if isinstance(text, str) else list(text)
        self._cards_error = cards_error
        self.request_count = 0
        self.cache_hits = 0
        self.cache_flags: list[bool] = []

    def generate_cards(self, prompt: str, use_cache: bool = True) -> list[Flashcard]:
        self.cache_flags.append(use_cache)
        self.request_count += 1
        if self._cards_error:
            raise GeminiError("finish_reason=MAX_TOKENS")
        return [Flashcard(**CARD_JSON)]

    def generate_text(self, prompt: str) -> str:
        self.request_count += 1
        return self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]


# --- parsing the unconstrained reply ---------------------------------------


def test_parses_a_plain_json_array() -> None:
    assert benchmark.parse_cards(json.dumps([CARD_JSON])) == [Flashcard(**CARD_JSON)]


def test_parses_through_a_markdown_fence() -> None:
    fenced = f"```json\n{json.dumps([CARD_JSON])}\n```"
    assert len(benchmark.parse_cards(fenced)) == 1


def test_bare_fence_without_language_also_parses() -> None:
    assert len(benchmark.parse_cards(f"```\n{json.dumps([CARD_JSON])}\n```")) == 1


def test_malformed_json_raises() -> None:
    with pytest.raises(ValueError):
        benchmark.parse_cards("{not json")


def test_a_json_object_is_not_an_array() -> None:
    with pytest.raises(ValueError, match="expected a JSON array"):
        benchmark.parse_cards(json.dumps(CARD_JSON))


def test_a_bad_difficulty_fails_validation() -> None:
    bad = dict(CARD_JSON, difficulty="trivial")
    with pytest.raises(Exception):
        benchmark.parse_cards(json.dumps([bad]))


# --- arm accounting --------------------------------------------------------


def test_both_arms_run_every_chunk(settings: Settings) -> None:
    client = FakeClient(text=json.dumps([CARD_JSON]))
    arms = benchmark.run([chunk(0), chunk(1)], settings, client)
    assert [arm.runs for arm in arms] == [2, 2]
    assert client.request_count == 4


def test_schema_arm_always_bypasses_the_cache(settings: Settings) -> None:
    # A cached reply would report near-zero latency and no failures.
    client = FakeClient(text=json.dumps([CARD_JSON]))
    benchmark.run([chunk(0)], settings, client)
    assert client.cache_flags == [False]


def test_prompt_arm_failures_are_counted(settings: Settings) -> None:
    client = FakeClient(text="sorry, here are your cards!")
    _, prompted = benchmark.run([chunk(0), chunk(1)], settings, client)
    assert len(prompted.failures) == 2
    assert prompted.failure_rate == 1.0
    assert prompted.mean_latency == 0.0


def test_schema_arm_failures_are_counted(settings: Settings) -> None:
    client = FakeClient(text=json.dumps([CARD_JSON]), cards_error=True)
    schema, _ = benchmark.run([chunk(0)], settings, client)
    assert len(schema.failures) == 1
    assert "MAX_TOKENS" in schema.failures[0]


def test_mixed_success_and_failure_rate(settings: Settings) -> None:
    client = FakeClient(text=[json.dumps([CARD_JSON]), "garbage", "garbage"])
    _, prompted = benchmark.run([chunk(0), chunk(1)], settings, client)
    assert prompted.runs == 2
    assert prompted.failure_rate == pytest.approx(0.5)


def test_repeats_multiply_the_runs(settings: Settings) -> None:
    client = FakeClient(text=json.dumps([CARD_JSON]))
    arms = benchmark.run([chunk(0)], settings, client, repeats=3)
    assert [arm.runs for arm in arms] == [3, 3]


def test_cards_are_tallied(settings: Settings) -> None:
    client = FakeClient(text=json.dumps([CARD_JSON, CARD_JSON]))
    schema, prompted = benchmark.run([chunk(0)], settings, client)
    assert schema.cards == 1
    assert prompted.cards == 2


def test_empty_arm_reports_zero_not_a_crash() -> None:
    arm = benchmark.ArmResult(name="x")
    assert arm.runs == 0
    assert arm.failure_rate == 0.0
    assert arm.mean_latency == 0.0
