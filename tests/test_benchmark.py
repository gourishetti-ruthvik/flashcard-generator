from __future__ import annotations

import json
from pathlib import Path

import pytest

from google.genai import errors

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
        # The benchmark reads this instead of timing the outer call, which would
        # include rate-limiter and backoff sleeps.
        self.last_call_seconds = 0.25

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


def test_fenced_replies_are_detected() -> None:
    from flashcards.benchmark import was_fenced

    assert was_fenced('```json\n[{"a": 1}]\n```')
    assert was_fenced('```\n[{"a": 1}]\n```')
    assert not was_fenced('[{"a": 1}]')


def test_fenced_json_still_parses() -> None:
    from flashcards.benchmark import parse_cards

    cards = parse_cards(
        '```json\n[{"question": "Q?", "answer": "An answer here.", '
        '"topic": "T", "difficulty": "easy"}]\n```'
    )
    assert len(cards) == 1 and cards[0].question == "Q?"


def test_latency_excludes_throttling(settings: Settings) -> None:
    """The arm records the client's own call time, not the wrapper's wall time.

    Timing generate_cards would fold in the rate limiter's sleep, which is how
    a 3.2s call came out as 8.8s once the bucket was empty.
    """
    client = FakeClient(text=json.dumps([CARD_JSON]))
    client.last_call_seconds = 0.4
    for arm in benchmark.run([chunk(0)], settings, client):
        assert arm.latencies == [0.4]


# --- surviving an interrupted run ------------------------------------------


class QuotaClient(FakeClient):
    """Fails every call the way an exhausted free tier does."""

    def __init__(self, fail_after: int = 0) -> None:
        super().__init__(text=json.dumps([CARD_JSON]))
        self._fail_after = fail_after

    def _maybe_fail(self) -> None:
        self.request_count += 1
        if self.request_count > self._fail_after:
            raise errors.APIError(
                429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}
            )

    def generate_cards(self, prompt: str, use_cache: bool = True) -> list[Flashcard]:
        self._maybe_fail()
        return [Flashcard(**CARD_JSON)]

    def generate_text(self, prompt: str) -> str:
        self._maybe_fail()
        return json.dumps([CARD_JSON])


def test_every_call_is_written_as_it_happens(
    settings: Settings, tmp_path: Path
) -> None:
    out = tmp_path / "r.jsonl"
    client = FakeClient(text=json.dumps([CARD_JSON]))
    benchmark.run([chunk(0)], settings, client, results_path=out)

    records = benchmark.load_records(out)
    assert [r["arm"] for r in records] == ["schema", "prompt"]
    assert all(r["ok"] and r["chunk"] == "a.md#0" for r in records)


def test_results_survive_an_unexpected_crash(
    settings: Settings, tmp_path: Path
) -> None:
    """The whole point of the file: an hour of quota must not vanish.

    The previous version accumulated in memory and returned only at the end,
    so a killed run produced nothing at all.
    """
    out = tmp_path / "r.jsonl"

    class Exploding(FakeClient):
        def generate_text(self, prompt: str) -> str:
            raise RuntimeError("process killed")

    with pytest.raises(RuntimeError):
        benchmark.run([chunk(0)], settings, Exploding(), results_path=out)

    # The schema arm ran before the crash, and its result is on disk.
    assert [r["arm"] for r in benchmark.load_records(out)] == ["schema"]


def test_resume_skips_calls_already_recorded(
    settings: Settings, tmp_path: Path
) -> None:
    out = tmp_path / "r.jsonl"
    first = FakeClient(text=json.dumps([CARD_JSON]))
    benchmark.run([chunk(0), chunk(1)], settings, first, results_path=out)
    assert first.request_count == 4

    second = FakeClient(text=json.dumps([CARD_JSON]))
    arms = benchmark.run([chunk(0), chunk(1)], settings, second, results_path=out)
    assert second.request_count == 0  # nothing left to do
    assert [arm.runs for arm in arms] == [2, 2]  # still reports the earlier run


def test_resume_only_runs_what_is_missing(settings: Settings, tmp_path: Path) -> None:
    out = tmp_path / "r.jsonl"
    stopped = QuotaClient(fail_after=1)
    benchmark.run([chunk(0)], settings, stopped, results_path=out, quota_stop=1)

    assert [r["arm"] for r in benchmark.load_records(out)] == ["schema"]

    resumed = FakeClient(text=json.dumps([CARD_JSON]))
    arms = benchmark.run([chunk(0)], settings, resumed, results_path=out)
    assert resumed.request_count == 1  # only the prompt arm was outstanding
    assert [arm.runs for arm in arms] == [1, 1]


def test_a_torn_final_line_is_ignored(tmp_path: Path) -> None:
    out = tmp_path / "r.jsonl"
    out.write_text(
        '{"arm": "schema", "chunk": "a.md#0", "repeat": 0, "ok": true}\n{"arm": "pro',
        encoding="utf-8",
    )
    assert len(benchmark.load_records(out)) == 1


def test_consecutive_quota_errors_stop_the_run(
    settings: Settings, tmp_path: Path
) -> None:
    """Without this, 30 calls x 4 attempts x 65s backoff burns an hour."""
    client = QuotaClient()
    seen: list[dict] = []
    benchmark.run(
        [chunk(i) for i in range(10)],
        settings,
        client,
        results_path=tmp_path / "r.jsonl",
        progress=seen.append,
        quota_stop=3,
    )
    assert client.request_count == 3
    assert seen[-1] == {"event": "stopped", "after": 3}


def test_quota_errors_stay_out_of_the_failure_rate(settings: Settings) -> None:
    schema, _ = benchmark.run([chunk(0)], settings, QuotaClient(), quota_stop=99)
    assert schema.failures == []
    assert schema.failure_rate == 0.0
    assert len(schema.api_errors) == 1


def test_a_success_resets_the_quota_counter(settings: Settings) -> None:
    # Alternating errors must not accumulate into a false "quota exhausted".
    client = QuotaClient(fail_after=1)
    client._fail_after = 1
    arms = benchmark.run([chunk(0)], settings, client, quota_stop=2)
    assert arms[0].runs == 1


def test_progress_reports_each_call(settings: Settings) -> None:
    seen: list[dict] = []
    benchmark.run(
        [chunk(0)],
        settings,
        FakeClient(text=json.dumps([CARD_JSON])),
        progress=seen.append,
    )
    assert [r["arm"] for r in seen] == ["schema", "prompt"]


def test_running_without_a_results_path_writes_nothing(
    settings: Settings, tmp_path: Path
) -> None:
    benchmark.run([chunk(0)], settings, FakeClient(text=json.dumps([CARD_JSON])))
    assert list(tmp_path.glob('*.jsonl')) == []


def test_summarise_rebuilds_arms_from_a_file(tmp_path: Path) -> None:
    """The table can be produced from disk alone, even after a crash."""
    records = [
        {"arm": "schema", "chunk": "a.md#0", "repeat": 0, "ok": True,
         "latency": 2.0, "cards": 5},
        {"arm": "prompt", "chunk": "a.md#0", "repeat": 0, "ok": False,
         "kind": "parse", "detail": "bad json", "fenced": True},
    ]
    schema, prompted = benchmark.summarise(records)
    assert schema.mean_latency == 2.0 and schema.cards == 5
    assert prompted.failure_rate == 1.0 and prompted.fenced == 1


def test_quota_errors_are_never_persisted(settings: Settings, tmp_path: Path) -> None:
    """Otherwise a resumed run skips the exact calls it exists to retry."""
    out = tmp_path / "r.jsonl"
    benchmark.run([chunk(0)], settings, QuotaClient(), results_path=out, quota_stop=99)
    assert benchmark.load_records(out) == []


# --- fairness of the call order --------------------------------------------


def test_arms_are_interleaved_not_batched() -> None:
    """Batching one arm ahead of the other biases the sample under a quota cap."""
    order = [arm for arm, _, _ in benchmark.planned_calls([chunk(0), chunk(1)], 1)]
    assert order == ["schema", "prompt", "schema", "prompt"]


def test_the_leading_arm_alternates_between_repeats() -> None:
    # Even interleaved, always calling schema first would hand it the last free
    # slot every time quota runs out mid-pair.
    order = [arm for arm, _, _ in benchmark.planned_calls([chunk(0)], 2)]
    assert order == ["schema", "prompt", "prompt", "schema"]


def test_a_quota_cap_now_hits_both_arms_evenly(settings: Settings) -> None:
    client = QuotaClient(fail_after=2)
    schema, prompted = benchmark.run(
        [chunk(0), chunk(1)], settings, client, quota_stop=99
    )
    assert schema.runs == 1 and prompted.runs == 1
