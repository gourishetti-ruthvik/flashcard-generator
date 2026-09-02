from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors

from flashcards import client
from flashcards.client import (
    MAX_RETRY_SLEEP,
    GeminiClient,
    GeminiError,
    TokenBucket,
    is_daily_cap,
    retry_delay,
)
from flashcards.config import Settings, load_settings
from flashcards.models import Flashcard

CARD = Flashcard(
    question="What is tokenization?",
    answer="Splitting text into smaller units called tokens.",
    topic="Natural Language Processing",
    difficulty="easy",
)


def reply(cards: Any, finish_reason: str = "STOP") -> SimpleNamespace:
    return SimpleNamespace(
        parsed=cards,
        candidates=[SimpleNamespace(finish_reason=finish_reason)],
    )


class FakeModels:
    """Replays a script; the last entry repeats once the script runs out."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Collapse jitter to zero so retry tests never actually wait."""
    drawn: list[float] = []

    def fake_uniform(low: float, high: float) -> float:
        drawn.append(high)
        return 0.0

    monkeypatch.setattr("flashcards.client.random.uniform", fake_uniform)
    return drawn


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch):
    def install(script: list[Any]) -> dict[str, Any]:
        models = FakeModels(script)
        captured: dict[str, Any] = {"models": models, "kwargs": None}

        def fake_client(**kwargs: Any) -> Any:
            captured["kwargs"] = kwargs
            return SimpleNamespace(models=models)

        monkeypatch.setattr("flashcards.client.genai.Client", fake_client)
        return captured

    return install


def rate_limited(retry_after: str | None = None) -> errors.ClientError:
    error: dict[str, object] = {"message": "quota"}
    if retry_after is not None:
        error["details"] = [
            {
                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                "retryDelay": retry_after,
            }
        ]
    return errors.ClientError(429, {"error": error})


def overloaded() -> errors.ServerError:
    return errors.ServerError(503, {"error": {"message": "overloaded"}})


# --- basic call ------------------------------------------------------------


def test_returns_parsed_cards(settings: Settings, fake_api) -> None:
    fake_api([reply([CARD])])
    assert GeminiClient(settings).generate_cards("prompt") == [CARD]


def test_sends_configured_model_and_json_mode(settings: Settings, fake_api) -> None:
    captured = fake_api([reply([CARD])])
    GeminiClient(settings).generate_cards("prompt")
    call = captured["models"].calls[0]
    assert call["model"] == settings.model_id
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema == list[Flashcard]


def test_api_key_is_passed_explicitly(settings: Settings, fake_api) -> None:
    # Regression guard: dropping this lets the SDK fall back to an ambient
    # GOOGLE_API_KEY, which on this machine is invalid.
    captured = fake_api([reply([CARD])])
    GeminiClient(settings)
    assert captured["kwargs"] == {"api_key": settings.api_key.get_secret_value()}


@pytest.mark.parametrize("parsed", [None, []])
def test_empty_parsed_raises_with_finish_reason(
    settings: Settings, fake_api, parsed: Any
) -> None:
    fake_api([reply(parsed, finish_reason="MAX_TOKENS")])
    with pytest.raises(GeminiError, match="MAX_TOKENS"):
        GeminiClient(settings).generate_cards("prompt")


def test_missing_candidates_still_reports_a_reason(
    settings: Settings, fake_api
) -> None:
    fake_api([SimpleNamespace(parsed=None, candidates=[])])
    with pytest.raises(GeminiError, match="no-candidates"):
        GeminiClient(settings).generate_cards("prompt")


def test_failed_call_still_counts_against_quota(settings: Settings, fake_api) -> None:
    fake_api([reply([], finish_reason="SAFETY")])
    client = GeminiClient(settings)
    with pytest.raises(GeminiError):
        client.generate_cards("prompt")
    assert client.request_count == 1


# --- disk cache ------------------------------------------------------------


def test_second_identical_call_is_served_from_cache(
    settings: Settings, fake_api
) -> None:
    captured = fake_api([reply([CARD])])
    client = GeminiClient(settings)
    first = client.generate_cards("prompt")
    second = client.generate_cards("prompt")

    assert first == second
    assert len(captured["models"].calls) == 1
    assert client.request_count == 1
    assert client.cache_hits == 1


def test_cache_survives_a_new_client(settings: Settings, fake_api) -> None:
    captured = fake_api([reply([CARD])])
    GeminiClient(settings).generate_cards("prompt")
    GeminiClient(settings).generate_cards("prompt")
    assert len(captured["models"].calls) == 1


def test_cache_key_includes_the_model(
    settings: Settings, env_file, tmp_path, fake_api
) -> None:
    # Same prompt, different model, must not replay the other model's answers.
    captured = fake_api([reply([CARD])])
    GeminiClient(settings).generate_cards("prompt")

    other = load_settings(
        env_file, cache_dir=settings.cache_dir, model_id="gemini-2.5-flash-lite"
    )
    GeminiClient(other).generate_cards("prompt")
    assert len(captured["models"].calls) == 2


def test_use_cache_false_bypasses_the_cache(settings: Settings, fake_api) -> None:
    # The benchmark needs this: reusing a cached reply would report near-zero
    # latency and no parse failures for whichever arm ran second.
    captured = fake_api([reply([CARD])])
    client = GeminiClient(settings)
    client.generate_cards("prompt")
    client.generate_cards("prompt", use_cache=False)
    assert len(captured["models"].calls) == 2


def test_corrupt_cache_entry_is_treated_as_a_miss(
    settings: Settings, fake_api
) -> None:
    captured = fake_api([reply([CARD])])
    client = GeminiClient(settings)
    client.generate_cards("prompt")

    corrupted = next(settings.cache_dir.glob("*.json"))
    corrupted.write_text('[{"question": "truncated"', encoding="utf-8")

    assert client.generate_cards("prompt") == [CARD]
    assert len(captured["models"].calls) == 2


def test_cache_file_is_readable_json(settings: Settings, fake_api) -> None:
    fake_api([reply([CARD])])
    GeminiClient(settings).generate_cards("prompt")
    stored = json.loads(
        next(settings.cache_dir.glob("*.json")).read_text(encoding="utf-8")
    )
    assert stored[0]["question"] == CARD.question


# --- retry / backoff -------------------------------------------------------


@pytest.mark.parametrize("failure", [rate_limited, overloaded])
def test_transient_failure_is_retried(settings: Settings, fake_api, failure) -> None:
    fake_api([failure(), reply([CARD])])
    client = GeminiClient(settings)
    assert client.generate_cards("prompt") == [CARD]
    assert client.request_count == 2


def test_backoff_grows_between_attempts(
    settings: Settings, fake_api, _no_backoff_sleep: list[float]
) -> None:
    fake_api([rate_limited(), rate_limited(), reply([CARD])])
    GeminiClient(settings).generate_cards("prompt")
    assert _no_backoff_sleep == [1.0, 2.0]


def test_server_retry_delay_overrides_local_backoff(
    settings: Settings, fake_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The live 429 asked for 40 s while the largest local backoff is 4 s, so
    # ignoring the hint guaranteed the retry failed too.
    slept: list[float] = []
    monkeypatch.setattr("flashcards.client.time.sleep", slept.append)
    fake_api([rate_limited("40s"), reply([CARD])])
    GeminiClient(settings).generate_cards("prompt")
    assert slept == [41.0]


def test_retry_delay_is_capped(
    settings: Settings, fake_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []
    monkeypatch.setattr("flashcards.client.time.sleep", slept.append)
    fake_api([rate_limited("3600s"), reply([CARD])])
    GeminiClient(settings).generate_cards("prompt")
    assert slept == [MAX_RETRY_SLEEP]


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"error": {"details": [{"retryDelay": "12s"}]}}, 12.0),
        ({"error": {"details": [{"retryDelay": "1.5s"}]}}, 1.5),
        ({"error": {"details": [{"retryDelay": "bogus"}]}}, None),
        ({"error": {"details": [{"other": "x"}]}}, None),
        ({"error": {"message": "no details"}}, None),
        ({}, None),
    ],
)
def test_retry_delay_extraction(payload: dict, expected: float | None) -> None:
    assert retry_delay(errors.ClientError(429, payload)) == expected


def test_non_retryable_error_raises_immediately(
    settings: Settings, fake_api
) -> None:
    fake_api([errors.ClientError(400, {"error": {"message": "bad key"}})])
    client = GeminiClient(settings)
    with pytest.raises(errors.ClientError):
        client.generate_cards("prompt")
    assert client.request_count == 1


def test_retries_are_capped_by_max_attempts(settings: Settings, fake_api) -> None:
    fake_api([rate_limited()])
    client = GeminiClient(settings)
    with pytest.raises(errors.ClientError):
        client.generate_cards("prompt")
    assert client.request_count == settings.max_attempts


def test_nothing_is_cached_when_every_attempt_fails(
    settings: Settings, fake_api
) -> None:
    fake_api([rate_limited()])
    with pytest.raises(errors.ClientError):
        GeminiClient(settings).generate_cards("prompt")
    assert not settings.cache_dir.exists() or not list(
        settings.cache_dir.glob("*.json")
    )


# --- token bucket ----------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_bucket_allows_a_full_burst_without_waiting() -> None:
    clock = FakeClock()
    bucket = TokenBucket(3, monotonic=clock.monotonic, sleep=clock.sleep)
    for _ in range(3):
        bucket.acquire()
    assert clock.now == 0.0


def test_bucket_throttles_once_drained() -> None:
    clock = FakeClock()
    bucket = TokenBucket(3, monotonic=clock.monotonic, sleep=clock.sleep)
    for _ in range(4):
        bucket.acquire()
    # Three per minute means the fourth waits the full 20 s refill.
    assert clock.now == pytest.approx(20.0)


def test_bucket_refills_over_time() -> None:
    clock = FakeClock()
    bucket = TokenBucket(60, monotonic=clock.monotonic, sleep=clock.sleep)
    for _ in range(60):
        bucket.acquire()
    clock.now += 10.0
    for _ in range(10):
        bucket.acquire()
    assert clock.now == pytest.approx(10.0)


def test_cache_hit_does_not_consume_a_token(settings: Settings, fake_api) -> None:
    # A fully cached run costs no quota, so throttling it would be pure waiting.
    fake_api([reply([CARD])])
    client = GeminiClient(settings)
    client.generate_cards("prompt")
    for _ in range(settings.requests_per_minute * 3):
        client.generate_cards("prompt")
    assert client.request_count == 1

# --- telling the daily cap apart from the minute window --------------------


def _quota_error(quota_id: str, delay: str = "30s") -> errors.APIError:
    return errors.APIError(
        429,
        {
            "error": {
                "code": 429,
                "message": "You exceeded your current quota",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": quota_id, "quotaValue": "20"}],
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": delay,
                    },
                ],
            }
        },
    )


DAILY = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
PER_MINUTE = "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"


def test_daily_cap_is_recognised() -> None:
    assert is_daily_cap(_quota_error(DAILY))


def test_per_minute_quota_is_not_a_daily_cap() -> None:
    assert not is_daily_cap(_quota_error(PER_MINUTE))


def test_a_429_without_quota_details_is_not_a_daily_cap() -> None:
    assert not is_daily_cap(errors.APIError(429, {"error": {"message": "busy"}}))


def test_the_daily_cap_is_not_retried(settings: Settings, fake_api) -> None:
    """Retrying it spends another of the 20 requests a day to learn nothing.

    Its RetryInfo is misleading rather than merely unhelpful: measured live it
    reported 52s, 6s, 19s, 33s, 46s and finally 0s across four minutes while
    still refusing every call.
    """
    captured = fake_api([_quota_error(DAILY, delay="0s")])
    with pytest.raises(errors.APIError):
        GeminiClient(settings).generate_text("prompt")
    assert len(captured["models"].calls) == 1


def test_a_per_minute_quota_error_is_still_retried(
    settings: Settings, fake_api
) -> None:
    # Waiting out the minute window is exactly what backoff is for.
    captured = fake_api([_quota_error(PER_MINUTE, delay="0s")])
    with pytest.raises(errors.APIError):
        GeminiClient(settings).generate_text("prompt")
    assert len(captured["models"].calls) == settings.max_attempts


# --- the daily ration ------------------------------------------------------


def test_a_served_call_spends_one(settings: Settings, fake_api) -> None:
    fake_api([reply([CARD])])
    GeminiClient(settings).generate_cards("prompt")
    assert client.spent_today(settings) == 1


def test_a_cache_hit_spends_nothing(settings: Settings, fake_api) -> None:
    # A cached reply returns before _call_with_retry, so it never counts.
    fake_api([reply([CARD])])
    GeminiClient(settings).generate_cards("prompt")
    GeminiClient(settings).generate_cards("prompt")
    assert client.spent_today(settings) == 1


def test_a_quota_rejection_spends_nothing(settings: Settings, fake_api) -> None:
    """A 429 is the quota refusing the request; it does not consume one.

    Counting it would make the strip run ahead of reality exactly when the
    number matters most.
    """
    fake_api([_quota_error(DAILY, delay="0s")])
    with pytest.raises(errors.APIError):
        GeminiClient(settings).generate_text("prompt")
    assert client.spent_today(settings) == 0


def test_a_server_error_does_spend(settings: Settings, fake_api) -> None:
    # It reached the model and was served badly, which is not free.
    fake_api([errors.ServerError(500, {"error": {"message": "boom"}})])
    with pytest.raises(errors.APIError):
        GeminiClient(settings).generate_cards("prompt")
    assert client.spent_today(settings) == 1


def test_every_retry_spends_its_own_request(settings: Settings, fake_api) -> None:
    # Three attempts against an overloaded model cost three of the twenty,
    # which is why max_attempts is lowered for the benchmark.
    fake_api([overloaded()])
    with pytest.raises(errors.APIError):
        GeminiClient(settings.model_copy(update={"max_attempts": 3})).generate_cards("p")
    assert client.spent_today(settings) == 3


def test_the_count_is_shared_across_clients(settings: Settings, fake_api) -> None:
    # The whole point: the CLI, the benchmark and the website draw on one
    # number rather than each keeping a private tally.
    fake_api([reply([CARD])])
    GeminiClient(settings).generate_cards("first")
    GeminiClient(settings).generate_cards("second")
    assert client.spent_today(settings) == 2


def test_the_day_key_is_pacific(settings: Settings) -> None:
    # Google's cap rolls over at midnight US Pacific. Keying on the local date
    # would reset the count hours early or late.
    from datetime import datetime

    client.record_spend(settings, 2)
    stored = json.loads(client.usage_file(settings).read_text(encoding="utf-8"))
    assert list(stored) == [datetime.now(client.PACIFIC).strftime("%Y-%m-%d")]


def test_a_corrupt_counter_reads_as_zero(settings: Settings) -> None:
    client.usage_file(settings).parent.mkdir(parents=True, exist_ok=True)
    client.usage_file(settings).write_text("{not json", encoding="utf-8")
    assert client.spent_today(settings) == 0
