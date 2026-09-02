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


def _absorb_small(
    parts: list[tuple[str, str]], target: int, minimum: int
) -> list[tuple[str, str]]:
    """Fold a too-small part into a neighbour instead of spending a request.

    Two shapes produce these. A preamble sitting before the first heading is
    its own section and so its own chunk; an orphaned tail is what is left when
    a long section splits at the token limit. Both are real content that has to
    go somewhere, and both are far too thin to yield the five cards the prompt
    asks for -- on a twenty-a-day allowance, three of them cost 15% of the day.

    A merge may exceed the target by up to `minimum`. The target is a soft
    guide resting on a four-chars-per-token estimate, so refusing to join 765
    and 36 because 801 crosses 800 would keep the orphan for no real reason.
    """
    if minimum <= 0:
        return parts

    limit = target + minimum
    merged: list[tuple[str, str]] = []
    for heading, text in parts:
        joinable = (
            merged
            and estimate_tokens(text) < minimum
            and estimate_tokens(merged[-1][1] + text) <= limit
        )
        if joinable:
            previous_heading, previous_text = merged[-1]
            # The larger side names the result; a two-line preamble should not
            # relabel the section it was folded into.
            keep = previous_heading if len(previous_text) >= len(text) else heading
            merged[-1] = (keep, previous_text + "\n\n" + text)
        else:
            merged.append((heading, text))

    # A small first part has no previous neighbour, so it folds forward into
    # whatever it introduces.
    if len(merged) > 1 and estimate_tokens(merged[0][1]) < minimum:
        (first_heading, first_text), (next_heading, next_text) = merged[0], merged[1]
        if estimate_tokens(first_text + next_text) <= limit:
            keep = next_heading if len(next_text) >= len(first_text) else first_heading
            merged[1] = (keep, first_text + "\n\n" + next_text)
            del merged[0]

    return merged


def chunk_text(
    text: str,
    source_path: Path,
    target_tokens: int,
    min_tokens: int = 0,
) -> list[Chunk]:
    parts: list[tuple[str, str]] = []

    for heading, body in _sections(text):
        pieces: list[str] = []
        for paragraph in _PARAGRAPH_BREAK.split(body):
            if paragraph.strip():
                pieces.extend(_split_oversized(paragraph.strip(), target_tokens))

        parts.extend((heading, part) for part in _pack(pieces, target_tokens, "\n\n"))

    return [
        Chunk(text=part, source_path=source_path, heading=heading, index=index)
        for index, (heading, part) in enumerate(
            _absorb_small(parts, target_tokens, min_tokens)
        )
    ]
