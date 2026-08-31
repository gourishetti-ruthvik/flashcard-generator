"""Gradio front end. Deployed to Hugging Face Spaces, used from a phone.

The API key lives in a Space Secret and stays server-side, so it never reaches
the device. All real work is done by the same package the CLI uses.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import gradio as gr
from google.genai import errors

from flashcards import dedupe, exporter, pipeline
from flashcards.chunker import estimate_tokens
from flashcards.client import GeminiClient
from flashcards.config import ConfigError, Settings, load_settings
from flashcards.models import Chunk

COLUMNS = ["Question", "Answer", "Topic", "Difficulty"]


def gather_chunks(
    notes_text: str, files: list[str] | None, settings: Settings
) -> list[Chunk]:
    chunks: list[Chunk] = []

    if notes_text and notes_text.strip():
        chunks.extend(pipeline.chunks_from_text(notes_text, settings))

    for item in files or []:
        # Gradio hands back either a path string or an object carrying one,
        # depending on the component's type setting.
        path = Path(getattr(item, "name", item))
        chunks.extend(
            pipeline.chunks_from_text(
                path.read_text(encoding="utf-8"), settings, name=path.stem
            )
        )

    return chunks


def preview(notes_text: str, files: list[str] | None, max_chunks: float) -> str:
    try:
        settings = load_settings()
    except ConfigError as exc:
        return f"**Not configured.** {exc}"

    chunks = gather_chunks(notes_text, files, settings)[: int(max_chunks)]
    if not chunks:
        return "Nothing to do yet — paste some notes or upload a file."

    tokens = sum(estimate_tokens(chunk.text) for chunk in chunks)
    return (
        f"**{len(chunks)} chunks** -> about **{len(chunks)} requests**, "
        f"~{tokens} prompt tokens.\n\n"
        f"No API calls were made. At {settings.requests_per_minute} requests per "
        f"minute, expect roughly "
        f"{max(0, (len(chunks) - settings.requests_per_minute) * 12)}s of waiting."
    )


def generate(
    notes_text: str, files: list[str] | None, max_chunks: float, use_dedupe: bool
) -> tuple[list[list[str]], str, str | None]:
    try:
        settings = load_settings()
    except ConfigError as exc:
        return [], f"**Not configured.** {exc}", None

    chunks = gather_chunks(notes_text, files, settings)
    if not chunks:
        return [], "Nothing to do yet — paste some notes or upload a file.", None

    client = GeminiClient(settings)
    try:
        result = pipeline.run(chunks, settings, client, limit=int(max_chunks))
    except errors.APIError as exc:
        # Quota exhaustion is the expected failure on a free tier, and a stack
        # trace on a phone screen helps nobody.
        return [], f"**API error {exc.code}.** {exc.message}", None

    entries = result.cards
    duplicates = 0
    notice = ""

    if use_dedupe and entries:
        try:
            entries, dropped = dedupe.deduplicate(
                entries, settings.similarity_threshold, settings.embedding_model
            )
            duplicates = len(dropped)
        except dedupe.DedupeUnavailable as exc:
            notice = f"\n\n_Dedupe skipped: {exc}_"

    rows = [
        [e.card.question, e.card.answer, e.card.topic, e.card.difficulty]
        for e in entries
    ]

    csv_path = Path(tempfile.mkdtemp()) / "cards.csv"
    exporter.write_csv(entries, csv_path)

    status = (
        f"**{len(entries)} cards** from {len(result.chunks)} chunks. "
        f"Dropped {result.dropped}, duplicates {duplicates}. "
        f"Requests {result.requests}, cached {result.cache_hits}."
    )
    if result.failures:
        status += "\n\n" + "\n".join(f"- Chunk failed: {f}" for f in result.failures)

    return rows, status + notice, str(csv_path)


with gr.Blocks(title="Flashcard Generator") as demo:
    gr.Markdown(
        "# Flashcard Generator\n"
        "Paste study notes, get Anki-importable cards. "
        "Download the CSV and import it in AnkiDroid."
    )

    notes_input = gr.Textbox(
        label="Notes", lines=10, placeholder="Paste your study notes here..."
    )
    file_input = gr.File(
        label="or upload .md / .txt files",
        file_count="multiple",
        file_types=[".md", ".txt"],
    )

    with gr.Row():
        # The free tier allows only a handful of requests per minute, so the
        # chunk cap is the control that matters most on this page.
        max_chunks = gr.Number(label="Max chunks", value=5, minimum=1, precision=0)
        use_dedupe = gr.Checkbox(label="Remove near-duplicates", value=True)

    with gr.Row():
        preview_button = gr.Button("Preview (free)")
        generate_button = gr.Button("Generate", variant="primary")

    status = gr.Markdown()
    cards = gr.Dataframe(headers=COLUMNS, label="Cards", wrap=True)
    download = gr.File(label="cards.csv")

    preview_button.click(
        preview, inputs=[notes_input, file_input, max_chunks], outputs=status
    )
    generate_button.click(
        generate,
        inputs=[notes_input, file_input, max_chunks, use_dedupe],
        outputs=[cards, status, download],
    )


if __name__ == "__main__":
    # pwa=True makes it installable from the phone's browser rather than just
    # bookmarkable.
    demo.launch(pwa=True)
