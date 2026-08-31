from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors

from flashcards.client import GeminiClient, GeminiError, TokenBucket
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


def rate_limited() -> errors.ClientError:
    return errors.ClientError(429, {"error": {"message": "quota"}})


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
