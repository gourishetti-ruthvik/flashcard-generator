from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from google.genai import errors

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
    # Set when the run stopped early because the API refused. Kept as the
    # exception rather than a flag so callers can tell a per-minute
    # throttle from a spent daily cap and say something useful.
    api_error: errors.APIError | None = None


def collect_chunks(source: Path, settings: Settings) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in loader.discover(source, settings.note_suffixes):
        chunks.extend(
            chunk_text(
                loader.load(path),
                path,
                settings.chunk_target_tokens,
                settings.min_chunk_tokens,
            )
        )
    return chunks


def chunks_from_text(text: str, settings: Settings, name: str = "pasted") -> list[Chunk]:
    # The web UI's input is pasted text, not a folder. A synthetic path keeps
    # Chunk.source_path.stem meaningful, so the exporter's source tag needs no
    # special case for this route.
    return chunk_text(
        loader.strip_markdown(text),
        Path(f"{name}.md"),
        settings.chunk_target_tokens,
        settings.min_chunk_tokens,
    )


def run(
    chunks: list[Chunk],
    settings: Settings,
    client: GeminiClient,
    limit: int | None = None,
) -> Result:
    chunks = chunks[:limit]
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
        except errors.APIError as exc:
            # Stop rather than continue: a quota refusal applies to every
            # remaining chunk too, so carrying on would spend the rest of the
            # allowance learning the same thing. Escaping uncaught gave the CLI
            # a raw traceback and threw away the cards already paid for.
            result.api_error = exc
            break

        kept, dropped = filter_cards(cards)
        result.cards.extend(
            SourcedCard(card=card, source=chunk.source_path.stem) for card in kept
        )
        result.dropped += len(dropped)

    result.requests = client.request_count
    result.cache_hits = client.cache_hits
    return result
