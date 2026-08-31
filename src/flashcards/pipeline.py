from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from flashcards import loader
from flashcards.chunker import chunk_text
from flashcards.client import GeminiClient, GeminiError
from flashcards.config import Settings
from flashcards.models import Chunk, SourcedCard
from flashcards.prompts import build_generation_prompt
from flashcards.validator import filter_cards


@dataclass
class Result:
    chunks: list[Chunk]
    cards: list[SourcedCard] = field(default_factory=list)
    dropped: int = 0
    failures: list[str] = field(default_factory=list)
    requests: int = 0
    cache_hits: int = 0


def collect_chunks(source: Path, settings: Settings) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in loader.discover(source, settings.note_suffixes):
        chunks.extend(
            chunk_text(loader.load(path), path, settings.chunk_target_tokens)
        )
    return chunks


def run(
    source: Path,
    settings: Settings,
    client: GeminiClient,
    limit: int | None = None,
) -> Result:
    chunks = collect_chunks(source, settings)[:limit]
    result = Result(chunks=chunks)

    for chunk in chunks:
        try:
            cards = client.generate_cards(
                build_generation_prompt(chunk, settings.cards_per_chunk)
            )
        except GeminiError as exc:
            # One bad chunk should not throw away the cards already paid for.
            result.failures.append(f"{chunk.source_path.name}#{chunk.index}: {exc}")
            continue

        kept, dropped = filter_cards(cards)
        result.cards.extend(
            SourcedCard(card=card, source=chunk.source_path.stem) for card in kept
        )
        result.dropped += len(dropped)

    result.requests = client.request_count
    result.cache_hits = client.cache_hits
    return result
