from __future__ import annotations

import re

from flashcards.models import Flashcard

# JSON mode already guarantees the shape, so the only checks worth running here
# are the ones a schema cannot express.
_SOURCE_DEPENDENT = re.compile(
    r"according to the (text|passage|notes|document|author)"
    r"|in the (text|passage|notes|document|above)"
    r"|as (mentioned|described|stated|shown) (above|earlier|previously)"
    r"|the (text|passage|notes|document) (state|say|mention|describe)s?"
    r"|this (passage|text|section|document)",
    re.IGNORECASE,
)

_MIN_ANSWER_WORDS = 3


def is_usable(card: Flashcard) -> bool:
    if not card.question.strip() or not card.answer.strip():
        return False
    if _SOURCE_DEPENDENT.search(card.question):
        return False
    return len(card.answer.split()) >= _MIN_ANSWER_WORDS


def filter_cards(cards: list[Flashcard]) -> tuple[list[Flashcard], list[Flashcard]]:
    """Split into (kept, dropped), discarding repeats of the same question."""
    kept: list[Flashcard] = []
    dropped: list[Flashcard] = []
    seen: set[str] = set()

    for card in cards:
        marker = card.question.strip().casefold()
        if is_usable(card) and marker not in seen:
            seen.add(marker)
            kept.append(card)
        else:
            dropped.append(card)

    return kept, dropped
