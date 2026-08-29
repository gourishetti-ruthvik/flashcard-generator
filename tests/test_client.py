from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from flashcards.client import GeminiClient, GeminiError
from flashcards.config import Settings
from flashcards.models import Flashcard

CARD = Flashcard(
    question="What is tokenization?",
    answer="Splitting text into smaller units called tokens.",
    topic="Natural Language Processing",
    difficulty="easy",
)


class _StubModels:
    def __init__(self, parsed: Any, finish_reason: str) -> None:
        self._parsed = parsed
        self._finish_reason = finish_reason
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        return SimpleNamespace(
            parsed=self._parsed,
            candidates=[SimpleNamespace(finish_reason=self._finish_reason)],
        )


@pytest.fixture
def install_stub(monkeypatch: pytest.MonkeyPatch):
    """Replace the SDK client so no test can reach the network."""

    def install(parsed: Any, finish_reason: str = "STOP") -> dict[str, Any]:
        stub = SimpleNamespace(models=_StubModels(parsed, finish_reason))
        captured: dict[str, Any] = {"stub": stub, "kwargs": None}

        def fake_client(**kwargs: Any) -> Any:
            captured["kwargs"] = kwargs
            return stub

        monkeypatch.setattr("flashcards.client.genai.Client", fake_client)
        return captured

    return install


def test_returns_parsed_cards(settings: Settings, install_stub) -> None:
    install_stub([CARD])
    cards = GeminiClient(settings).generate_cards("prompt")
    assert cards == [CARD]


def test_request_count_tracks_calls(settings: Settings, install_stub) -> None:
    install_stub([CARD])
    client = GeminiClient(settings)
    assert client.request_count == 0
    client.generate_cards("prompt")
    client.generate_cards("prompt")
    assert client.request_count == 2


def test_sends_the_configured_model_id(settings: Settings, install_stub) -> None:
    captured = install_stub([CARD])
    GeminiClient(settings).generate_cards("prompt")
    assert captured["stub"].models.calls[0]["model"] == settings.model_id


def test_api_key_is_passed_explicitly(settings: Settings, install_stub) -> None:
    # Regression guard: if the key is ever dropped here the SDK falls back to an
    # ambient GOOGLE_API_KEY, which on this machine is invalid.
    captured = install_stub([CARD])
    GeminiClient(settings)
    assert captured["kwargs"] == {"api_key": settings.api_key.get_secret_value()}


def test_requests_json_mode(settings: Settings, install_stub) -> None:
    captured = install_stub([CARD])
    GeminiClient(settings).generate_cards("prompt")
    config = captured["stub"].models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema == list[Flashcard]


@pytest.mark.parametrize("parsed", [None, []])
def test_empty_parsed_raises_gemini_error(
    settings: Settings, install_stub, parsed: Any
) -> None:
    install_stub(parsed, finish_reason="MAX_TOKENS")
    with pytest.raises(GeminiError, match="MAX_TOKENS"):
        GeminiClient(settings).generate_cards("prompt")


def test_missing_candidates_still_reports_a_reason(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **_: SimpleNamespace(parsed=None, candidates=[])
        )
    )
    monkeypatch.setattr("flashcards.client.genai.Client", lambda **_: stub)
    with pytest.raises(GeminiError, match="no-candidates"):
        GeminiClient(settings).generate_cards("prompt")


def test_failed_call_still_counts_against_quota(
    settings: Settings, install_stub
) -> None:
    # The request reached the API, so it consumed quota even though it produced
    # nothing usable. The counter has to reflect that.
    install_stub([], finish_reason="SAFETY")
    client = GeminiClient(settings)
    with pytest.raises(GeminiError):
        client.generate_cards("prompt")
    assert client.request_count == 1
