from __future__ import annotations

import re
from pathlib import Path

from flashcards.models import Chunk

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def estimate_tokens(text: str) -> int:
    # Four characters per token is the usual English rule of thumb. The real
    # tokenizer is a network call, and --dry-run has to work without one.
    return max(1, len(text) // 4)


def _sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading = ""
    body: list[str] = []

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            if body:
                sections.append((heading, "\n".join(body)))
            heading = match.group(2).strip()
            body = []
        else:
            body.append(line)

    if body:
        sections.append((heading, "\n".join(body)))
    return [(head, chunk.strip()) for head, chunk in sections if chunk.strip()]


def _pack(pieces: list[str], target: int, separator: str) -> list[str]:
    packed: list[str] = []
    current: list[str] = []

    for piece in pieces:
        candidate = current + [piece]
        if current and estimate_tokens(separator.join(candidate)) > target:
            packed.append(separator.join(current))
            current = [piece]
        else:
            current = candidate

    if current:
        packed.append(separator.join(current))
    return packed


def _split_oversized(paragraph: str, target: int) -> list[str]:
    if estimate_tokens(paragraph) <= target:
        return [paragraph]
    # Falling back to sentences keeps the promise that a chunk never ends
    # mid-sentence, even when one paragraph is larger than the whole target.
    return _pack(_SENTENCE_END.split(paragraph), target, " ")


def chunk_text(text: str, source_path: Path, target_tokens: int) -> list[Chunk]:
    chunks: list[Chunk] = []

    for heading, body in _sections(text):
        pieces: list[str] = []
        for paragraph in _PARAGRAPH_BREAK.split(body):
            if paragraph.strip():
                pieces.extend(_split_oversized(paragraph.strip(), target_tokens))

        for part in _pack(pieces, target_tokens, "\n\n"):
            chunks.append(
                Chunk(
                    text=part,
                    source_path=source_path,
                    heading=heading,
                    index=len(chunks),
                )
            )

    return chunks
