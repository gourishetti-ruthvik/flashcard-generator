from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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


# --- the daily ration ------------------------------------------------------

# Counted here rather than in a front end because every call already routes
# through this wrapper: the CLI, the benchmark and the website all draw on the
# same 20, and a counter living in one of them would under-report the others.
# The window rolls over at midnight US Pacific, not local midnight -- probed
# once a minute for four minutes at the cap and it never reopened early.
PACIFIC = ZoneInfo("America/Los_Angeles")
DAILY_CAP = 20


def quota_day() -> str:
    return datetime.now(PACIFIC).strftime("%Y-%m-%d")


def resets_in() -> str:
    now = datetime.now(PACIFIC)
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    minutes = int((midnight - now).total_seconds()) // 60
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m" if hours else f"{mins}m"


def usage_file(settings: Settings) -> Path:
    return settings.cache_dir / "daily-usage.json"


def spent_today(settings: Settings) -> int:
    """Requests already spent in the current Pacific day.

    A missing or corrupt file reads as zero rather than raising: the count is
    an aid, and refusing to run because a counter is unparsable would be worse
    than briefly under-reporting it.
    """
    try:
        data = json.loads(usage_file(settings).read_text(encoding="utf-8"))
        return int(data.get(quota_day(), 0))
    except (OSError, ValueError, TypeError):
        return 0


def record_spend(settings: Settings, count: int = 1) -> int:
    if count <= 0:
        return spent_today(settings)
    total = spent_today(settings) + count
    path = usage_file(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Only today's key is kept; yesterday's count answers no question worth
        # the file growing forever.
        path.write_text(json.dumps({quota_day(): total}), encoding="utf-8")
    except OSError:
        pass
    return total


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


def is_daily_cap(exc: errors.APIError) -> bool:
    """Is this the per-day quota rather than the per-minute one?

    Worth telling apart because retrying is only ever useful for the minute
    window. The daily cap does not reopen until it resets, and its RetryInfo is
    not merely unhelpful but actively misleading: measured across four minutes
    it returned 52s, 6s, 19s, 33s, 46s and finally 0s while still refusing every
    call. Sleeping on that and retrying spends another of the 20 requests a day
    to learn what the first one already said.
    """
    details = getattr(exc, "details", None)
    if not isinstance(details, dict):
        return False
    for item in details.get("error", {}).get("details", []):
        if not isinstance(item, dict):
            continue
        for violation in item.get("violations", []):
            if "PerDay" in str(violation.get("quotaId", "")):
                return True
    return False


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
        self._last_call_seconds = 0.0

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    @property
    def last_call_seconds(self) -> float:
        """Wall time of the last HTTP call alone.

        Timed here rather than around generate_cards, which also blocks on
        the rate limiter and on retry backoff. Measuring the outer call made
        the benchmark report throttling as model latency.
        """
        return self._last_call_seconds

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
            started = time.perf_counter()
            try:
                response = self._client.models.generate_content(
                    model=self._settings.model_id,
                    contents=prompt,
                    config=config,
                )
                self._last_call_seconds = time.perf_counter() - started
                record_spend(self._settings)
                return response
            except errors.APIError as exc:
                # A 429 is the quota refusing the request, so it consumes
                # nothing. Anything else reached the server and did.
                if exc.code != 429:
                    record_spend(self._settings)
                if (
                    exc.code not in RETRY_CODES
                    or attempt == self._settings.max_attempts - 1
                    or is_daily_cap(exc)
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
