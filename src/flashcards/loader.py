from __future__ import annotations

import re
from pathlib import Path

# Applied in order. Heading markers survive on purpose: the chunker splits on
# them, and only then does the heading text become chunk provenance.
_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"```.*?```", re.DOTALL), ""),  # fenced code
    (re.compile(r"^\s*(?:[-*_]\s*){3,}$", re.MULTILINE), ""),  # horizontal rules
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),  # images
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),  # links -> text
    (re.compile(r"`([^`]+)`"), r"\1"),  # inline code
    (re.compile(r"(\*\*|__)(.+?)\1"), r"\2"),  # bold
    (re.compile(r"(?<!\w)([*_])(.+?)\1(?!\w)"), r"\2"),  # italic
    (re.compile(r"^\s*>\s?", re.MULTILINE), ""),  # blockquotes
    (re.compile(r"^\s*(?:[-*+]|\d+\.)\s+", re.MULTILINE), ""),  # list markers
    (re.compile(r"\n{3,}"), "\n\n"),  # collapse blank runs
)


def strip_markdown(text: str) -> str:
    for pattern, replacement in _SUBSTITUTIONS:
        text = pattern.sub(replacement, text)
    return text.strip()


def discover(source: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if source.is_file():
        return [source]
    # Sorted so a run over the same directory produces the same chunk order,
    # which keeps cache keys and output stable.
    return sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    )


def load(path: Path) -> str:
    return strip_markdown(path.read_text(encoding="utf-8"))
