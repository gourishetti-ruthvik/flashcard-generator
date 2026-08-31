from __future__ import annotations

from pathlib import Path

import typer

from flashcards import __version__, dedupe, exporter, pipeline
from flashcards.chunker import estimate_tokens
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
    out: Path = typer.Option(None, "--out", help="Write an Anki CSV here."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report the plan without calling the API."
    ),
    limit: int = typer.Option(None, "--limit", help="Only process N chunks."),
    no_dedupe: bool = typer.Option(
        False, "--no-dedupe", help="Skip near-duplicate removal."
    ),
) -> None:
    """Turn a directory of notes into flashcards."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    if dry_run:
        chunks = pipeline.collect_chunks(source, settings)[:limit]
        tokens = sum(estimate_tokens(chunk.text) for chunk in chunks)
        typer.echo(f"chunks: {len(chunks)}")
        typer.echo(f"estimated requests: {len(chunks)} (before any retries)")
        typer.echo(f"estimated prompt tokens: ~{tokens} (4 chars/token, not exact)")
        typer.echo("requests made: 0")
        return

    result = pipeline.run(source, settings, GeminiClient(settings), limit=limit)
    entries = result.cards
    duplicates = 0

    if not no_dedupe and entries:
        try:
            entries, dropped = dedupe.deduplicate(
                entries, settings.similarity_threshold, settings.embedding_model
            )
            duplicates = len(dropped)
        except dedupe.DedupeUnavailable as exc:
            typer.secho(f"dedupe skipped: {exc}", fg=typer.colors.YELLOW)

    for position, entry in enumerate(entries, start=1):
        card = entry.card
        typer.secho(f"\n[{position}] {card.question}", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"    {card.answer}")
        typer.echo(f"    topic={card.topic}  difficulty={card.difficulty}")

    for failure in result.failures:
        typer.secho(f"chunk failed: {failure}", fg=typer.colors.RED)

    if out is not None:
        written = exporter.write_csv(entries, out)
        typer.echo(f"\nwrote {written} cards to {out}")

    typer.echo(
        f"\nchunks: {len(result.chunks)}   cards: {len(entries)}   "
        f"dropped: {result.dropped}   duplicates: {duplicates}   "
        f"requests: {result.requests}   cached: {result.cache_hits}"
    )


# `benchmark` lands in Phase F.

if __name__ == "__main__":
    app()
