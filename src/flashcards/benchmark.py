from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

from google.genai import errors
from pydantic import ValidationError

from flashcards.client import GeminiClient, GeminiError
from flashcards.config import Settings
from flashcards.models import Chunk, Flashcard
from flashcards.prompts import build_generation_prompt, build_json_instruction_prompt

# Unconstrained models routinely wrap JSON in a fence despite being told not to.
# Stripping it first is what any real implementation would do, so leaving it in
# would inflate the control arm's failure rate for an uninteresting reason.
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")

SCHEMA_ARM = "schema"
PROMPT_ARM = "prompt"
ARM_NAMES = {
    SCHEMA_ARM: "JSON mode (response_schema)",
    PROMPT_ARM: "Prompt-based JSON instructions",
}


def was_fenced(text: str) -> bool:
    """Did the reply arrive wrapped in a Markdown code fence?

    Counted because the control arm strips fences before parsing. Without this
    its failure rate reads as "the model always returned clean JSON" when it may
    mean "the harness cleaned up after it every time".
    """
    return bool(_FENCE.search(text.strip()))


def parse_cards(text: str) -> list[Flashcard]:
    payload = json.loads(_FENCE.sub("", text.strip()).strip())
    if not isinstance(payload, list):
        raise ValueError(f"expected a JSON array, got {type(payload).__name__}")
    return [Flashcard(**item) for item in payload]


@dataclass
class ArmResult:
    name: str
    latencies: list[float] = field(default_factory=list)
    cards: int = 0
    failures: list[str] = field(default_factory=list)
    # Kept apart from `failures` on purpose: running out of quota says nothing
    # about whether the arm can produce valid JSON, so folding it into the
    # failure rate would corrupt the only number this command exists to report.
    api_errors: list[str] = field(default_factory=list)
    fenced: int = 0  # replies that arrived wrapped in a code fence

    @property
    def runs(self) -> int:
        return len(self.latencies) + len(self.failures)

    @property
    def failure_rate(self) -> float:
        return len(self.failures) / self.runs if self.runs else 0.0

    @property
    def mean_latency(self) -> float:
        return mean(self.latencies) if self.latencies else 0.0


# --- the record, one per call ----------------------------------------------


def chunk_id(chunk: Chunk) -> str:
    """Stable across runs, so a resumed run can tell what it already did."""
    return f"{chunk.source_path.name}#{chunk.index}"


def load_records(path: Path) -> list[dict]:
    """Read a results file, skipping any line a crash left half-written."""
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue  # a torn final line is the expected damage from a kill
    return records


def append_record(path: Path, record: dict) -> None:
    """Append and flush, so a killed run keeps every call it paid for."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.flush()


def _key(record: dict) -> tuple[str, str, int]:
    return (record["arm"], record["chunk"], record["repeat"])


# --- executing one call -----------------------------------------------------


def _run_one(
    arm: str, chunk: Chunk, repeat: int, settings: Settings, client: GeminiClient
) -> dict:
    base = {"arm": arm, "chunk": chunk_id(chunk), "repeat": repeat}
    fenced = False

    try:
        if arm == SCHEMA_ARM:
            prompt = build_generation_prompt(chunk, settings.cards_per_chunk)
            # use_cache=False or the second arm would race a cached reply and
            # the whole comparison would be meaningless.
            cards = client.generate_cards(prompt, use_cache=False)
        else:
            prompt = build_json_instruction_prompt(chunk, settings.cards_per_chunk)
            raw = client.generate_text(prompt)
            fenced = was_fenced(raw)
            cards = parse_cards(raw)
    except errors.APIError as exc:
        # The message names the quota metric, which is the only way to tell a
        # per-minute throttle (wait and resume) from a spent daily cap (come
        # back tomorrow). A bare "429" cannot distinguish them.
        return {
            **base,
            "ok": False,
            "kind": "api",
            "detail": f"{exc.code} {exc.message}"[:300],
        }
    except (GeminiError, ValidationError, ValueError, TypeError) as exc:
        return {**base, "ok": False, "kind": "parse", "detail": str(exc)[:200],
                "fenced": fenced}

    return {
        **base,
        "ok": True,
        "latency": client.last_call_seconds,
        "cards": len(cards),
        "fenced": fenced,
    }


def summarise(records: Iterable[dict]) -> list[ArmResult]:
    arms = {arm: ArmResult(name=name) for arm, name in ARM_NAMES.items()}
    for record in records:
        arm = arms.get(record.get("arm"))
        if arm is None:
            continue
        if record.get("fenced"):
            arm.fenced += 1
        if record.get("ok"):
            arm.latencies.append(record.get("latency", 0.0))
            arm.cards += record.get("cards", 0)
        elif record.get("kind") == "api":
            arm.api_errors.append(f"{record['chunk']}: {record.get('detail')}")
        else:
            arm.failures.append(f"{record['chunk']}: {record.get('detail')}")
    return [arms[SCHEMA_ARM], arms[PROMPT_ARM]]


def planned_calls(chunks: list[Chunk], repeats: int) -> list[tuple[str, Chunk, int]]:
    """Interleave the arms, alternating which one leads on each repeat.

    Running every schema call before every prompt call biases the result under a
    quota ceiling: whichever arm goes first spends the available quota and the
    other collects the 429s. That is what produced the earlier lopsided 9-vs-6
    sample, which looked like a property of the arms and was an artefact of the
    order they ran in.
    """
    return [
        (arm, chunk, repeat)
        for repeat in range(repeats)
        for chunk in chunks
        for arm in (
            (SCHEMA_ARM, PROMPT_ARM) if repeat % 2 == 0 else (PROMPT_ARM, SCHEMA_ARM)
        )
    ]


def run(
    chunks: list[Chunk],
    settings: Settings,
    client: GeminiClient,
    repeats: int = 1,
    results_path: Path | None = None,
    progress: Callable[[dict], None] | None = None,
    quota_stop: int = 6,
) -> list[ArmResult]:
    """Run both arms, persisting and reporting each call as it happens.

    An earlier version accumulated everything in memory and returned only at the
    end, so an hour of quota spent against a rate limit produced nothing at all
    when the process was killed. Every call is now written to `results_path`
    immediately, already-recorded calls are skipped, and a run of consecutive
    quota errors stops the whole thing rather than grinding through every
    remaining call four attempts at a time.
    """
    previous = load_records(results_path) if results_path else []
    done = {_key(record) for record in previous}
    fresh: list[dict] = []
    consecutive_api = 0

    for arm, chunk, repeat in planned_calls(chunks, repeats):
        if (arm, chunk_id(chunk), repeat) in done:
            continue

        record = _run_one(arm, chunk, repeat, settings, client)
        fresh.append(record)
        # A quota error is a call that did not happen, not a result. Writing it
        # would make a resumed run skip the very gap it exists to fill.
        if results_path and not (not record["ok"] and record["kind"] == "api"):
            append_record(results_path, record)
        if progress:
            progress(record)

        if not record["ok"] and record.get("kind") == "api":
            consecutive_api += 1
            if consecutive_api >= quota_stop:
                if progress:
                    progress({"event": "stopped", "after": consecutive_api})
                break
        else:
            consecutive_api = 0

    return summarise(previous + fresh)
