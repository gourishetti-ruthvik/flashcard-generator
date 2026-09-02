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


# --- the minimum chunk size ------------------------------------------------
#
# Without one, a heading-only preamble and an orphaned tail each cost a whole
# API request. On a twenty-a-day allowance that was three of twenty on the
# sample notes: 15% of the day spent on 36-token scraps.

BIG = "Sentence number one here. " * 40     # ~260 tokens, stands alone
SMALL = "Tiny preamble."                    # ~3 tokens, cannot


def test_a_preamble_folds_forward_into_what_it_introduces() -> None:
    text = f"{SMALL}\n\n# Real Heading\n\n{BIG}"
    chunks = chunk_text(text, NOTE, target_tokens=800, min_tokens=100)
    assert len(chunks) == 1
    assert SMALL in chunks[0].text and BIG.strip() in chunks[0].text
    # The larger side names the result; a two-line preamble must not relabel it.
    assert chunks[0].heading == "Real Heading"


def test_an_orphaned_tail_folds_back_into_its_section() -> None:
    text = f"# Section\n\n{BIG}\n\n# Coda\n\n{SMALL}"
    chunks = chunk_text(text, NOTE, target_tokens=800, min_tokens=100)
    assert len(chunks) == 1
    assert chunks[0].heading == "Section"


def test_sections_that_stand_alone_are_left_alone() -> None:
    text = f"# One\n\n{BIG}\n\n# Two\n\n{BIG}"
    chunks = chunk_text(text, NOTE, target_tokens=800, min_tokens=100)
    assert [c.heading for c in chunks] == ["One", "Two"]


def test_merging_never_loses_content() -> None:
    """The whole point is to spend fewer requests, not to drop material."""
    text = f"{SMALL}\n\n# A\n\n{BIG}\n\n# B\n\n{SMALL}"
    merged = chunk_text(text, NOTE, target_tokens=800, min_tokens=100)
    split = chunk_text(text, NOTE, target_tokens=800, min_tokens=0)
    assert len(merged) < len(split)          # fewer requests
    joined = " ".join(c.text for c in merged)
    for part in (SMALL, BIG.strip()):
        assert part in joined                 # and nothing left behind


def test_zero_disables_the_merge() -> None:
    text = f"{SMALL}\n\n# Real Heading\n\n{BIG}"
    assert len(chunk_text(text, NOTE, target_tokens=800, min_tokens=0)) == 2


def test_a_lone_small_note_is_still_a_chunk() -> None:
    # Nothing to merge into. Better one thin request than losing the content.
    chunks = chunk_text(SMALL, NOTE, target_tokens=800, min_tokens=100)
    assert len(chunks) == 1 and SMALL in chunks[0].text


def test_a_merge_may_overshoot_the_target() -> None:
    """A near-full chunk beside a small tail is not worth keeping apart.

    The target rests on a four-chars-per-token estimate, so treating it as a
    hard wall would preserve an orphan for no real reason.
    """
    body = "Word here. " * 287           # ~789 tokens, just under the target
    tail = "Tail sentence here. " * 6    # ~30 tokens, under the minimum
    text = "# Long\n\n" + body + "\n\n# Tail\n\n" + tail
    chunks = chunk_text(text, NOTE, target_tokens=800, min_tokens=100)
    assert len(chunks) == 1
    assert estimate_tokens(chunks[0].text) > 800


def test_no_chunk_grows_past_the_target_plus_the_minimum() -> None:
    """The overshoot is bounded, or the merge would undo the packing.

    Checked as an invariant across several shapes rather than by contriving a
    single refusal: the merge cascades, and two hand-built examples proved
    less honest than sweeping the sizes.
    """
    shapes = [
        SMALL + "\n\n# A\n\n" + BIG + "\n\n# B\n\n" + SMALL,
        "# Long\n\n" + "Word here. " * 320 + "\n\n# Tail\n\n" + SMALL,
        "# Long\n\n" + "Word here. " * 500 + "\n\n# Tail\n\n" + SMALL,
        "\n\n".join("# H" + str(n) + "\n\n" + SMALL for n in range(12)),
    ]
    for text in shapes:
        for chunk in chunk_text(text, NOTE, target_tokens=800, min_tokens=100):
            assert estimate_tokens(chunk.text) <= 800 + 100
