from __future__ import annotations

from pathlib import Path

import typer

from flashcards import __version__, pipeline
from flashcards.client import GeminiClient
from flashcards.config import ConfigError, load_settings

app = typer.Typer(
    add_completion=False,
    help="Convert study notes into Anki-importable flashcards.",
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
def generate(
    source: Path = typer.Argument(..., exists=True, help="Note file or directory."),
    limit: int | None = typer.Option(None, "--limit", help="Only process N chunks."),
) -> None:
    """Turn a directory of notes into flashcards."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    result = pipeline.run(source, settings, GeminiClient(settings), limit=limit)

    for position, card in enumerate(result.cards, start=1):
        typer.secho(f"\n[{position}] {card.question}", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"    {card.answer}")
        typer.echo(f"    topic={card.topic}  difficulty={card.difficulty}")

    for failure in result.failures:
        typer.secho(f"chunk failed: {failure}", fg=typer.colors.RED)

    typer.echo(
        f"\nchunks: {len(result.chunks)}   cards: {len(result.cards)}   "
        f"dropped: {result.dropped}   requests: {result.requests}   "
        f"cached: {result.cache_hits}"
    )


# `--out`, `--dry-run` and `benchmark` land in later phases.

if __name__ == "__main__":
    app()
