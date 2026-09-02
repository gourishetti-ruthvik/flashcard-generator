from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_KEY_VAR = "GEMINI_API_KEY"


class ConfigError(RuntimeError):
    """Raised when the environment cannot produce usable settings."""


class Settings(BaseModel):
    # protected_namespaces is cleared because pydantic reserves the "model_"
    # prefix and would otherwise warn about model_id on every import.
    model_config = ConfigDict(frozen=True, protected_namespaces=())

    api_key: SecretStr

    # The single source of truth for the model. Nothing downstream may hardcode it.
    model_id: str = "gemini-2.5-flash"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    # Thinking costs ~30x the latency on this workload for no measurable gain in
    # card quality, and the free tier is rate limited, so it is off by default.
    thinking_budget: int = Field(default=0, ge=0)

    cards_per_chunk: int = Field(default=5, gt=0)
    chunk_target_tokens: int = Field(default=800, gt=0)

    # Measured, not guessed: the free tier rejects the 6th call in a minute for
    # gemini-2.5-flash with "quotaValue: 5". The commonly quoted 15 RPM does not
    # apply to this model.
    requests_per_minute: int = Field(default=5, gt=0)
    max_attempts: int = Field(default=4, gt=0)
    daily_cap: int = Field(default=20, gt=0)
    # A chunk below this is folded into a neighbour rather than spending a
    # whole request. Set to 0 to disable the merge entirely.
    min_chunk_tokens: int = Field(default=100, ge=0)

    cache_dir: Path = PROJECT_ROOT / ".llm_cache"
    note_suffixes: tuple[str, ...] = (".md", ".txt")

    embedding_model: str = "all-MiniLM-L6-v2"
    similarity_threshold: float = Field(default=0.9, ge=0.0, le=1.0)


def load_settings(env_file: Path | None = None, **overrides: object) -> Settings:
    path = env_file if env_file is not None else PROJECT_ROOT / ".env"

    # override=True so the project's .env beats whatever is already exported in
    # the shell. This machine has a stale, invalid GOOGLE_API_KEY set at user
    # scope; the google-genai SDK prefers that variable over GEMINI_API_KEY when
    # it resolves credentials itself, which yields a confusing 400. We therefore
    # read the key here and always pass it to the client explicitly.
    load_dotenv(path, encoding="utf-8", override=True)

    api_key = os.environ.get(API_KEY_VAR, "").strip()
    if not api_key:
        raise ConfigError(
            f"{API_KEY_VAR} is not set. Add it to {path} as {API_KEY_VAR}=your-key"
        )

    return Settings(api_key=SecretStr(api_key), **overrides)
