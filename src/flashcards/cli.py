from __future__ import annotations

from pathlib import Path

import typer

from flashcards import __version__
from flashcards.client import GeminiClient, GeminiError
from flashcards.config import ConfigError, load_settings
from flashcards.models import Chunk
from flashcards.prompts import build_generation_prompt

app = typer.Typer(
    add_completion=False,
    help="Convert study notes into Anki-importable flashcards.",
)

# Phase B scaffolding: a fixed chunk so the slice can be exercised before the
# loader and chunker exist. Replaced by real input in Phase D.
_DEMO_TEXT = (
    "Tokenization is the process of breaking text into smaller units called "
    "tokens, such as words, subwords, or characters. It is one of the first and "
    "most important preprocessing steps in Natural Language Processing because "
    "machine learning models cannot directly understand raw text. Modern NLP "
    "models often use subword tokenization techniques like Byte Pair Encoding "
    "(BPE) or WordPiece, which handle rare or unseen words more effectively "
    "than traditional word-level tokenization."
)


@app.callback()
def main() -> None:
    # Keeps Typer in a subcommand layout; without it a lone command gets
    # promoted to the root and `flashcards <name>` fails as an extra argument.
    pass


@app.command()
def version() -> None:
    typer.echo(f"flashcards {__version__}")


@app.command()
def demo() -> None:
    """Run one hardcoded chunk through one API call and print the cards."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    chunk = Chunk(
        text=_DEMO_TEXT,
        source_path=Path("notes/02_NLP_Tokenization_and_Text_Preprocessing.md"),
        heading="Tokenization and Text Preprocessing",
        index=0,
    )
    client = GeminiClient(settings)

    try:
        cards = client.generate_cards(
            build_generation_prompt(chunk, settings.cards_per_chunk)
        )
    except GeminiError as exc:
        typer.secho(f"Generation failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    for position, card in enumerate(cards, start=1):
        typer.secho(f"\n[{position}] {card.question}", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"    {card.answer}")
        typer.echo(f"    topic={card.topic}  difficulty={card.difficulty}")

    typer.echo(f"\ncards: {len(cards)}   requests: {client.request_count}")


# `generate` and `benchmark` land in later phases.

if __name__ == "__main__":
    app()
