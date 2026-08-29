from __future__ import annotations

from pathlib import Path

import pytest

from flashcards.models import Chunk
from flashcards.prompts import build_generation_prompt


@pytest.fixture
def chunk() -> Chunk:
    return Chunk(
        text="Tokenization splits text into tokens.",
        source_path=Path("notes/02_tokenization.md"),
        heading="Tokenization",
        index=0,
    )


def test_prompt_includes_source_text_and_heading(chunk: Chunk) -> None:
    prompt = build_generation_prompt(chunk, max_cards=5)
    assert chunk.text in prompt
    assert chunk.heading in prompt


def test_prompt_states_the_card_limit(chunk: Chunk) -> None:
    assert "at most 7 flashcards" in build_generation_prompt(chunk, max_cards=7)


def test_prompt_forbids_source_dependent_questions(chunk: Chunk) -> None:
    # The schema cannot express "answerable without the notes", so the prompt
    # must carry it. If this wording is dropped the validator stage silently
    # becomes the only defence.
    prompt = build_generation_prompt(chunk, max_cards=5)
    assert "according to the text" in prompt
    assert "stand alone" in prompt


def test_missing_heading_renders_placeholder() -> None:
    chunk = Chunk(text="body", source_path=Path("a.md"), heading="", index=0)
    assert "(none)" in build_generation_prompt(chunk, max_cards=3)
