from __future__ import annotations

import csv
from pathlib import Path

from flashcards.exporter import to_row, to_tag, write_csv
from flashcards.models import Flashcard, SourcedCard


def entry(
    question: str = "What is entropy?",
    answer: str = "A measure of disorder.",
    topic: str = "Natural Language Processing",
    difficulty: str = "easy",
    source: str = "03_Word_Embeddings",
) -> SourcedCard:
    return SourcedCard(
        card=Flashcard(
            question=question, answer=answer, topic=topic, difficulty=difficulty
        ),
        source=source,
    )


def test_multiword_topic_becomes_one_tag() -> None:
    # Anki splits tags on whitespace; three words would become three tags.
    assert to_tag("Natural Language Processing") == "Natural_Language_Processing"


def test_tag_strips_punctuation_and_edges() -> None:
    assert to_tag("  NLP: tokenization!  ") == "NLP_tokenization"


def test_row_has_three_space_separated_tags() -> None:
    front, back, tags = to_row(entry())
    assert front == "What is entropy?"
    assert back == "A measure of disorder."
    assert tags.split(" ") == [
        "Natural_Language_Processing",
        "easy",
        "03_Word_Embeddings",
    ]


def test_newlines_in_answers_become_br() -> None:
    _, back, _ = to_row(entry(answer="First line.\nSecond line."))
    assert back == "First line.<br>Second line."


def test_file_starts_with_anki_directives(tmp_path: Path) -> None:
    out = tmp_path / "cards.csv"
    write_csv([entry()], out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#separator:Comma"
    assert lines[1] == "#columns:Front,Back,Tags"


def test_no_bom_is_written(tmp_path: Path) -> None:
    # Anki reads plain UTF-8; a BOM corrupts the first field.
    out = tmp_path / "cards.csv"
    write_csv([entry()], out)
    assert not out.read_bytes().startswith(b"\xef\xbb\xbf")


def test_no_blank_rows_between_records(tmp_path: Path) -> None:
    # Without newline="" the csv module emits \r\r\n on Windows and every other
    # imported row is empty.
    out = tmp_path / "cards.csv"
    write_csv([entry(), entry(question="Second?")], out)
    assert b"\r\r\n" not in out.read_bytes()


def test_round_trips_through_a_csv_reader(tmp_path: Path) -> None:
    out = tmp_path / "cards.csv"
    write_csv([entry(question='He said "hi", loudly'), entry(question="Plain?")], out)

    with out.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.reader(handle) if not row[0].startswith("#")]

    assert len(rows) == 2
    assert rows[0][0] == 'He said "hi", loudly'
    assert all(len(row) == 3 for row in rows)


def test_unicode_survives(tmp_path: Path) -> None:
    out = tmp_path / "cards.csv"
    write_csv([entry(answer="Café naïve résumé")], out)
    assert "Café naïve résumé" in out.read_text(encoding="utf-8")


def test_write_creates_missing_directories(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "deeper" / "cards.csv"
    assert write_csv([entry()], out) == 1
    assert out.exists()
