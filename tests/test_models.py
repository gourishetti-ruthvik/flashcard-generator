from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from flashcards.models import Chunk, Flashcard


def test_valid_flashcard() -> None:
    card = Flashcard(
        question="What is tokenization?",
        answer="Splitting text into smaller units called tokens.",
        topic="Natural Language Processing",
        difficulty="easy",
    )
    assert card.difficulty == "easy"


@pytest.mark.parametrize("bad", ["trivial", "EASY", "", "very hard"])
def test_difficulty_is_constrained(bad: str) -> None:
    with pytest.raises(ValidationError):
        Flashcard(question="q", answer="a", topic="t", difficulty=bad)


def test_flashcard_requires_every_field() -> None:
    with pytest.raises(ValidationError):
        Flashcard(question="q", answer="a")


def test_chunk_is_frozen() -> None:
    chunk = Chunk(text="body", source_path=Path("notes/a.md"), heading="H", index=0)
    with pytest.raises(ValidationError):
        chunk.text = "changed"


def test_chunk_coerces_str_to_path() -> None:
    chunk = Chunk(text="body", source_path="notes/a.md", heading="H", index=0)
    assert isinstance(chunk.source_path, Path)
