from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections.abc import Callable
from pathlib import Path

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from flashcards.config import Settings
from flashcards.models import Flashcard

# 429 is the quota ceiling; 503 is the overload we actually hit while probing
# gemini-3.7-flash. Both are transient and worth the same retry.
RETRY_CODES = frozenset({429, 503})


# A quota error can carry a RetryInfo saying exactly how long to wait. Ignoring
# it and using only exponential backoff guarantees failure when the server asks
# for 40 s and the largest local backoff is 4 s.
_RETRY_DELAY = re.compile(r"^(\d+(?:\.\d+)?)s$")
MAX_RETRY_SLEEP = 65.0


class GeminiError(RuntimeError):
    """Raised when the model returns no usable cards."""


def retry_delay(exc: errors.APIError) -> float | None:
    details = getattr(exc, "details", None)
    if not isinstance(details, dict):
        return None
    for item in details.get("error", {}).get("details", []):
        if not isinstance(item, dict):
            continue
        match = _RETRY_DELAY.match(str(item.get("retryDelay", "")))
        if match:
            return float(match.group(1))
    return None


def _finish_reason(response: types.GenerateContentResponse) -> str:
    candidates = response.candidates or []
    if not candidates:
        return "no-candidates"
    return str(candidates[0].finish_reason)


class TokenBucket:
    # The clock is injectable so tests can exhaust the bucket without waiting a
    # real minute; production always uses the stdlib default.
    def __init__(
        self,
        per_minute: int,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._rate = per_minute / 60.0
        self._capacity = float(per_minute)
        self._tokens = float(per_minute)
        self._monotonic = monotonic
        self._sleep = sleep
        self._updated = monotonic()

    def acquire(self) -> None:
        while True:
            now = self._monotonic()
            self._tokens = min(
                self._capacity, self._tokens + (now - self._updated) * self._rate
            )
            self._updated = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            self._sleep((1.0 - self._tokens) / self._rate)


class GeminiClient:
    """The only object in this project that talks to the Gemini API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # The key is passed explicitly because the SDK prefers an ambient
        # GOOGLE_API_KEY over GEMINI_API_KEY when it resolves credentials
        # itself, and the one set on this machine is invalid.
        self._client = genai.Client(api_key=settings.api_key.get_secret_value())
        self._bucket = TokenBucket(settings.requests_per_minute)
        self._request_count = 0
        self._cache_hits = 0

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    def _generation_config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[Flashcard],
            temperature=self._settings.temperature,
            thinking_config=types.ThinkingConfig(
                thinking_budget=self._settings.thinking_budget
            ),
        )

    def _cache_key(self, prompt: str) -> str:
        # Every knob that changes the reply goes into the key. Keyed on the
        # prompt alone, a cache would replay one model's answers for another,
        # and the Phase F benchmark would compare an arm against its own cache.
        material = json.dumps(
            {
                "model": self._settings.model_id,
                "prompt": prompt,
                "temperature": self._settings.temperature,
                "thinking_budget": self._settings.thinking_budget,
                "mime": "application/json",
                "schema": "list[Flashcard]",
            },
            sort_keys=True,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self._settings.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> list[Flashcard] | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return [Flashcard(**item) for item in raw]
        except (OSError, ValueError, TypeError, ValidationError):
            # A half-written file from an interrupted run is a miss, not a crash.
            return None

    def _write_cache(self, key: str, cards: list[Flashcard]) -> None:
        self._settings.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(key).write_text(
            json.dumps([card.model_dump() for card in cards], indent=2),
            encoding="utf-8",
        )

    def _call_with_retry(
        self, prompt: str, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        for attempt in range(self._settings.max_attempts):
            self._bucket.acquire()
            self._request_count += 1
            try:
                return self._client.models.generate_content(
                    model=self._settings.model_id,
                    contents=prompt,
                    config=config,
                )
            except errors.APIError as exc:
                if (
                    exc.code not in RETRY_CODES
                    or attempt == self._settings.max_attempts - 1
                ):
                    raise
                # Full jitter rather than a fixed backoff: when several chunks
                # hit the limit together, identical sleeps would retry in lockstep.
                backoff = random.uniform(0.0, 2.0**attempt)
                # The server knows when the quota window reopens; local backoff
                # is only a floor when it does not say.
                server_hint = retry_delay(exc)
                if server_hint is not None:
                    backoff = max(backoff, min(server_hint + 1.0, MAX_RETRY_SLEEP))
                time.sleep(backoff)
        raise AssertionError("unreachable: loop either returns or raises")

    def generate_cards(self, prompt: str, use_cache: bool = True) -> list[Flashcard]:
        key = self._cache_key(prompt)
        if use_cache:
            cached = self._read_cache(key)
            if cached is not None:
                # Deliberately before the rate limiter: a cached run consumes no
                # quota, so throttling it would be pure waiting.
                self._cache_hits += 1
                return cached

        response = self._call_with_retry(prompt, self._generation_config())

        # In JSON mode the schema is enforced server-side, so malformed JSON is
        # not the failure to guard against. What actually happens is a reply
        # truncated at MAX_TOKENS or dropped by a safety filter, both of which
        # leave `parsed` empty. The finish reason distinguishes them.
        cards = response.parsed
        if not cards:
            raise GeminiError(
                f"Model returned no usable cards (finish_reason={_finish_reason(response)})"
            )

        cards = list(cards)
        self._write_cache(key, cards)
        return cards

    def generate_text(self, prompt: str) -> str:
        """Unconstrained completion. Only the benchmark's control arm uses this.

        Deliberately uncached: it exists to measure what happens without the
        schema, and a cached reply would measure nothing.
        """
        response = self._call_with_retry(
            prompt,
            types.GenerateContentConfig(
                temperature=self._settings.temperature,
                thinking_config=types.ThinkingConfig(
                    thinking_budget=self._settings.thinking_budget
                ),
            ),
        )
        return response.text or ""
