from __future__ import annotations

import typer

from flashcards import __version__

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


# `generate` and `benchmark` land in later phases.

if __name__ == "__main__":
    app()
