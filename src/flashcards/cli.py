from __future__ import annotations

from pathlib import Path

import typer

from flashcards import __version__, benchmark as benchmark_mod, dedupe, exporter, pipeline
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

    result = pipeline.run(
        pipeline.collect_chunks(source, settings),
        settings,
        GeminiClient(settings),
        limit=limit,
    )
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


@app.command()
def benchmark(
    source: Path = typer.Argument(..., exists=True, help="Note file or directory."),
    limit: int = typer.Option(None, "--limit", help="Only use N chunks."),
    repeats: int = typer.Option(1, "--repeats", help="Passes over each arm."),
    results: Path = typer.Option(
        Path("benchmark-results.jsonl"),
        "--results",
        help="Append each call's outcome here as it happens.",
    ),
    resume: bool = typer.Option(
        False, "--resume", help="Skip calls already recorded in --results."
    ),
    quota_stop: int = typer.Option(
        6, "--quota-stop", help="Give up after this many consecutive API errors."
    ),
    max_attempts: int = typer.Option(
        2, "--max-attempts", help="Attempts per call before recording an error."
    ),
) -> None:
    """Compare JSON mode against prompt-based JSON instructions."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    # Each retry is itself a request against the same quota. The rate limiter
    # already paces the per-minute ceiling, so a 429 here usually means the
    # daily cap, which no amount of backoff will clear -- three extra attempts
    # just spend three more requests to learn what the first one said.
    settings = settings.model_copy(update={"max_attempts": max_attempts})

    chunks = pipeline.collect_chunks(source, settings)[:limit]
    if not chunks:
        typer.secho("no chunks found", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    # Appending to a stale file would silently mix two runs' numbers, and
    # truncating it would throw away calls that cost real quota. Neither is a
    # decision to make on the user's behalf.
    if results.exists() and results.stat().st_size and not resume:
        typer.secho(
            f"{results} already holds results. Pass --resume to continue that "
            "run, or delete the file to start over.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    done = len(benchmark_mod.load_records(results)) if resume else 0
    calls = len(chunks) * 2 * repeats
    typer.echo(f"{len(chunks)} chunks x 2 arms x {repeats} = {calls} uncached calls")
    if done:
        typer.echo(f"resuming: {done} already recorded, {calls - done} to go")
    typer.echo("")

    def show(record: dict) -> None:
        if record.get("event") == "stopped":
            typer.secho(
                f"stopped after {record['after']} consecutive API errors -- "
                f"rerun with --resume to pick up where this left off",
                fg=typer.colors.YELLOW,
            )
            return
        mark, colour = ("ok", typer.colors.GREEN) if record["ok"] else (
            record["kind"], typer.colors.RED
        )
        tail = (
            f"{record['latency']:.2f}s  {record['cards']} cards"
            if record["ok"]
            else str(record.get("detail", ""))[:60]
        )
        typer.secho(
            f"  {record['arm']:<7}{record['chunk']:<28}#{record['repeat']} "
            f"{mark:<6}{tail}",
            fg=colour,
        )

    client = GeminiClient(settings)
    arms = benchmark_mod.run(
        chunks,
        settings,
        client,
        repeats=repeats,
        results_path=results,
        progress=show,
        quota_stop=quota_stop,
    )
    typer.echo("")

    typer.echo(f"{'arm':<32}{'runs':>6}{'failed':>8}{'rate':>8}{'mean latency':>15}")
    typer.echo("-" * 69)
    for arm in arms:
        typer.echo(
            f"{arm.name:<32}{arm.runs:>6}{len(arm.failures):>8}"
            f"{arm.failure_rate:>7.0%}{arm.mean_latency:>14.2f}s"
        )

    for arm in arms:
        for failure in arm.failures:
            typer.secho(f"{arm.name}: {failure}", fg=typer.colors.RED)

    typer.echo(f"\ncards produced: {' / '.join(str(a.cards) for a in arms)}")
    # Without this the control arm's failure rate reads as "the model always
    # returned clean JSON" when it may mean the harness cleaned up after it.
    prompt_arm = arms[1]
    typer.echo(
        f"code fences stripped: {prompt_arm.fenced} of {prompt_arm.runs} "
        "prompt-based replies"
    )
    typer.echo(f"requests: {client.request_count}")


if __name__ == "__main__":
    app()
