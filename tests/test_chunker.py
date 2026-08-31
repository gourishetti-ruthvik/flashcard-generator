from __future__ import annotations

from pathlib import Path

from flashcards.chunker import chunk_text, estimate_tokens

NOTE = Path("notes/sample.md")


def test_small_note_is_a_single_chunk() -> None:
    # This is what the real notes/ directory looks like: every file fits.
    chunks = chunk_text("# Heading\n\nA short paragraph.", NOTE, target_tokens=800)
    assert len(chunks) == 1
    assert chunks[0].heading == "Heading"
    assert chunks[0].source_path == NOTE


def test_each_heading_starts_a_new_chunk() -> None:
    text = "# One\n\nAlpha body.\n\n# Two\n\nBeta body."
    chunks = chunk_text(text, NOTE, target_tokens=800)
    assert [c.heading for c in chunks] == ["One", "Two"]


def test_text_before_any_heading_is_kept() -> None:
    chunks = chunk_text("Preamble text.\n\n# Later\n\nBody.", NOTE, target_tokens=800)
    assert chunks[0].heading == ""
    assert "Preamble" in chunks[0].text


def test_large_section_splits_on_paragraph_boundaries() -> None:
    paragraph = "word " * 100  # ~500 chars, ~125 tokens
    text = "# Big\n\n" + "\n\n".join([paragraph.strip()] * 6)
    chunks = chunk_text(text, NOTE, target_tokens=300)

    assert len(chunks) > 1
    assert all(estimate_tokens(c.text) <= 300 for c in chunks)
    assert all(c.heading == "Big" for c in chunks)


def test_oversized_paragraph_splits_without_breaking_a_sentence() -> None:
    sentences = [f"This is sentence number {n} of the paragraph." for n in range(40)]
    text = "# Dense\n\n" + " ".join(sentences)
    chunks = chunk_text(text, NOTE, target_tokens=60)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.rstrip().endswith(".")


def test_no_content_is_lost_when_splitting() -> None:
    sentences = [f"Sentence {n} here." for n in range(30)]
    text = "# Keep\n\n" + " ".join(sentences)
    rejoined = " ".join(c.text for c in chunk_text(text, NOTE, target_tokens=50))
    for sentence in sentences:
        assert sentence in rejoined


def test_indexes_are_sequential() -> None:
    text = "# A\n\nbody a\n\n# B\n\nbody b\n\n# C\n\nbody c"
    assert [c.index for c in chunk_text(text, NOTE, 800)] == [0, 1, 2]


def test_empty_and_heading_only_input_yields_nothing() -> None:
    assert chunk_text("", NOTE, 800) == []
    assert chunk_text("# Only A Heading", NOTE, 800) == []


def test_token_estimate_scales_with_length() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 800) == 200
