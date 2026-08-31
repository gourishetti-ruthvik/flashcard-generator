from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from pathlib import Path

from flashcards.models import SourcedCard

COLUMNS = ("Front", "Back", "Tags")
_NON_TAG_CHARS = re.compile(r"[^0-9A-Za-z]+")


def to_tag(value: str) -> str:
    # Anki separates tags on whitespace, so "Natural Language Processing" would
    # otherwise import as three unrelated tags.
    return _NON_TAG_CHARS.sub("_", value).strip("_")


def to_row(entry: SourcedCard) -> tuple[str, str, str]:
    card = entry.card
    tags = [to_tag(card.topic), to_tag(card.difficulty), to_tag(entry.source)]
    return (
        card.question.strip(),
        # Anki renders fields as HTML, so a literal newline would collapse.
        card.answer.strip().replace("\n", "<br>"),
        " ".join(tag for tag in tags if tag),
    )


def write_csv(entries: Iterable[SourcedCard], out: Path) -> int:
    rows = [to_row(entry) for entry in entries]
    out.parent.mkdir(parents=True, exist_ok=True)

    # newline="" is required: without it csv writes \r\r\n on Windows and every
    # other imported row is blank. utf-8 without a BOM, which Anki expects.
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("#separator:Comma\n")
        handle.write(f"#columns:{','.join(COLUMNS)}\n")
        csv.writer(handle).writerows(rows)

    return len(rows)
