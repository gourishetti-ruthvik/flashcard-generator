from __future__ import annotations

import csv
from collections import deque
from pathlib import Path
from typing import Any

import pytest
from google.genai import errors

import app
from flashcards.config import ConfigError, Settings
from flashcards.models import Flashcard, SourcedCard

NOTES = "# Tokenization\n\nTokenization splits text into smaller units."


def _card(question: str = "What is tokenization?", **kwargs: Any) -> Flashcard:
    return Flashcard(
        question=question,
        answer=kwargs.get("answer", "Splitting text into smaller units called tokens."),
        topic=kwargs.get("topic", "Natural Language Processing"),
        difficulty=kwargs.get("difficulty", "easy"),
    )


def _sourced(card: Flashcard) -> SourcedCard:
    return SourcedCard(card=card, source="pasted")


class FakeClient:
    def __init__(self, cards: list[Flashcard] | None = None) -> None:
        self._cards = cards if cards is not None else [_card()]
        self.request_count = 0
        self.cache_hits = 0

    def generate_cards(self, prompt: str) -> list[Flashcard]:
        self.request_count += 1
        return list(self._cards)


def last(generator) -> tuple[str, str, Any]:
    """Drain a Gradio generator handler and keep only its final yield."""
    return deque(generator, maxlen=1)[0]


@pytest.fixture(autouse=True)
def _wire_app(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "GeminiClient", lambda _: FakeClient())


# --- input gathering -------------------------------------------------------


def test_pasted_text_becomes_chunks(settings: Settings) -> None:
    chunks = app.gather_chunks(NOTES, None, settings)
    assert len(chunks) == 1
    assert chunks[0].heading == "Tokenization"
    assert chunks[0].source_path.stem == "pasted"


def test_uploaded_files_are_read(tmp_path: Path, settings: Settings) -> None:
    note = tmp_path / "embeddings.md"
    note.write_text("# Embeddings\n\nVectors for words.", encoding="utf-8")
    chunks = app.gather_chunks("", [str(note)], settings)
    # The filename becomes the source tag, so cards stay traceable in Anki.
    assert chunks[0].source_path.stem == "embeddings"


def test_text_and_files_combine(tmp_path: Path, settings: Settings) -> None:
    note = tmp_path / "extra.md"
    note.write_text("# Extra\n\nMore body text.", encoding="utf-8")
    chunks = app.gather_chunks(NOTES, [str(note)], settings)
    assert {c.source_path.stem for c in chunks} == {"pasted", "extra"}


def test_blank_input_yields_nothing(settings: Settings) -> None:
    assert app.gather_chunks("   ", None, settings) == []


# --- rendering -------------------------------------------------------------


@pytest.mark.parametrize(
    ("difficulty", "filled"),
    [("easy", 1), ("medium", 2), ("hard", 3)],
)
def test_meter_fills_one_bar_per_level(difficulty: str, filled: int) -> None:
    # The filled-square count carries the level, so it survives greyscale and
    # colour blindness. The card's margin rule is what carries the colour.
    assert app.meter(difficulty).count(f"background:{app.INK}") == filled


def test_meter_labels_the_level() -> None:
    assert ">hard<" in app.meter("hard")


def test_cards_escape_model_output() -> None:
    # Questions and answers come from the model and are injected into HTML.
    nasty = _sourced(_card(question="<script>alert(1)</script>"))
    rendered = app.render_cards([nasty])
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_render_cards_is_empty_for_no_cards() -> None:
    assert app.render_cards([]) == ""


def test_summary_matches_the_cli_wording() -> None:
    summary = app.render_summary(3, 1, 0, 1, 0, 1)
    assert "3 cards" in summary
    assert "from 1 chunk<" in summary  # singular for one chunk
    assert "dropped 0" in summary and "duplicates 1" in summary


def test_card_margin_rule_carries_the_difficulty_colour() -> None:
    # Colour lives on the card edge, not in the meter.
    entry = _sourced(_card(difficulty="hard"))
    assert f"border-left:3px solid {app.DIFFICULTY['hard'][0]}" in app.render_cards([entry])


def test_estimate_reports_counts_and_reassurance() -> None:
    estimate = app.render_estimate(2, 480, 5)
    assert ">2<" in estimate and ">480<" in estimate
    assert "No API calls were made." in estimate


# --- preview ---------------------------------------------------------------


def test_preview_reports_chunks_and_spends_nothing() -> None:
    message = app.preview(NOTES, None, 5)
    assert "Estimate" in message
    assert "No API calls were made" in message


def test_preview_never_builds_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(_: object) -> None:
        raise AssertionError("preview must not touch the API")

    monkeypatch.setattr(app, "GeminiClient", explode)
    assert "Estimate" in app.preview(NOTES, None, 5)


def test_preview_on_empty_input_is_friendly() -> None:
    assert "Nothing to work with" in app.preview("", None, 5)


# --- generate --------------------------------------------------------------


def test_generate_returns_cards_summary_and_csv() -> None:
    status, cards_html, download = last(app.generate(NOTES, None, 5, False))

    assert "What is tokenization?" in cards_html
    assert "1 cards" in status and "from 1 chunk" in status
    assert download["visible"] is True
    assert Path(download["value"]).exists()


def test_generate_streams_progress_before_finishing() -> None:
    frames = list(app.generate(NOTES, None, 5, False))
    # A dead spinner was the thing to avoid: the stage list must appear first.
    assert len(frames) > 1
    assert "Progress" in frames[0][0]
    assert "Splitting notes into chunks" in frames[0][0]


def test_csv_is_importable() -> None:
    _, _, download = last(app.generate(NOTES, None, 5, False))
    with Path(download["value"]).open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.reader(handle) if not row[0].startswith("#")]
    assert rows[0][0] == "What is tokenization?"
    assert rows[0][2] == "Natural_Language_Processing easy pasted"


def test_limit_caps_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(app, "GeminiClient", lambda _: client)
    long_notes = "\n\n".join(f"# H{n}\n\nBody number {n} here." for n in range(5))
    last(app.generate(long_notes, None, 2, False))
    assert client.request_count == 2


def _two_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        app, "GeminiClient", lambda _: FakeClient([_card("First?"), _card("Second?")])
    )


def test_missing_dedupe_extra_is_reported_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _two_cards(monkeypatch)

    def unavailable(*_: object, **__: object) -> None:
        raise app.dedupe.DedupeUnavailable("sentence-transformers is not installed")

    monkeypatch.setattr(app.dedupe, "deduplicate", unavailable)
    status, cards_html, download = last(app.generate(NOTES, None, 5, True))

    assert "First?" in cards_html and "Second?" in cards_html
    assert "Dedupe skipped" in status
    assert download["visible"] is True


def test_duplicates_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    # The encoder is stubbed rather than loaded: the real one downloads weights
    # from the HF Hub, and tests must not touch the network.
    _two_cards(monkeypatch)
    monkeypatch.setattr(
        app.dedupe, "deduplicate", lambda entries, *_, **__: ([entries[0]], [entries[1]])
    )
    status, cards_html, _ = last(app.generate(NOTES, None, 5, True))

    assert "duplicates 1" in status
    assert "Second?" not in cards_html


def test_dedupe_short_circuits_on_a_single_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_: object, **__: object) -> None:
        raise AssertionError("dedupe should not run for a single card")

    monkeypatch.setattr(app.dedupe, "load_encoder", explode)
    status, _, _ = last(app.generate(NOTES, None, 5, True))
    assert "Dedupe skipped" not in status


def test_quota_error_becomes_a_readable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Exhausted(FakeClient):
        def generate_cards(self, prompt: str) -> list[Flashcard]:
            raise errors.ClientError(429, {"error": {"message": "quota"}})

    monkeypatch.setattr(app, "GeminiClient", lambda _: Exhausted())
    status, cards_html, download = last(app.generate(NOTES, None, 5, False))

    assert "Out of quota" in status and "HTTP 429" in status
    assert "Lower Max chunks" in status  # the recovery steps are shown
    assert cards_html == ""
    assert download["visible"] is False


def test_missing_secret_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def unconfigured() -> Settings:
        raise ConfigError("GEMINI_API_KEY is not set")

    monkeypatch.setattr(app, "load_settings", unconfigured)
    status, cards_html, download = last(app.generate(NOTES, None, 5, False))

    assert "No API key" in status
    assert ".env" in status
    assert cards_html == ""
    assert download["visible"] is False


def test_generate_on_empty_input_is_friendly() -> None:
    status, cards_html, download = last(app.generate("", None, 5, False))
    assert "Nothing to work with" in status
    assert cards_html == ""
    assert download["visible"] is False


def test_step_counter_tracks_the_active_stage() -> None:
    # A hand-maintained counter drifted and reported "step 1 of 4" while stage 2
    # was running, so the number is derived from the stage list instead.
    stages = [
        ["done", "a", "", ""],
        ["active", "b", "", ""],
        ["pending", "c", "", ""],
    ]
    assert app.active_step(stages) == 2
    stages[1][0], stages[2][0] = "done", "active"
    assert app.active_step(stages) == 3
    stages[2][0] = "done"
    assert app.active_step(stages) == 3  # all done: report the last stage


def test_generating_frame_reports_step_two_of_four() -> None:
    frames = [f[0] for f in app.generate(NOTES, None, 5, True)]
    generating = next(f for f in frames if "Generating cards" in f and "step" in f)
    assert "step 2 of 4" in generating


def test_summary_sets_colour_on_every_text_span() -> None:
    # Gradio ships a dark theme; any span of ours without an explicit colour
    # inherits near-white and vanishes on the paper ground.
    summary = app.render_summary(12, 3, 0, 1, 0, 3)
    for span in summary.split("<span")[1:]:
        assert "color:" in span.split(">")[0]


def test_card_has_both_faces() -> None:
    entry = _sourced(_card(question="Q?", answer="A long enough answer here."))
    rendered = app.render_cards([entry])
    assert rendered.count("fc-face") == 2       # front and back
    assert "fc-back" in rendered
    assert "Q?" in rendered and "A long enough answer here." in rendered


def test_flip_is_driven_by_a_checkbox_not_javascript() -> None:
    # Keyboard users get the flip for free this way, and there is no script to
    # break inside Gradio's rendering.
    rendered = app.render_cards([_sourced(_card())])
    assert '<input type="checkbox">' in rendered
    assert "<script" not in rendered


def test_answer_lives_on_the_back_face() -> None:
    entry = _sourced(_card(question="Front side", answer="Back side text."))
    front, back = app.render_cards([entry]).split("fc-back")
    assert "Front side" in front and "Back side text." not in front
    assert "Back side text." in back


def test_entrance_is_staggered_then_capped() -> None:
    entries = [_sourced(_card(question=f"Q{n}")) for n in range(14)]
    rendered = app.render_cards(entries)
    assert "animation-delay:0ms" in rendered
    assert "animation-delay:45ms" in rendered
    # Capped so the last card of a long run does not wait half a second.
    assert "animation-delay:495ms" in rendered
    assert "animation-delay:540ms" not in rendered
