from __future__ import annotations

from pathlib import Path

from flashcards.loader import discover, load, strip_markdown


def test_headings_survive_stripping() -> None:
    # The chunker splits on headings, so they must outlive the loader.
    assert strip_markdown("## Tokenization\n\ntext") == "## Tokenization\n\ntext"


def test_inline_formatting_is_removed() -> None:
    source = "**bold** and *italic* and `code` and __also bold__"
    assert strip_markdown(source) == "bold and italic and code and also bold"


def test_links_keep_their_text_and_images_go() -> None:
    assert strip_markdown("see [the docs](http://x.com)") == "see the docs"
    assert strip_markdown("![diagram](img.png)text") == "text"


def test_fenced_code_blocks_are_dropped() -> None:
    source = "before\n\n```python\nprint('x')\n```\n\nafter"
    stripped = strip_markdown(source)
    assert "print" not in stripped
    assert "before" in stripped and "after" in stripped


def test_list_markers_and_quotes_are_removed() -> None:
    assert strip_markdown("- first\n- second") == "first\nsecond"
    assert strip_markdown("> quoted") == "quoted"


def test_underscores_inside_words_are_kept() -> None:
    # Guards the italic rule against eating snake_case identifiers.
    assert strip_markdown("use max_output_tokens here") == "use max_output_tokens here"


def test_discover_finds_notes_recursively_and_sorted(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "sub" / "c.txt").write_text("c", encoding="utf-8")
    (tmp_path / "ignore.png").write_text("x", encoding="utf-8")

    found = discover(tmp_path, (".md", ".txt"))
    assert [p.name for p in found] == ["a.md", "b.md", "c.txt"]


def test_discover_accepts_a_single_file(tmp_path: Path) -> None:
    note = tmp_path / "one.md"
    note.write_text("x", encoding="utf-8")
    assert discover(note, (".md",)) == [note]


def test_load_reads_utf8(tmp_path: Path) -> None:
    note = tmp_path / "n.md"
    note.write_text("# Café\n\n**naïve** résumé", encoding="utf-8")
    assert load(note) == "# Café\n\nnaïve résumé"
