from __future__ import annotations

import pytest

from flashcards.models import Flashcard
from flashcards.validator import filter_cards, is_usable


def card(question: str = "What is entropy?", answer: str = "A measure of disorder.") -> Flashcard:
    return Flashcard(question=question, answer=answer, topic="T", difficulty="easy")


def test_a_self_contained_card_is_kept() -> None:
    assert is_usable(card())


@pytest.mark.parametrize(
    "question",
    [
        "According to the text, what is entropy?",
        "What does the passage state about entropy?",
        "As mentioned above, what is entropy?",
        "What is the main idea of this section?",
        "In the notes, which algorithm is fastest?",
    ],
)
def test_source_dependent_questions_are_rejected(question: str) -> None:
    # These are unanswerable once the card is out of Anki and away from the note.
    assert not is_usable(card(question=question))


def test_blank_fields_are_rejected() -> None:
    assert not is_usable(card(question="   "))
    assert not is_usable(card(answer=""))


def test_one_word_answers_are_rejected() -> None:
    assert not is_usable(card(answer="Disorder."))


def test_filter_reports_both_sides() -> None:
    good = card()
    bad = card(question="According to the text, what is entropy?")
    kept, dropped = filter_cards([good, bad])
    assert kept == [good]
    assert dropped == [bad]


def test_duplicate_questions_are_dropped_case_insensitively() -> None:
    first = card(question="What is entropy?")
    repeat = card(question="  what is ENTROPY?  ")
    kept, dropped = filter_cards([first, repeat])
    assert kept == [first]
    assert dropped == [repeat]
