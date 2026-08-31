from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
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

    @property
    def runs(self) -> int:
        return len(self.latencies) + len(self.failures)

    @property
    def failure_rate(self) -> float:
        return len(self.failures) / self.runs if self.runs else 0.0

    @property
    def mean_latency(self) -> float:
        return mean(self.latencies) if self.latencies else 0.0


def _schema_arm(chunks: list[Chunk], settings: Settings, client: GeminiClient) -> ArmResult:
    arm = ArmResult(name="JSON mode (response_schema)")
    for chunk in chunks:
        prompt = build_generation_prompt(chunk, settings.cards_per_chunk)
        started = time.perf_counter()
        try:
            # use_cache=False or the second arm would race a cached reply and
            # the whole comparison would be meaningless.
            cards = client.generate_cards(prompt, use_cache=False)
        except errors.APIError as exc:
            arm.api_errors.append(f"{chunk.source_path.name}#{chunk.index}: {exc.code}")
            continue
        except (GeminiError, ValidationError, ValueError) as exc:
            arm.failures.append(f"{chunk.source_path.name}#{chunk.index}: {exc}")
            continue
        arm.latencies.append(time.perf_counter() - started)
        arm.cards += len(cards)
    return arm


def _prompt_arm(chunks: list[Chunk], settings: Settings, client: GeminiClient) -> ArmResult:
    arm = ArmResult(name="Prompt-based JSON instructions")
    for chunk in chunks:
        prompt = build_json_instruction_prompt(chunk, settings.cards_per_chunk)
        started = time.perf_counter()
        try:
            cards = parse_cards(client.generate_text(prompt))
        except errors.APIError as exc:
            arm.api_errors.append(f"{chunk.source_path.name}#{chunk.index}: {exc.code}")
            continue
        except (GeminiError, ValidationError, ValueError, TypeError) as exc:
            arm.failures.append(f"{chunk.source_path.name}#{chunk.index}: {exc}")
            continue
        arm.latencies.append(time.perf_counter() - started)
        arm.cards += len(cards)
    return arm


def run(
    chunks: list[Chunk], settings: Settings, client: GeminiClient, repeats: int = 1
) -> list[ArmResult]:
    schema = ArmResult(name="JSON mode (response_schema)")
    prompted = ArmResult(name="Prompt-based JSON instructions")

    for _ in range(repeats):
        for source, target in (
            (_schema_arm(chunks, settings, client), schema),
            (_prompt_arm(chunks, settings, client), prompted),
        ):
            target.latencies.extend(source.latencies)
            target.failures.extend(source.failures)
            target.api_errors.extend(source.api_errors)
            target.cards += source.cards

    return [schema, prompted]
