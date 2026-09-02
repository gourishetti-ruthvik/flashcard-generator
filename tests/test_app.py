from __future__ import annotations

import csv
import json
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


def last(generator) -> tuple[str, str, str, Any]:
    """Drain a Gradio generator handler and keep only its final yield."""
    return deque(generator, maxlen=1)[0]


@pytest.fixture(autouse=True)
def _wire_app(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "GeminiClient", lambda _: FakeClient())


def _quota_error(quota_id: str) -> errors.APIError:
    return errors.APIError(
        429,
        {
            "error": {
                "code": 429,
                "message": "You exceeded your current quota",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": quota_id, "quotaValue": "20"}],
                    }
                ],
            }
        },
    )


DAILY = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"


# --- input gathering -------------------------------------------------------


def test_pasted_text_becomes_chunks(settings: Settings) -> None:
    chunks = app.gather_chunks(NOTES, None, settings)
    assert len(chunks) == 1
    assert chunks[0].heading == "Tokenization"
    assert chunks[0].source_path.stem == "pasted"


def test_uploaded_file_becomes_chunks(settings: Settings, tmp_path: Path) -> None:
    note = tmp_path / "lecture.md"
    note.write_text(NOTES, encoding="utf-8")
    chunks = app.gather_chunks("", [str(note)], settings)
    assert chunks and chunks[0].source_path.stem == "lecture"


def test_paste_and_upload_combine(settings: Settings, tmp_path: Path) -> None:
    note = tmp_path / "lecture.md"
    note.write_text("# Other\n\nSomething else entirely here.", encoding="utf-8")
    assert len(app.gather_chunks(NOTES, [str(note)], settings)) == 2


def test_blank_paste_is_ignored(settings: Settings) -> None:
    assert app.gather_chunks("   ", None, settings) == []


# --- the daily ration ------------------------------------------------------


def test_ration_starts_empty(settings: Settings) -> None:
    assert app.read_spent(settings) == 0


def test_ration_accumulates_within_a_day(settings: Settings) -> None:
    app.add_spent(settings, 3)
    assert app.add_spent(settings, 2) == 5
    assert app.read_spent(settings) == 5


def test_ration_is_keyed_by_pacific_day(settings: Settings) -> None:
    """Google's cap rolls over at midnight US Pacific, not local midnight.

    Keying on the local date would reset the strip hours early or late and make
    it lie about what is left.
    """
    app.add_spent(settings, 4)
    stored = json.loads(app._usage_file(settings).read_text(encoding="utf-8"))
    assert list(stored) == [app.quota_day()]


def test_a_corrupt_counter_reads_as_zero(settings: Settings) -> None:
    # The ration is an aid; refusing to render the page over an unparsable
    # counter would be worse than briefly under-reporting.
    app._usage_file(settings).parent.mkdir(parents=True, exist_ok=True)
    app._usage_file(settings).write_text("{not json", encoding="utf-8")
    assert app.read_spent(settings) == 0


def test_ration_strip_marks_what_is_spent() -> None:
    assert app.ticks_html(0).count("background:") == 0
    assert app.ticks_html(7).count("background:") == 7
    assert app.ticks_html(app.DAILY_CAP).count("background:") == app.DAILY_CAP


def test_header_counts_down_what_is_left() -> None:
    assert ">13</b> of 20 left" in app.header_html(7)
    assert "none left" in app.header_html(app.DAILY_CAP)


def test_cached_replies_do_not_move_the_ration(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """A cache hit consumes no quota, so it must not fill a tick."""

    class Cached(FakeClient):
        def generate_cards(self, prompt: str) -> list[Flashcard]:
            self.request_count += 1
            self.cache_hits += 1
            return [_card()]

    monkeypatch.setattr(app, "GeminiClient", lambda _: Cached())
    last(app.generate(NOTES, None, 5, False))
    assert app.read_spent(settings) == 0


def test_real_calls_do_move_the_ration(settings: Settings) -> None:
    last(app.generate(NOTES, None, 5, False))
    assert app.read_spent(settings) == 1


# --- rendering -------------------------------------------------------------


@pytest.mark.parametrize(
    ("difficulty", "filled"), [("easy", 1), ("medium", 2), ("hard", 3)]
)
def test_difficulty_fills_one_mark_per_level(difficulty: str, filled: int) -> None:
    # The count carries the level, so it survives greyscale and colour blindness.
    assert app.dtag(difficulty).count("background:var(") == filled


def test_difficulty_labels_the_level() -> None:
    assert "hard</span>" in app.dtag("hard")


def test_cards_escape_model_output() -> None:
    # Questions and answers come from the model and are injected into HTML.
    nasty = _sourced(_card(question="<script>alert(1)</script>"))
    rendered = app.render_cards([nasty])
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_render_cards_is_empty_for_no_cards() -> None:
    assert app.render_cards([]) == ""


def test_summary_reports_the_run() -> None:
    summary = app.render_summary(3, 1, 0, 1, 0, 1)
    assert "3</b> cards" in summary
    assert "1</b> chunk<" in summary  # singular for one chunk
    assert "dropped 0" in summary and "1</b> duplicates" in summary


def test_card_carries_the_difficulty_colour() -> None:
    entry = _sourced(_card(difficulty="hard"))
    assert "var(--hard)" in app.render_cards([entry])


def test_estimate_reports_counts_and_costs_nothing() -> None:
    estimate = app.render_estimate(2, 480, 5, spent=0)
    assert "2 chunks" in estimate and "480 tokens" in estimate
    assert "nothing spent" in estimate


def test_estimate_prices_the_run_against_what_is_left() -> None:
    assert "That is 4 of the 13 you have left today." in app.render_estimate(
        4, 900, 5, spent=7
    )


def test_estimate_warns_when_the_run_will_not_fit() -> None:
    # Better to say so before the run than to fail halfway through it.
    estimate = app.render_estimate(9, 2000, 5, spent=17)
    assert "more than the 3 you have left" in estimate


# --- preview ---------------------------------------------------------------


def test_preview_reports_chunks_and_spends_nothing() -> None:
    status, _ = app.preview(NOTES, None, 5)
    assert "Estimate" in status and "nothing spent" in status


def test_preview_never_builds_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(_: object) -> None:
        raise AssertionError("preview must not touch the API")

    monkeypatch.setattr(app, "GeminiClient", explode)
    status, _ = app.preview(NOTES, None, 5)
    assert "Estimate" in status


def test_preview_prices_the_generate_button() -> None:
    # The cost rides on the button itself so Generate is a considered act.
    _, button = app.preview(NOTES, None, 5)
    assert "spends 1 of your 20" in button["value"]


def test_preview_on_empty_input_is_friendly() -> None:
    status, _ = app.preview("", None, 5)
    assert "Nothing to do" in status


# --- generate --------------------------------------------------------------


def test_generate_returns_cards_summary_and_csv() -> None:
    _, status, cards_html, download = last(app.generate(NOTES, None, 5, False))

    assert "What is tokenization?" in cards_html
    assert "1</b> cards" in status and "1</b> chunk" in status
    assert download["visible"] is True
    assert Path(download["value"]).exists()


def test_generate_streams_progress_before_finishing() -> None:
    frames = list(app.generate(NOTES, None, 5, False))
    # A dead spinner was the thing to avoid: the ledger must appear first.
    assert len(frames) > 1
    assert "Progress" in frames[0][1]
    assert "Tokenization" in frames[0][1]


def test_generate_refreshes_the_ration_as_it_runs() -> None:
    frames = list(app.generate(NOTES, None, 5, False))
    assert "Daily ration" in frames[0][0]


def test_the_rate_limit_pause_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dead air only reads as broken when nothing on the page accounts for it.

    At five a minute a longer run visibly stalls, so the wait is labelled
    rather than hidden behind a spinner.
    """
    long_notes = "\n\n".join(f"# H{n}\n\nBody number {n} here." for n in range(7))
    frames = [f[1] for f in app.generate(long_notes, None, 7, False)]
    assert any("Waiting for the 5-a-minute limit" in f for f in frames)
    assert any("This pause is the rate limiter, not a stall" in f for f in frames)


def test_csv_is_importable() -> None:
    _, _, _, download = last(app.generate(NOTES, None, 5, False))
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
    _, status, cards_html, download = last(app.generate(NOTES, None, 5, True))

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
    _, status, cards_html, _ = last(app.generate(NOTES, None, 5, True))

    assert "1</b> duplicates" in status
    assert "Second?" not in cards_html


def test_dedupe_short_circuits_on_a_single_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_: object, **__: object) -> None:
        raise AssertionError("dedupe should not run for a single card")

    monkeypatch.setattr(app.dedupe, "load_encoder", explode)
    _, status, _, _ = last(app.generate(NOTES, None, 5, True))
    assert "Dedupe skipped" not in status


def test_rate_limit_error_becomes_a_readable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Limited(FakeClient):
        def generate_cards(self, prompt: str) -> list[Flashcard]:
            raise _quota_error("GenerateRequestsPerMinutePerProjectPerModel-FreeTier")

    monkeypatch.setattr(app, "GeminiClient", lambda _: Limited())
    _, status, cards_html, download = last(app.generate(NOTES, None, 5, False))

    assert "Rate limited" in status and "HTTP 429" in status
    assert "Lower Max chunks" in status  # the recovery steps are shown
    assert cards_html == ""
    assert download["visible"] is False


def test_the_daily_cap_gets_its_own_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hitting the cap is a weekly event on this tier, not a fault.

    So it says what still works instead of rendering as a red error box.
    """

    class Exhausted(FakeClient):
        def generate_cards(self, prompt: str) -> list[Flashcard]:
            raise _quota_error(DAILY)

    monkeypatch.setattr(app, "GeminiClient", lambda _: Exhausted())
    _, status, _, download = last(app.generate(NOTES, None, 5, False))

    assert "That is today" in status and "twenty" in status
    assert "Preview keeps working" in status
    assert "Rate limited" not in status
    assert download["visible"] is False


def test_missing_secret_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def unconfigured() -> Settings:
        raise ConfigError("GEMINI_API_KEY is not set")

    monkeypatch.setattr(app, "load_settings", unconfigured)
    _, status, cards_html, download = last(app.generate(NOTES, None, 5, False))

    assert "No API key" in status
    assert ".env" in status
    assert cards_html == ""
    assert download["visible"] is False


def test_generate_on_empty_input_is_friendly() -> None:
    _, status, cards_html, download = last(app.generate("", None, 5, False))
    assert "Nothing to do" in status
    assert cards_html == ""
    assert download["visible"] is False


def test_summary_sets_colour_on_every_text_span() -> None:
    # Gradio ships a dark theme; any span of ours without an explicit colour
    # inherits near-white and vanishes on the paper ground.
    summary = app.render_summary(12, 3, 0, 1, 0, 3)
    for span in summary.split("<span")[1:]:
        assert "color:" in span.split(">")[0]


# --- the card --------------------------------------------------------------


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


def test_cards_size_to_their_content() -> None:
    """Faces stack in a grid cell, not absolutely.

    A fixed height clipped long answers and left short ones swimming, so the
    two faces share one grid area and the taller wins.
    """
    assert "grid-area:1/1" in app.CSS
    assert "position:absolute" not in app.CSS.split(".fc-face")[1].split("}")[0]


def test_entrance_is_staggered_then_capped() -> None:
    entries = [_sourced(_card(question=f"Q{n}")) for n in range(14)]
    rendered = app.render_cards(entries)
    assert "animation-delay:0ms" in rendered
    assert "animation-delay:42ms" in rendered
    # Capped so the last card of a long run does not wait half a second.
    assert "animation-delay:462ms" in rendered
    assert "animation-delay:504ms" not in rendered


def test_entrance_animation_does_not_pin_the_hover_lift() -> None:
    # animation-fill-mode: both keeps the final keyframe's `transform: none`
    # applied forever, and an animated value outranks a normal one, so
    # `.fc:hover { transform: translateY(-3px) }` never took effect.
    assert "cubic-bezier(.2,.8,.2,1) backwards" in app.CSS
    assert "cubic-bezier(.2,.8,.2,1) both" not in app.CSS
    assert ".fc:hover .fc-inner{transform:translateY(-3px)}" in app.CSS


# --- palette ---------------------------------------------------------------


def _tokens(block: str) -> dict[str, str]:
    pairs = (part.split(":", 1) for part in block.split(";") if part.strip())
    return {name.strip(): value.strip() for name, value in pairs}


LIGHT = _tokens(app.LIGHT_TOKENS)
DARK = _tokens(app.DARK_TOKENS)
PALETTES = [pytest.param(LIGHT, id="light"), pytest.param(DARK, id="dark")]


def _luminance(colour: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(foreground: str, background: str) -> float:
    a, b = _luminance(foreground), _luminance(background)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _hue(colour: str) -> float:
    import colorsys

    r, g, b = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[0] * 360


def test_dark_defines_every_token_light_does() -> None:
    # A token defined in one mode only falls back silently to whatever the other
    # mode left behind, which is how half-themed pages happen.
    assert set(LIGHT) == set(DARK)


@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("level", ["--easy", "--med", "--hard"])
def test_difficulty_colour_clears_wcag_aa(palette: dict, level: str) -> None:
    # The label sits at 9.5px, so AA for normal text is the bar. An earlier
    # medium sat at 2.89 and was genuinely hard to read.
    assert _contrast(palette[level], palette["--paper2"]) >= 4.5


@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("token", ["--ink", "--ink2", "--mute", "--blue", "--oranget"])
def test_text_colours_clear_wcag_aa(palette: dict, token: str) -> None:
    assert _contrast(palette[token], palette["--paper2"]) >= 4.5


@pytest.mark.parametrize("palette", PALETTES)
def test_knockout_text_clears_aa_on_its_block(palette: dict) -> None:
    # Paper-coloured text on the spot blue, which is its own contrast problem.
    assert _contrast(palette["--knockfg"], palette["--blue"]) >= 4.5


@pytest.mark.parametrize("palette", PALETTES)
def test_difficulty_levels_are_distinguishable_by_hue(palette: dict) -> None:
    # easy and hard were once three degrees apart, which is the same colour to
    # the eye. The marks carry the level, but colour should not actively mislead.
    hues = [_hue(palette[level]) for level in ("--easy", "--med", "--hard")]
    assert abs(hues[0] - hues[1]) >= 20
    assert abs(hues[1] - hues[2]) >= 20


@pytest.mark.parametrize("palette", PALETTES)
def test_action_colour_is_not_a_difficulty_colour(palette: dict) -> None:
    # Otherwise a card's difficulty mark reads as a button.
    levels = [palette[level] for level in ("--easy", "--med", "--hard")]
    assert palette["--blue"] not in levels
    assert min(abs(_hue(palette["--blue"]) - _hue(c)) for c in levels) >= 40


# --- ground and motion -----------------------------------------------------


def test_ground_layers_are_present_and_behind_the_page() -> None:
    for layer in ("bloom b1", "bloom b2", "grain"):
        assert layer in app.GROUND
    assert "#ground" in app.CSS and "z-index:0" in app.CSS
    # A solid container background would paint straight over the fixed layer.
    assert "background:transparent !important" in app.CSS


def test_the_ground_paints_its_own_paper() -> None:
    # The grain multiplies. Over a transparent layer that turned the page black.
    ground = app.CSS.split("#ground{")[1].split("}")[0]
    assert "background:var(--paper)" in ground


def test_every_animation_is_dropped_under_reduced_motion() -> None:
    blocks = "".join(app.CSS.split("prefers-reduced-motion")[1:])
    for selector in ("#ground .bloom", ".fc,.fc-inner", "#genbtn"):
        assert selector in blocks


# --- light and dark switching ----------------------------------------------


def test_the_mode_switch_needs_no_javascript() -> None:
    # Gradio gives no client-side state, so the toggle is two radios and
    # :has(). A JS toggle would simply not have been buildable here.
    header = app.header_html(0)
    assert '<input type="radio" name="fcmode" id="m-light">' in header
    assert '<input type="radio" name="fcmode" id="m-dark">' in header
    assert "<script" not in header
    assert "body:has(#m-dark:checked)" in app.CSS


def test_the_mode_radios_are_taken_out_of_the_layout() -> None:
    """They rendered as three visible dots above the title.

    Gradio's own input styling overrides the `hidden` attribute, so they have
    to be positioned out of flow instead. Not display:none -- that stops the
    label activating them in some browsers.
    """
    rule = app.CSS.split("#m-light,#m-dark{")[1].split("}")[0]
    assert "position:absolute" in rule and "opacity:0" in rule
    assert "display:none" not in rule


def test_untouched_toggle_follows_the_operating_system() -> None:
    # Absence of a choice means auto, rather than a third radio carrying a
    # `checked` attribute that Gradio may drop when it re-renders the block.
    assert "m-auto" not in app.CSS and "m-auto" not in app.header_html(0)
    assert (
        "body:not(:has(#m-light:checked)):not(:has(#m-dark:checked))" in app.CSS
    )


def test_an_explicit_choice_outranks_the_system_preference() -> None:
    # Same specificity, so the explicit rules must be declared after the media
    # query or clicking "light" on a dark OS would do nothing.
    css = app.CSS
    assert css.index("@media (prefers-color-scheme: dark)") < css.index(
        "body:has(#m-light:checked){"
    )


# --- the Max chunks field --------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 5), ("", 5), ("abc", 5), (0, 1), (-3, 1), (4.7, 4), (12, 12), ("8", 8)],
)
def test_chunk_limit_survives_whatever_the_number_box_sends(
    value: object, expected: int
) -> None:
    """Clearing the box sends None and int() raised on it.

    That surfaced as a bare "Error" in the results column with nothing to act
    on. Zero or a negative would also slice the chunk list from the wrong end
    and silently drop work.
    """
    assert app.chunk_limit(value) == expected


@pytest.mark.parametrize("value", [None, "", "abc", 0, -3])
def test_a_cleared_max_chunks_still_previews(value: object) -> None:
    status, _ = app.preview(NOTES, None, value)
    assert "Estimate" in status


@pytest.mark.parametrize("value", [None, "", 0])
def test_a_cleared_max_chunks_still_generates(value: object) -> None:
    _, status, cards_html, download = last(app.generate(NOTES, None, value, False))
    assert "What is tokenization?" in cards_html
    assert download["visible"] is True


def test_the_header_wraps_on_a_phone() -> None:
    """At 375px the twenty-tick ration ran off the right edge, clipping the
    counter. The header carries inline styles, so only !important reaches it."""
    mobile = app.CSS.split("@media (max-width:900px)")[1].split("\n}")[0]
    assert ".hd{flex-direction:column !important" in mobile
    assert ".ticks{justify-content:flex-start !important}" in mobile
    assert 'class="hd"' in app.header_html(0)
    assert 'class="ration"' in app.header_html(0)
    assert 'class="ticks"' in app.header_html(0)


def test_the_header_cluster_wraps_before_it_clips() -> None:
    """At ~1000px the dark pill was cut off rather than wrapping.

    The page did not scroll, so nothing signalled that a control had gone
    missing -- it simply was not there.
    """
    assert ".hd{flex-wrap:wrap}" in app.CSS
    # Split on the base rule, not the first ".meta{" -- that one is the mobile
    # override inside the media query and asserting against it proves nothing.
    base = app.CSS.split(".meta{display:flex")[1].split("}")[0]
    assert "flex-wrap:wrap" in base
    assert "margin-left:auto" in base  # keeps it right-aligned once wrapped
