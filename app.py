"""Gradio web front end, served in a browser.

Ruled Paper: warm paper ground, Newsreader serif, cards drawn as index cards
with a coloured margin rule. Two columns on a desktop window -- the form on the
left, results on the right -- collapsing to one column below 900px.

All real work is done by the same package the CLI uses; the key is read
server-side and never reaches the browser. Everything non-interactive is
rendered as inline-styled HTML rather than Gradio components: it is the only way
to control the layout precisely, and inline styles are immune to Gradio's own
stylesheet.
"""

from __future__ import annotations

import html
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import gradio as gr
from google.genai import errors

from flashcards import dedupe, exporter, pipeline
from flashcards.chunker import estimate_tokens
from flashcards.client import GeminiClient
from flashcards.config import ConfigError, Settings, load_settings
from flashcards.models import Chunk, SourcedCard

# --- design tokens ---------------------------------------------------------

PAPER = "#faf7f2"
CARD_BG = "#fffdfa"
INK = "#23201c"
INK_2 = "#4a443b"
INK_3 = "#6d6559"
RULE = "#d9d2c6"
RULE_2 = "#e6e0d5"
MUTE = "#8c8578"
FAINT = "#a49c8f"
# Difficulty is a sequential ramp, cool to hot, and every step clears WCAG AA
# on the card ground (5.03, 5.32, 7.03). The previous easy and hard were three
# degrees apart in hue -- the same colour to the eye -- and medium sat at 2.89,
# unreadable at the 10.5px label size.
SAGE = "#5b7553"
OCHRE = "#8f6116"
OXBLOOD = "#9c3520"

# Actions are a separate hue entirely, so an "easy" card's edge never reads as a
# button. Blue ink on ruled paper is also what the metaphor wants.
ACCENT = "#2c4a6b"
GREEN = SAGE

# level -> (margin-rule colour, filled squares)
DIFFICULTY = {"easy": (SAGE, 1), "medium": (OCHRE, 2), "hard": (OXBLOOD, 3)}

SERIF = "'Newsreader', Georgia, serif"
MONO = "'IBM Plex Mono', ui-monospace, monospace"

FONTS = (
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
    "&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap"
)

CSS = f"""
@import url('{FONTS}');

body {{
  background: {PAPER} !important;
  font-family: {SERIF} !important;
  margin: 0 !important;
  padding: 0 !important;
}}
/* Padding lives on the container only. Setting it on body as well subtracted
   112px twice and the page came out 1068 wide instead of 1180. */
.gradio-container {{
  background: {PAPER} !important;
  font-family: {SERIF} !important;
  color: {INK} !important;
  box-sizing: border-box !important;
  width: 100% !important;
  max-width: 1180px !important;
  margin: 0 auto !important;
  padding: 0 56px 56px !important;
}}
#upload {{ overflow: hidden !important; }}
footer, .show-api, .built-with {{ display: none !important; }}
.gradio-container .wrap.hide {{ display: none !important; }}

/* Gradio 6 ships a dark zinc theme on its own wrappers, which showed through
   the paper ground as grey boxes round every control. */
#left .block, #left .form, #right .block, #right .form,
#maxchunks, #dedupe {{
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}}

#main {{ gap: 44px !important; align-items: flex-start !important; }}
#left {{
  flex: 0 0 320px !important;
  position: sticky !important;
  top: 24px !important;
  max-height: calc(100vh - 48px) !important;
  overflow-y: auto !important;
}}
#right {{ flex: 1 1 0 !important; min-width: 0 !important; }}
#left > *, #right > * {{ background: transparent !important; border: none !important; }}
#left {{ gap: 0 !important; }}

/* notes */
#notes textarea {{
  background: {CARD_BG} !important;
  border: 1px solid {RULE} !important;
  border-radius: 2px !important;
  color: {INK_2} !important;
  font-family: {SERIF} !important;
  font-size: 14px !important;
  line-height: 1.62 !important;
  padding: 14px 16px !important;
  max-height: 260px !important;
  box-shadow: none !important;
}}
#notes textarea::placeholder {{ color: {FAINT} !important; }}
#notes textarea:focus {{ border-color: {INK_3} !important; outline: none !important; }}
#notes label > span {{ display: none !important; }}

/* upload */
#upload {{
  background: {CARD_BG} !important;
  border: 1px solid {RULE} !important;
  border-radius: 2px !important;
  margin-top: 14px !important;
}}
#upload button, #upload .label-wrap {{
  color: {INK_3} !important;
  font-family: {SERIF} !important;
  font-size: 14px !important;
  font-weight: 400 !important;
  min-height: 46px !important;
}}
#upload, #upload * {{ min-width: 0 !important; max-width: 100% !important; }}

/* controls */
#controls {{ margin-top: 18px !important; gap: 10px !important; }}
#maxchunks label, #dedupe label {{
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  gap: 12px !important;
  width: 100% !important;
  margin: 0 !important;
}}
#dedupe label {{ flex-direction: row-reverse !important; }}
#maxchunks label span, #dedupe label span {{
  color: {INK} !important;
  font-family: {SERIF} !important;
  font-size: 14.5px !important;
  font-weight: 400 !important;
  margin: 0 !important;
}}
#maxchunks input {{
  background: {CARD_BG} !important;
  border: 1px solid {RULE} !important;
  border-radius: 2px !important;
  color: {INK} !important;
  font-family: {MONO} !important;
  font-size: 15px !important;
  height: 38px !important;
  width: 74px !important;
  flex: 0 0 74px !important;
  text-align: center !important;
  padding: 0 !important;
}}
#dedupe input[type="checkbox"] {{
  appearance: none !important; -webkit-appearance: none !important;
  width: 42px !important; height: 24px !important;
  flex: 0 0 42px !important;
  border-radius: 12px !important;
  background: {RULE} !important;
  border: none !important;
  position: relative !important;
  cursor: pointer !important;
  transition: background .15s ease !important;
}}
#dedupe input[type="checkbox"]::after {{
  content: ""; position: absolute; top: 3px; left: 3px;
  width: 18px; height: 18px; border-radius: 9px; background: {CARD_BG};
  transition: transform .15s ease;
}}
#dedupe input[type="checkbox"]:checked {{ background: {ACCENT} !important; }}
#dedupe input[type="checkbox"]:checked::after {{ transform: translateX(18px); }}

/* buttons */
#previewbtn, #genbtn, #dlbtn {{
  font-family: {SERIF} !important;
  border-radius: 2px !important;
  box-shadow: none !important;
  margin-top: 9px !important;
}}
#previewbtn {{
  background: transparent !important;
  border: 1px solid {INK} !important;
  color: {INK} !important;
  min-height: 44px !important;
  font-size: 15px !important;
  font-weight: 400 !important;
}}
#genbtn {{
  background: {INK} !important;
  border: none !important;
  color: {PAPER} !important;
  min-height: 48px !important;
  font-size: 15px !important;
  font-weight: 500 !important;
}}
#dlbtn {{
  background: {ACCENT} !important;
  border: none !important;
  color: {CARD_BG} !important;
  min-height: 44px !important;
  font-family: {MONO} !important;
  font-size: 13px !important;
  letter-spacing: .04em !important;
}}
#genbtn:hover {{ background: #3a352e !important; }}
#dlbtn:hover {{ background: #213952 !important; }}

/* Flip cards. A hidden checkbox inside the label drives a 3D rotation, so the
   whole thing is CSS: no JavaScript, and the card stays keyboard-operable
   because the checkbox keeps focus and space toggles it. */
.fc {{
  display: block;
  height: 296px;
  perspective: 1400px;
  cursor: pointer;
  transition: transform .25s ease;
  animation: fc-in .4s cubic-bezier(.2,.8,.2,1) both;
}}
.fc:hover {{ transform: translateY(-3px); }}
.fc input {{ position: absolute; opacity: 0; width: 0; height: 0; }}
.fc-inner {{
  position: relative; width: 100%; height: 100%;
  transform-style: preserve-3d;
  transition: transform .6s cubic-bezier(.2,.75,.2,1);
}}
.fc input:checked ~ .fc-inner {{ transform: rotateY(180deg); }}
.fc-face {{
  position: absolute; inset: 0;
  backface-visibility: hidden; -webkit-backface-visibility: hidden;
  background: {CARD_BG};
  border: 1px solid {RULE};
  border-radius: 2px;
  padding: 16px 18px;
  display: flex; flex-direction: column; gap: 11px;
  overflow: hidden;
  transition: box-shadow .25s ease;
}}
.fc:hover .fc-face {{ box-shadow: 0 8px 22px rgba(35,32,28,.10); }}
.fc input:focus-visible ~ .fc-inner .fc-face {{
  outline: 2px solid {ACCENT}; outline-offset: 2px;
}}
/* The reverse of an index card is ruled. Line-height matches the rule pitch so
   the answer sits on the lines. */
.fc-back {{
  transform: rotateY(180deg);
  background-image: repeating-linear-gradient(
    {CARD_BG} 0 27px, #ece5d8 27px 28px);
  background-position: 0 52px;
}}
@keyframes fc-in {{
  from {{ opacity: 0; transform: translateY(10px); }}
  to {{ opacity: 1; transform: none; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .fc, .fc-inner, .fc-face {{ transition: none !important; animation: none !important; }}
}}

@media (max-width: 900px) {{
  .gradio-container, body {{ padding: 0 24px 40px !important; }}
  #main {{ flex-direction: column !important; gap: 0 !important; }}
  #left {{ position: static !important; flex: 1 1 auto !important; width: 100% !important;
           max-height: none !important; overflow-y: visible !important; }}
  #right {{ width: 100% !important; padding-top: 30px !important; }}
}}
"""

LBL = (
    f"font-family:{MONO};font-size:10.5px;letter-spacing:.12em;"
    f"text-transform:uppercase;color:{MUTE}"
)


# --- rendering helpers -----------------------------------------------------


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def meter(difficulty: str) -> str:
    """Filled and hollow squares, plus the word.

    The count carries the level, so it survives greyscale and colour blindness.
    The card's margin rule is what carries the colour.
    """
    filled = DIFFICULTY.get(difficulty, (MUTE, 0))[1]
    squares = "".join(
        f'<span style="width:7px;height:7px;background:{INK}"></span>'
        if index < filled
        else '<span style="width:7px;height:7px;border:1px solid #b9b1a3"></span>'
        for index in range(3)
    )
    return (
        f'<div style="display:flex;align-items:center;gap:8px">'
        f'<span style="display:inline-flex;gap:3px">{squares}</span>'
        f'<span style="{LBL};color:{INK}">{_esc(difficulty)}</span></div>'
    )


def header_html() -> str:
    return (
        f'<div style="display:flex;align-items:flex-end;justify-content:space-between;'
        f'padding:34px 0 20px;border-bottom:2px solid {INK};font-family:{SERIF}">'
        f'<div style="display:flex;align-items:baseline;gap:14px">'
        f'<h1 style="margin:0;font-size:34px;font-weight:600;letter-spacing:-0.02em;'
        f'color:{INK}">Flashcards</h1>'
        f'<span style="font-size:16px;color:{INK_3}">notes in, Anki cards out</span></div>'
        f'<span style="font-family:{MONO};font-size:11px;color:{MUTE}">gemini-2.5-flash</span></div>'
    )


def hint_html(rpm: int) -> str:
    return (
        f'<p style="margin:12px 0 0;font-family:{SERIF};font-size:12.5px;line-height:1.5;'
        f'color:{MUTE}">Free tier allows <span style="font-family:{MONO};color:{INK_3}">{rpm}</span> '
        f"requests a minute. Higher values wait between calls.</p>"
    )


def render_estimate(chunks: int, tokens: int, rpm: int) -> str:
    waiting = max(0, (chunks - rpm) * 12)
    cells = "".join(
        f'<div style="display:flex;flex-direction:column;gap:4px">'
        f'<span style="font-size:38px;font-weight:600;line-height:1;letter-spacing:-0.02em;'
        f'color:{INK}">{value}</span><span style="{LBL}">{label}</span></div>'
        for value, label in (
            (chunks, "chunk" if chunks == 1 else "chunks"),
            (chunks, "request" if chunks == 1 else "requests"),
            (tokens, "tokens approx"),
        )
    )
    wait_line = f" About {waiting}s of that is waiting on the rate limit." if waiting else ""
    return (
        f'<div style="font-family:{SERIF}">'
        f'<div style="border:1px solid {RULE};background:{CARD_BG};border-radius:2px;overflow:hidden">'
        f'<div style="padding:16px 20px 0"><span style="{LBL}">Estimate</span></div>'
        f'<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;'
        f'padding:14px 20px 20px">{cells}</div>'
        f'<div style="display:flex;align-items:center;gap:10px;padding:14px 20px;'
        f'background:#f2f5ee;border-top:1px solid #dfe5d8">'
        f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{GREEN}" '
        f'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M20 6L9 17l-5-5"></path></svg>'
        f'<span style="font-size:14px;color:#3f5c3a">No API calls were made.</span></div></div>'
        f'<p style="margin:12px 2px 0;font-size:13px;line-height:1.55;color:{MUTE}">'
        f"Token count is estimated locally at four characters per token, not measured "
        f"by the API.{wait_line}</p></div>"
    )


def render_error(title: str, code: str, detail: str, steps: tuple[str, ...] = ()) -> str:
    code_html = (
        f'<span style="font-family:{MONO};font-size:11px;color:{MUTE}">{_esc(code)}</span>'
        if code
        else ""
    )
    rows = ""
    if steps:
        items = "".join(
            f'<div style="display:flex;align-items:center;gap:14px;min-height:52px;'
            f'padding:10px 4px;border-bottom:1px solid {RULE_2}">'
            f'<span style="font-family:{MONO};font-size:14px;color:{ACCENT};width:16px">{index}</span>'
            f'<span style="font-size:14.5px;color:{INK_2}">{step}</span></div>'
            for index, step in enumerate(steps, 1)
        )
        rows = (
            f'<div style="padding-top:20px"><span style="{LBL}">What you can do</span>'
            f'<div style="padding-top:6px">{items}</div></div>'
        )
    return (
        f'<div style="font-family:{SERIF}">'
        f'<div style="border:1px solid {RULE};border-left:3px solid {ACCENT};background:#fbf0ed;'
        f'border-radius:2px;padding:16px 20px;display:flex;flex-direction:column;gap:7px">'
        f'<div style="display:flex;align-items:baseline;gap:10px">'
        f'<span style="font-size:18px;font-weight:600;color:{INK}">{_esc(title)}</span>{code_html}</div>'
        f'<p style="margin:0;font-size:14.5px;line-height:1.6;color:{INK_2}">{detail}</p>'
        f"</div>{rows}</div>"
    )


_TICK = (
    f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{INK}" '
    'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M20 6L9 17l-5-5"></path></svg>'
)
_RING = (
    f'<span style="width:14px;height:14px;border:2px solid {ACCENT};'
    f'border-right-color:{RULE};border-radius:50%;display:inline-block"></span>'
)
_DOT = (
    f'<span style="width:12px;height:12px;border:1px solid {RULE};'
    'border-radius:50%;display:inline-block"></span>'
)


def render_stages(stages: list[tuple[str, str, str, str]], done: int, total: int) -> str:
    rows = []
    for index, (state, label, sublabel, meta) in enumerate(stages):
        icon = {"done": _TICK, "active": _RING}.get(state, _DOT)
        colour = {"done": INK_2, "active": INK}.get(state, FAINT)
        weight = "500" if state == "active" else "400"
        background = CARD_BG if state == "active" else "transparent"
        top = f"border-top:1px solid {RULE_2};" if index == 0 else ""
        sub = (
            f'<span style="font-size:12.5px;color:{INK_3}">{_esc(sublabel)}</span>'
            if sublabel and state == "active"
            else ""
        )
        rows.append(
            f'<div style="display:flex;align-items:center;gap:14px;min-height:54px;'
            f'padding:10px 18px;background:{background};'
            f'border-bottom:1px solid {RULE_2};{top}">'
            f'<span style="width:16px;display:flex;justify-content:center">{icon}</span>'
            f'<div style="display:flex;flex-direction:column;gap:2px;flex-grow:1">'
            f'<span style="font-size:15px;font-weight:{weight};color:{colour}">{_esc(label)}</span>'
            f"{sub}</div>"
            f'<span style="font-family:{MONO};font-size:11.5px;color:{MUTE}">{_esc(meta)}</span></div>'
        )
    pct = int(100 * done / total) if total else 0
    return (
        f'<div style="font-family:{SERIF}">'
        f'<div style="display:flex;align-items:baseline;justify-content:space-between;'
        f'padding-bottom:12px"><span style="{LBL}">Progress</span>'
        f'<span style="font-family:{MONO};font-size:11.5px;color:{INK_3}">'
        f"step {done} of {total}</span></div>"
        f'<div style="height:3px;background:{RULE};display:flex">'
        f'<div style="width:{pct}%;background:{ACCENT}"></div></div>'
        f'<div style="padding-top:18px">{"".join(rows)}</div></div>'
    )


def render_summary(
    cards: int, chunks: int, dropped: int, duplicates: int, requests: int, cached: int
) -> str:
    return (
        f'<div style="font-family:{SERIF}">'
        f'<div style="padding-bottom:18px;border-bottom:1px solid {RULE}">'
        f'<p style="margin:0;font-size:26px;line-height:1.1;color:{INK}">'
        # colour repeated on the span: without it Gradio's dark-theme text
        # colour wins over the inherited value and it renders near-white.
        f'<span style="font-weight:600;color:{INK}">{cards} cards</span> '
        f'<span style="color:{INK_3}">from {chunks} '
        f'{"chunk" if chunks == 1 else "chunks"}</span></p></div>'
        f'<p style="margin:10px 0 0;font-family:{MONO};font-size:11px;color:{MUTE}">'
        f"dropped {dropped} &nbsp;·&nbsp; duplicates {duplicates} &nbsp;·&nbsp; "
        f"requests {requests} &nbsp;·&nbsp; cached {cached}</p></div>"
    )


_FLIP_ICON = (
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 7.5 4"></path><path d="M20 3v4h-4"></path>'
    '<path d="M21 12a9 9 0 0 1-9 9 9 9 0 0 1-7.5-4"></path><path d="M4 21v-4h4"></path></svg>'
)


def _face_head(card, rule_colour: str, back: bool = False) -> str:
    left = (
        f'<span style="{LBL}">{_esc(card.topic)}</span>'
        if back
        else meter(card.difficulty)
    )
    right = (
        f'<span style="{LBL};color:{rule_colour}">answer</span>'
        if back
        else f'<span style="{LBL}">{_esc(card.topic)}</span>'
    )
    return (
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'gap:10px;flex-shrink:0">{left}{right}</div>'
    )


def render_cards(entries: list[SourcedCard]) -> str:
    if not entries:
        return ""
    blocks = []
    for index, entry in enumerate(entries):
        card = entry.card
        rule_colour = DIFFICULTY.get(card.difficulty, (MUTE, 0))[0]
        edge = f"border-left:3px solid {rule_colour};"
        # Stagger the entrance so a dozen cards arrive as a wave rather than a slab.
        delay = f"animation-delay:{min(index, 11) * 45}ms"
        blocks.append(
            f'<label class="fc" style="{delay}"><input type="checkbox">'
            f'<div class="fc-inner">'
            f'<div class="fc-face" style="{edge}">'
            f"{_face_head(card, rule_colour)}"
            f'<p style="margin:0;font-size:18px;font-weight:500;line-height:1.36;color:{INK};'
            f'text-wrap:pretty;flex-grow:1">{_esc(card.question)}</p>'
            f'<div style="display:flex;align-items:center;gap:6px;color:{ACCENT};flex-shrink:0">'
            f'{_FLIP_ICON}<span style="{LBL};color:{ACCENT}">flip for answer</span></div></div>'
            f'<div class="fc-face fc-back" style="{edge}">'
            f"{_face_head(card, rule_colour, back=True)}"
            f'<p style="margin:0;font-size:15px;line-height:28px;color:{INK_2};'
            f'text-wrap:pretty;flex-grow:1;overflow-y:auto">{_esc(card.answer)}</p></div>'
            f"</div></label>"
        )
    return (
        f'<div style="font-family:{SERIF};padding-top:22px;display:grid;'
        f"grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px;"
        f'align-items:start">{"".join(blocks)}</div>'
    )


def render_partial(failures: list[str]) -> str:
    lines = "".join(
        f'<p style="margin:5px 0 0;font-family:{MONO};font-size:12px;line-height:1.5;'
        f'color:{INK_3}">{_esc(failure)}</p>'
        for failure in failures
    )
    count = len(failures)
    return (
        f'<div style="font-family:{SERIF};padding-top:18px">'
        f'<div style="border:1px solid {RULE};border-left:3px solid {OCHRE};background:#faf4e8;'
        f'border-radius:2px;padding:16px 20px">'
        f'<span style="font-size:16px;font-weight:600;color:{INK}">'
        f'{count} chunk{"" if count == 1 else "s"} failed</span>{lines}</div></div>'
    )


EMPTY_RESULTS = (
    f'<div style="font-family:{SERIF};border:1px dashed {RULE};border-radius:2px;'
    f'padding:150px 24px;text-align:center">'
    f'<p style="margin:0;font-size:15px;color:{MUTE}">Cards appear here once you generate.</p></div>'
)


# --- pipeline glue ---------------------------------------------------------


@dataclass
class Outcome:
    entries: list[SourcedCard] = field(default_factory=list)
    chunks: int = 0
    dropped: int = 0
    duplicates: int = 0
    failures: list[str] = field(default_factory=list)
    requests: int = 0
    cache_hits: int = 0
    csv_path: str | None = None
    dedupe_note: str = ""


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


def write_csv(entries: list[SourcedCard]) -> str:
    path = Path(tempfile.mkdtemp()) / "cards.csv"
    exporter.write_csv(entries, path)
    return str(path)


NO_INPUT = (
    f'<div style="font-family:{SERIF};border:1px dashed {RULE};border-radius:2px;'
    f'padding:44px 24px;text-align:center">'
    f'<p style="margin:0;font-size:16px;color:{INK_2}">Nothing to work with</p>'
    f'<p style="margin:7px 0 0;font-size:13.5px;color:{MUTE}">Paste notes on the left '
    f"or upload a .md or .txt file, then try again.</p></div>"
)

_NO_KEY_STEPS = (
    "Add GEMINI_API_KEY to .env at the project root",
    "Reload the page once it is set",
)

_QUOTA_STEPS = (
    "Wait a minute, then try again",
    "Lower Max chunks and split the work",
    "Run again tomorrow if the daily cap is hit",
)


# --- gradio handlers -------------------------------------------------------


def preview(notes_text: str, files: list[str] | None, max_chunks: float) -> str:
    try:
        settings = load_settings()
    except ConfigError as exc:
        return render_error("No API key", "", _esc(str(exc)), _NO_KEY_STEPS)

    chunks = gather_chunks(notes_text, files, settings)[: int(max_chunks)]
    if not chunks:
        return NO_INPUT

    tokens = sum(estimate_tokens(chunk.text) for chunk in chunks)
    return render_estimate(len(chunks), tokens, settings.requests_per_minute)


def active_step(stages: list[list[str]]) -> int:
    """1-based position of the running stage.

    Derived rather than tracked by hand: a separate counter drifted out of step
    with the stage list and reported "step 1 of 4" while stage 2 was running.
    """
    for index, stage in enumerate(stages):
        if stage[0] == "active":
            return index + 1
    return len(stages)


def _stages(use_dedupe: bool) -> list[list[str]]:
    stages = [
        ["pending", "Splitting notes into chunks", "", ""],
        ["pending", "Generating cards", "", ""],
    ]
    if use_dedupe:
        stages.append(
            [
                "pending",
                "Removing near-duplicates",
                "First run loads a model, about 25 seconds",
                "",
            ]
        )
    stages.append(["pending", "Writing CSV", "", ""])
    return stages


def generate(
    notes_text: str, files: list[str] | None, max_chunks: float, use_dedupe: bool
):
    hide = gr.update(visible=False)

    try:
        settings = load_settings()
    except ConfigError as exc:
        yield render_error("No API key", "", _esc(str(exc)), _NO_KEY_STEPS), "", hide
        return

    chunks = gather_chunks(notes_text, files, settings)[: int(max_chunks)]
    if not chunks:
        yield NO_INPUT, "", hide
        return

    stages = _stages(use_dedupe)
    total = len(stages)
    client = GeminiClient(settings)
    outcome = Outcome(chunks=len(chunks))

    stages[0][0] = "done"
    stages[0][3] = f"{len(chunks)} chunk{'' if len(chunks) == 1 else 's'}"
    stages[1][0] = "active"
    stages[1][3] = f"0 / {len(chunks)}"
    yield render_stages(stages, active_step(stages), total), "", hide

    for index, chunk in enumerate(chunks, start=1):
        try:
            result = pipeline.run([chunk], settings, client)
        except errors.APIError as exc:
            detail = (
                f"The free tier allows {settings.requests_per_minute} requests a "
                f"minute. {_esc(str(exc.message))} Your notes are still here."
            )
            steps = _QUOTA_STEPS if exc.code == 429 else ()
            yield (
                render_error(
                    "Out of quota" if exc.code == 429 else "API error",
                    f"HTTP {exc.code}",
                    detail,
                    steps,
                )
                + render_cards(outcome.entries),
                "",
                hide,
            )
            return

        outcome.entries.extend(result.cards)
        outcome.dropped += result.dropped
        outcome.failures.extend(result.failures)
        stages[1][3] = f"{index} / {len(chunks)}"
        yield (
            render_stages(stages, active_step(stages), total),
            render_cards(outcome.entries),
            hide,
        )

    stages[1][0] = "done"

    if use_dedupe:
        stages[2][0] = "active"
        yield (
            render_stages(stages, active_step(stages), total),
            render_cards(outcome.entries),
            hide,
        )
        try:
            kept, dropped = dedupe.deduplicate(
                outcome.entries, settings.similarity_threshold, settings.embedding_model
            )
            outcome.entries, outcome.duplicates = kept, len(dropped)
            stages[2][3] = f"-{len(dropped)}"
        except dedupe.DedupeUnavailable as exc:
            outcome.dedupe_note = str(exc)
            stages[2][3] = "skipped"
        stages[2][0] = "done"

    stages[-1][0] = "done"
    outcome.csv_path = write_csv(outcome.entries)
    outcome.requests = client.request_count
    outcome.cache_hits = client.cache_hits

    summary = render_summary(
        len(outcome.entries),
        outcome.chunks,
        outcome.dropped,
        outcome.duplicates,
        outcome.requests,
        outcome.cache_hits,
    )
    if outcome.failures:
        summary += render_partial(outcome.failures)
    if outcome.dedupe_note:
        summary += (
            f'<p style="margin:10px 0 0;font-family:{SERIF};font-size:12.5px;'
            f'color:{MUTE}">Dedupe skipped: {_esc(outcome.dedupe_note)}</p>'
        )

    yield (
        summary,
        render_cards(outcome.entries),
        gr.update(value=outcome.csv_path, visible=True),
    )


# --- ui --------------------------------------------------------------------

with gr.Blocks(title="Flashcards") as demo:
    gr.HTML(header_html())

    with gr.Row(elem_id="main"):
        with gr.Column(elem_id="left"):
            notes_input = gr.Textbox(
                elem_id="notes",
                lines=9,
                max_lines=20,
                placeholder="Paste lecture notes here…",
                show_label=False,
                container=False,
            )

            with gr.Accordion("Upload .md or .txt", open=False, elem_id="upload"):
                file_input = gr.File(
                    file_count="multiple", file_types=[".md", ".txt"], show_label=False
                )

            with gr.Column(elem_id="controls"):
                max_chunks = gr.Number(
                    label="Max chunks",
                    value=5,
                    minimum=1,
                    precision=0,
                    elem_id="maxchunks",
                )
                use_dedupe = gr.Checkbox(
                    label="Remove near-duplicates",
                    value=True,
                    elem_id="dedupe",
                )

            gr.HTML(hint_html(5))

            preview_button = gr.Button("Preview · free", elem_id="previewbtn")
            generate_button = gr.Button("Generate", elem_id="genbtn")

        with gr.Column(elem_id="right"):
            status = gr.HTML(EMPTY_RESULTS)
            download = gr.DownloadButton(
                "DOWNLOAD CSV", visible=False, elem_id="dlbtn"
            )
            cards = gr.HTML()

    preview_button.click(
        preview, inputs=[notes_input, file_input, max_chunks], outputs=status
    )
    generate_button.click(
        generate,
        inputs=[notes_input, file_input, max_chunks, use_dedupe],
        outputs=[status, cards, download],
    )


if __name__ == "__main__":
    # server_port is passed only when PORT is set. Gradio otherwise resolves the
    # host and port from GRADIO_SERVER_NAME / GRADIO_SERVER_PORT.
    port = os.environ.get("PORT")
    demo.launch(css=CSS, **({"server_port": int(port)} if port else {}))
