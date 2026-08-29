from __future__ import annotations

from google import genai
from google.genai import types

from flashcards.config import Settings
from flashcards.models import Flashcard


class GeminiError(RuntimeError):
    """Raised when the model returns no usable cards."""


def _finish_reason(response: types.GenerateContentResponse) -> str:
    candidates = response.candidates or []
    if not candidates:
        return "no-candidates"
    return str(candidates[0].finish_reason)


class GeminiClient:
    """The only object in this project that talks to the Gemini API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # The key is passed explicitly because the SDK prefers an ambient
        # GOOGLE_API_KEY over GEMINI_API_KEY when it resolves credentials
        # itself, and the one set on this machine is invalid.
        self._client = genai.Client(api_key=settings.api_key.get_secret_value())
        self._request_count = 0

    @property
    def request_count(self) -> int:
        return self._request_count

    def _generation_config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[Flashcard],
            temperature=self._settings.temperature,
            thinking_config=types.ThinkingConfig(
                thinking_budget=self._settings.thinking_budget
            ),
        )

    def generate_cards(self, prompt: str) -> list[Flashcard]:
        self._request_count += 1
        response = self._client.models.generate_content(
            model=self._settings.model_id,
            contents=prompt,
            config=self._generation_config(),
        )

        # In JSON mode the schema is enforced server-side, so malformed JSON is
        # not the failure to guard against. What actually happens is a reply
        # truncated at MAX_TOKENS or dropped by a safety filter, both of which
        # leave `parsed` empty. The finish reason is what makes those two
        # distinguishable to the caller.
        cards = response.parsed
        if not cards:
            raise GeminiError(
                f"Model returned no usable cards (finish_reason={_finish_reason(response)})"
            )
        return list(cards)
