from __future__ import annotations

import pytest

from flashcards.dedupe import cosine, deduplicate
from flashcards.models import Flashcard, SourcedCard


def entry(question: str) -> SourcedCard:
    return SourcedCard(
        card=Flashcard(
            question=question, answer="An answer.", topic="T", difficulty="easy"
        ),
        source="notes",
    )


def encoder_from(table: dict[str, list[float]]):
    """Stands in for the embedding model so tests need no torch."""
    return lambda questions: [table[q] for q in questions]


def test_cosine_of_identical_vectors_is_one() -> None:
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_of_orthogonal_vectors_is_zero() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_handles_a_zero_vector() -> None:
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_near_duplicates_are_dropped() -> None:
    entries = [entry("What is tokenization?"), entry("Define tokenization.")]
    table = {
        "What is tokenization?": [1.0, 0.0, 0.0],
        "Define tokenization.": [0.99, 0.14, 0.0],
    }
    kept, dropped = deduplicate(entries, 0.9, "unused", encoder_from(table))
    assert kept == [entries[0]]
    assert dropped == [entries[1]]


def test_distinct_questions_are_kept() -> None:
    entries = [entry("What is tokenization?"), entry("What is a word embedding?")]
    table = {
        "What is tokenization?": [1.0, 0.0],
        "What is a word embedding?": [0.0, 1.0],
    }
    kept, dropped = deduplicate(entries, 0.9, "unused", encoder_from(table))
    assert kept == entries
    assert dropped == []


def test_threshold_is_respected() -> None:
    entries = [entry("A"), entry("B")]
    table = {"A": [1.0, 0.0], "B": [0.8, 0.6]}  # cosine 0.8
    assert len(deduplicate(entries, 0.9, "x", encoder_from(table))[0]) == 2
    assert len(deduplicate(entries, 0.7, "x", encoder_from(table))[0]) == 1


def test_first_of_a_group_survives() -> None:
    entries = [entry("A"), entry("B"), entry("C")]
    table = {"A": [1.0, 0.0], "B": [1.0, 0.01], "C": [1.0, 0.02]}
    kept, dropped = deduplicate(entries, 0.9, "x", encoder_from(table))
    assert kept == [entries[0]]
    assert len(dropped) == 2


def test_short_inputs_short_circuit_without_encoding() -> None:
    def explode(_: list[str]):
        raise AssertionError("encoder should not be called")

    assert deduplicate([], 0.9, "x", explode) == ([], [])
    single = [entry("only")]
    assert deduplicate(single, 0.9, "x", explode) == (single, [])
