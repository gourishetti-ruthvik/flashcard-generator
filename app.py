"""Gradio web front end, served in a browser.

Two columns on a desktop window -- the form on the left, results on the right --
collapsing to one column on a narrow screen. All real work is done by the same
package the CLI uses; the key is read server-side and never reaches the browser.

Everything non-interactive is rendered as inline-styled HTML rather than Gradio
components: it is the only way to control the layout precisely, and inline
styles are immune to Gradio's own stylesheet.
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

BG = "#14151a"
SURFACE = "#1a1c22"
SURFACE_2 = "#1c1e25"
SURFACE_3 = "#23262e"
BORDER = "#2a2d35"
BORDER_STRONG = "#3a3f49"
TEXT = "#e8e9ec"
TEXT_2 = "#9ba1ac"
TEXT_3 = "#6b7280"
TEXT_4 = "#575d67"
ACCENT = "#d99a4e"

DIFFICULTY = {
    "easy": ("#7fa87f", 1),
    "medium": ("#d2a24c", 2),
    "hard": ("#c47f66", 3),
}

SANS = "'IBM Plex Sans', system-ui, sans-serif"
SERIF = "'Literata', Georgia, serif"
MONO = "'IBM Plex Mono', ui-monospace, monospace"

FONTS = (
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
    "&family=IBM+Plex+Sans:wght@400;500;600"
    "&family=Literata:opsz,wght@7..72,400;7..72,500&display=swap"
)

CSS = f"""
@import url('{FONTS}');

.gradio-container, body {{
  background: {BG} !important;
  font-family: {SANS} !important;
  max-width: 1180px !important;
  margin: 0 auto !important;
  padding: 0 32px 56px !important;
}}
/* Gradio caps its own container well below the max-width above. */
.gradio-container {{ color: {TEXT} !important; width: 100% !important; }}
/* The file dropzone is wider than the sidebar and pushed out a scrollbar. */
#upload, #upload * {{ min-width: 0 !important; max-width: 100% !important; }}
#notes textarea {{ max-height: 300px !important; }}
footer, .show-api, .built-with {{ display: none !important; }}

/* Two columns on a desktop browser: the form stays put on the left while
   results scroll on the right. Collapses to one column on narrow screens. */
#main {{ gap: 32px !important; align-items: flex-start !important; }}
/* A long paste grew the textarea until Generate sat below the fold of a sticky
   sidebar, out of reach. The sidebar scrolls internally instead. */
#left {{
  flex: 0 0 360px !important;
  position: sticky !important;
  top: 24px !important;
  max-height: calc(100vh - 48px) !important;
  overflow-y: auto !important;
}}
/* flex-basis 0, not auto: with auto the column is sized by its content and the
   card grid pushed it past the container instead of wrapping inside it. */
#right {{ flex: 1 1 0 !important; min-width: 0 !important; }}
#left > *, #right > * {{ background: transparent !important; border: none !important; }}
#left {{ gap: 0 !important; }}

@media (max-width: 900px) {{
  .gradio-container, body {{ padding: 0 20px 40px !important; }}
  #main {{ flex-direction: column !important; gap: 0 !important; }}
  #left {{ position: static !important; flex: 1 1 auto !important; width: 100% !important; }}
  #right {{ width: 100% !important; }}
}}
/* Gradio's loading tracker keeps its box when hidden, which left a 68px gap
   under the accordion. Progress is rendered by the app itself instead. */
.gradio-container .wrap.hide {{ display: none !important; }}

/* notes textarea */
#notes textarea {{
  background: {SURFACE_2} !important;
  border: 1px solid #2e323b !important;
  border-radius: 8px !important;
  color: #c3c8d0 !important;
  font-family: {SANS} !important;
  font-size: 13.5px !important;
  line-height: 1.6 !important;
  padding: 14px 15px !important;
  box-shadow: none !important;
}}
#notes textarea::placeholder {{ color: {TEXT_4} !important; }}
#notes textarea:focus {{ border-color: {BORDER_STRONG} !important; outline: none !important; }}
/* Gradio nests the textarea inside the label, so only the label's text is
   hidden here. Hiding the label itself takes the input down with it. */
#notes label > span {{ display: none !important; }}

/* upload accordion */
#upload {{
  background: {SURFACE} !important;
  border: 1px solid {BORDER} !important;
  border-radius: 8px !important;
  margin-top: 14px !important;
}}
#upload button, #upload .label-wrap {{
  color: {TEXT_2} !important;
  font-family: {SANS} !important;
  font-size: 13.5px !important;
  font-weight: 400 !important;
  min-height: 48px !important;
}}

/* control rows */
#controls {{ margin-top: 14px !important; gap: 0 !important; }}
#maxchunks, #dedupe {{
  background: {SURFACE} !important;
  border: 1px solid {BORDER} !important;
  padding: 10px 15px !important;
  min-height: 56px !important;
  display: flex !important;
  align-items: center !important;
}}
#maxchunks {{ border-radius: 8px 8px 0 0 !important; }}
#dedupe {{ border-radius: 0 0 8px 8px !important; border-top: none !important; }}
#maxchunks label, #dedupe label {{
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  gap: 12px !important;
  width: 100% !important;
  margin: 0 !important;
}}
/* Gradio puts the checkbox before its text; the design wants the label on the
   left and the switch on the right. */
#dedupe label {{ flex-direction: row-reverse !important; }}
#maxchunks label span, #dedupe label span {{
  color: #d5d9df !important; font-size: 13.5px !important; font-weight: 400 !important;
  margin: 0 !important;
}}
#maxchunks input {{
  background: {SURFACE_3} !important;
  border: 1px solid #333740 !important;
  border-radius: 7px !important;
  color: {TEXT} !important;
  font-family: {MONO} !important;
  font-size: 15px !important;
  height: 40px !important;
  width: 96px !important;
  flex: 0 0 96px !important;
  text-align: center !important;
  padding: 0 !important;
}}
#dedupe input[type="checkbox"] {{
  appearance: none !important; -webkit-appearance: none !important;
  width: 46px !important; height: 28px !important;
  flex: 0 0 46px !important;
  border-radius: 14px !important;
  background: {BORDER} !important;
  border: none !important;
  position: relative !important;
  cursor: pointer !important;
  transition: background .15s ease !important;
}}
#dedupe input[type="checkbox"]::after {{
  content: ""; position: absolute; top: 3px; left: 3px;
  width: 22px; height: 22px; border-radius: 11px; background: {BG};
  transition: transform .15s ease;
}}
#dedupe input[type="checkbox"]:checked {{ background: {ACCENT} !important; }}
#dedupe input[type="checkbox"]:checked::after {{ transform: translateX(18px); }}

/* buttons */
#previewbtn, #genbtn, #dlbtn {{
  font-family: {SANS} !important;
  border-radius: 8px !important;
  box-shadow: none !important;
  margin-top: 10px !important;
}}
#previewbtn {{
  background: {SURFACE_2} !important;
  border: 1px solid {BORDER_STRONG} !important;
  color: #d5d9df !important;
  min-height: 48px !important;
  font-size: 14.5px !important;
  font-weight: 500 !important;
}}
#genbtn, #dlbtn {{
  background: {ACCENT} !important;
  border: none !important;
  color: #17140f !important;
  min-height: 52px !important;
  font-size: 15px !important;
  font-weight: 600 !important;
}}
#genbtn:hover, #dlbtn:hover {{ background: #e8b473 !important; }}
"""


# --- rendering helpers -----------------------------------------------------


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def meter(difficulty: str) -> str:
    """Three ascending bars, filled by level.

    The count carries the meaning; colour only reinforces it, so the level
    survives greyscale and colour blindness.
    """
    colour, filled = DIFFICULTY.get(difficulty, (TEXT_3, 0))
    bars = "".join(
        f'<span style="width:3px;border-radius:1px;height:{h}px;'
        f'background:{colour if i < filled else "#2e323b"}"></span>'
        for i, h in enumerate((4, 7, 11))
    )
    return (
        f'<span style="display:inline-flex;align-items:flex-end;gap:2px;height:11px">{bars}</span>'
        f'<span style="font-size:11.5px;font-weight:500;color:{colour}">{_esc(difficulty)}</span>'
    )


def header_html() -> str:
    return (
        f'<div style="padding:24px 0 18px;border-bottom:1px solid #24272f;'
        f'display:flex;flex-direction:column;gap:5px;font-family:{SANS}">'
        f'<div style="display:flex;align-items:baseline;justify-content:space-between;gap:12px">'
        f'<h1 style="margin:0;font-size:24px;font-weight:600;letter-spacing:-0.02em;color:{TEXT}">Flashcards</h1>'
        f'<span style="font-family:{MONO};font-size:11px;color:{TEXT_3}">gemini-2.5-flash</span></div>'
        f'<p style="margin:0;font-size:13px;color:{TEXT_2};line-height:1.45">Notes in, Anki cards out.</p></div>'
    )


def hint_html(rpm: int) -> str:
    return (
        f'<div style="padding:12px 0 0;display:flex;align-items:flex-start;gap:8px;font-family:{SANS}">'
        f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="{TEXT_3}" stroke-width="1.8" '
        f'stroke-linecap="round" style="flex-shrink:0;margin-top:2px"><circle cx="12" cy="12" r="9"></circle>'
        f'<path d="M12 8h.01M11 12h1v4h1"></path></svg>'
        f'<p style="margin:0;font-size:11.5px;line-height:1.5;color:{TEXT_3}">Free tier allows '
        f'<span style="font-family:{MONO};color:{TEXT_2}">{rpm}</span> requests per minute. '
        f"Higher values wait between calls.</p></div>"
    )


def render_estimate(chunks: int, tokens: int, rpm: int) -> str:
    waiting = max(0, (chunks - rpm) * 12)
    cells = "".join(
        f'<div style="display:flex;flex-direction:column;gap:3px">'
        f'<span style="font-family:{MONO};font-size:26px;font-weight:500;line-height:1;color:{TEXT}">{value}</span>'
        f'<span style="font-size:11.5px;color:#7f858f">{label}</span></div>'
        for value, label in (
            (chunks, "chunk" if chunks == 1 else "chunks"),
            (chunks, "request" if chunks == 1 else "requests"),
            (tokens, "tokens approx"),
        )
    )
    wait_line = (
        f" About {waiting}s of that is waiting on the rate limit." if waiting else ""
    )
    return (
        f'<div style="font-family:{SANS};padding-top:20px">'
        f'<div style="border:1px solid #33383f;background:#1b1e24;border-radius:10px;overflow:hidden">'
        f'<div style="padding:13px 16px 0"><span style="font-size:11px;letter-spacing:0.09em;'
        f'text-transform:uppercase;font-weight:500;color:#7f858f">Estimate</span></div>'
        f'<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;padding:12px 16px 16px">{cells}</div>'
        f'<div style="display:flex;align-items:center;gap:9px;padding:12px 16px;background:#1e241f;'
        f'border-top:1px solid #2b3430"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" '
        f'stroke="#7fa87f" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" '
        f'style="flex-shrink:0"><path d="M20 6L9 17l-5-5"></path></svg>'
        f'<span style="font-size:12.5px;line-height:1.45;color:#a8c0a8">No API calls were made.</span></div></div>'
        f'<p style="margin:10px 2px 0;font-size:11.5px;line-height:1.5;color:{TEXT_3}">'
        f"Token count is estimated locally at 4 characters per token, not measured by the API.{wait_line}</p></div>"
    )


def render_error(title: str, code: str, detail: str, steps: tuple[str, ...] = ()) -> str:
    code_html = (
        f'<span style="font-family:{MONO};font-size:11px;color:#8a6455">{_esc(code)}</span>'
        if code
        else ""
    )
    rows = ""
    if steps:
        items = []
        for index, step in enumerate(steps, 1):
            radius = (
                "8px 8px 0 0"
                if index == 1
                else ("0 0 8px 8px" if index == len(steps) else "0")
            )
            top = "none" if index > 1 else f"1px solid {BORDER}"
            items.append(
                f'<div style="display:flex;align-items:center;gap:12px;min-height:56px;padding:11px 15px;'
                f'background:{SURFACE};border:1px solid {BORDER};border-top:{top};border-radius:{radius}">'
                f'<span style="font-family:{MONO};font-size:15px;color:{ACCENT};width:18px">{index}</span>'
                f'<span style="font-size:13.5px;line-height:1.45;color:#c3c8d0">{step}</span></div>'
            )
        rows = (
            f'<div style="padding-top:18px"><span style="font-size:11px;letter-spacing:0.09em;'
            f'text-transform:uppercase;font-weight:500;color:{TEXT_3}">What you can do</span>'
            f'<div style="margin-top:11px;display:flex;flex-direction:column;gap:1px">{"".join(items)}</div></div>'
        )
    return (
        f'<div style="font-family:{SANS};padding-top:20px">'
        f'<div style="border:1px solid #4a352e;background:#221a17;border-radius:10px;padding:15px 16px">'
        f'<div style="display:flex;align-items:flex-start;gap:11px">'
        f'<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#c47f66" stroke-width="1.9" '
        f'stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px">'
        f'<circle cx="12" cy="12" r="9"></circle><path d="M12 7.5v5.5"></path><path d="M12 16.5h.01"></path></svg>'
        f'<div style="display:flex;flex-direction:column;gap:6px">'
        f'<div style="display:flex;align-items:baseline;gap:8px">'
        f'<span style="font-size:14.5px;font-weight:600;color:#e6bfae">{_esc(title)}</span>{code_html}</div>'
        f'<p style="margin:0;font-size:13px;line-height:1.55;color:#b09287">{detail}</p>'
        f"</div></div></div>{rows}</div>"
    )


_DONE_ICON = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#7fa87f" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0">'
    '<circle cx="12" cy="12" r="10" stroke="#31463a"></circle><path d="M17 9l-6.2 6L7 11.6"></path></svg>'
)
_ACTIVE_ICON = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" '
    'style="flex-shrink:0"><circle cx="12" cy="12" r="10" stroke="#3a3f49"></circle>'
    f'<path d="M12 2a10 10 0 0 1 8.7 5" stroke="{ACCENT}"></path></svg>'
)
_PENDING_ICON = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#3a3f49" stroke-width="2" '
    'style="flex-shrink:0"><circle cx="12" cy="12" r="10"></circle></svg>'
)


def render_stages(stages: list[tuple[str, str, str, str]], done: int, total: int) -> str:
    """stages: (state, label, sublabel, meta) where state is done/active/pending."""
    rows = []
    for index, (state, label, sublabel, meta) in enumerate(stages):
        first, last = index == 0, index == len(stages) - 1
        radius = (
            "8px 8px 0 0" if first else ("0 0 8px 8px" if last else "0")
        )
        background = {"done": SURFACE, "active": "#1f2229"}.get(state, "#17191e")
        border = BORDER_STRONG if state == "active" else BORDER
        icon = {"done": _DONE_ICON, "active": _ACTIVE_ICON}.get(state, _PENDING_ICON)
        label_colour = {"done": "#d5d9df", "active": TEXT}.get(state, "#7c828c")
        meta_colour = {"done": "#7fa87f", "active": ACCENT}.get(state, TEXT_4)
        sub = (
            f'<span style="font-size:11.5px;line-height:1.4;color:{TEXT_2}">{_esc(sublabel)}</span>'
            if sublabel and state == "active"
            else ""
        )
        rows.append(
            f'<div style="display:flex;align-items:center;gap:13px;min-height:56px;padding:11px 15px;'
            f'background:{background};border:1px solid {border};'
            f'{"border-top:none;" if not first else ""}border-radius:{radius}">{icon}'
            f'<div style="display:flex;flex-direction:column;gap:3px;flex-grow:1">'
            f'<span style="font-size:13.5px;color:{label_colour}">{_esc(label)}</span>{sub}</div>'
            f'<span style="font-family:{MONO};font-size:11.5px;color:{meta_colour}">{_esc(meta)}</span></div>'
        )
    pct = int(100 * done / total) if total else 0
    return (
        f'<div style="font-family:{SANS};padding-top:20px">'
        f'<div style="display:flex;align-items:baseline;justify-content:space-between;padding-bottom:10px">'
        f'<span style="font-size:11px;letter-spacing:0.09em;text-transform:uppercase;font-weight:500;'
        f'color:{TEXT_3}">Progress</span>'
        f'<span style="font-family:{MONO};font-size:11.5px;color:{TEXT_2}">step {done} of {total}</span></div>'
        f'<div style="height:6px;border-radius:3px;background:#24272f;overflow:hidden;display:flex">'
        f'<div style="width:{pct}%;background:{ACCENT};border-radius:3px"></div></div>'
        f'<div style="display:flex;flex-direction:column;gap:2px;padding-top:20px">{"".join(rows)}</div></div>'
    )


def render_summary(
    cards: int, chunks: int, dropped: int, duplicates: int, requests: int, cached: int
) -> str:
    return (
        f'<div style="font-family:{SANS};padding-top:20px;display:flex;flex-direction:column;gap:7px">'
        f'<p style="margin:0;font-size:15px;line-height:1.4;color:#d5d9df">'
        f'<span style="font-family:{MONO};font-size:17px;font-weight:500;color:{TEXT}">{cards}</span> '
        f'cards from <span style="font-family:{MONO};color:{TEXT}">{chunks}</span> '
        f'{"chunk" if chunks == 1 else "chunks"}.</p>'
        f'<p style="margin:0;font-family:{MONO};font-size:11.5px;line-height:1.6;color:{TEXT_3}">'
        f"dropped {dropped} &nbsp;·&nbsp; duplicates {duplicates} &nbsp;·&nbsp; "
        f"requests {requests} &nbsp;·&nbsp; cached {cached}</p></div>"
    )


def render_cards(entries: list[SourcedCard]) -> str:
    if not entries:
        return ""
    blocks = []
    for entry in entries:
        card = entry.card
        blocks.append(
            f'<div style="background:{SURFACE};border:1px solid {BORDER};border-radius:10px;'
            f'padding:14px 15px;display:flex;flex-direction:column;gap:10px">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;gap:10px">'
            f'<div style="display:flex;align-items:center;gap:7px">{meter(card.difficulty)}</div>'
            f'<span style="font-family:{MONO};font-size:11px;color:{TEXT_3}">{_esc(card.topic)}</span></div>'
            f'<p style="margin:0;font-size:14.5px;font-weight:500;line-height:1.4;color:{TEXT};'
            f'text-wrap:pretty">{_esc(card.question)}</p>'
            f'<details><summary style="font-size:11.5px;color:{TEXT_3};cursor:pointer;list-style:none">'
            f"Show answer</summary>"
            f'<p style="margin:10px 0 0;font-family:{SERIF};font-size:14px;line-height:1.68;'
            f'color:#ccd1d8;text-wrap:pretty">{_esc(card.answer)}</p></details></div>'
        )
    # auto-fill rather than a fixed count: one column on a phone, two or three
    # across a browser window, without a breakpoint to maintain.
    return (
        f'<div style="font-family:{SANS};padding-top:20px;display:grid;'
        f"grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;"
        f'align-items:start">{"".join(blocks)}</div>'
    )


EMPTY_RESULTS = (
    f'<div style="font-family:{SANS};margin-top:20px;border:1px dashed {BORDER};'
    f'border-radius:10px;padding:44px 24px;text-align:center">'
    f'<p style="margin:0;font-size:13px;color:{TEXT_4}">Cards appear here once you generate.</p></div>'
)


def render_partial(failures: list[str]) -> str:
    lines = "".join(
        f'<p style="margin:4px 0 0;font-family:{MONO};font-size:11.5px;line-height:1.5;'
        f'color:#a89a75">{_esc(f)}</p>'
        for f in failures
    )
    count = len(failures)
    return (
        f'<div style="font-family:{SANS};padding-top:16px">'
        f'<div style="border:1px solid #4a3f2e;background:#211d16;border-radius:10px;padding:14px 15px">'
        f'<div style="display:flex;align-items:flex-start;gap:11px">'
        f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#d2a24c" stroke-width="1.9" '
        f'stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px">'
        f'<path d="M10.3 4.3L2.8 17a1.8 1.8 0 0 0 1.6 2.7h15.2A1.8 1.8 0 0 0 21.2 17L13.7 4.3a1.8 1.8 0 0 0-3.1 0z"></path>'
        f'<path d="M12 9.5v4"></path><path d="M12 17h.01"></path></svg>'
        f'<div style="display:flex;flex-direction:column">'
        f'<span style="font-size:13.5px;font-weight:600;color:#ddc189">'
        f'{count} chunk{"" if count == 1 else "s"} failed</span>{lines}'
        f"</div></div></div></div>"
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


NO_INPUT = render_error(
    "Nothing to work with",
    "",
    "Paste notes above or upload a .md or .txt file, then try again.",
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


_NO_KEY_STEPS = (
    "Add a Space secret named GEMINI_API_KEY",
    "Or put GEMINI_API_KEY=your-key in .env locally",
    "Reload the page once it is set",
)

_QUOTA_STEPS = (
    "Wait a minute, then try again",
    "Lower Max chunks and split the work",
    "Run again tomorrow if the daily cap is hit",
)


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
            ["pending", "Removing near-duplicates", "First run loads a model, ~25s", ""]
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
                f"The free tier allows {settings.requests_per_minute} requests per "
                f"minute. {_esc(str(exc.message))}"
            )
            steps = _QUOTA_STEPS if exc.code == 429 else ()
            yield (
                render_error("Out of quota" if exc.code == 429 else "API error",
                             f"HTTP {exc.code}", detail, steps)
                + (render_cards(outcome.entries) if outcome.entries else ""),
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
            f'<p style="margin:10px 0 0;font-family:{SANS};font-size:11.5px;'
            f'color:{TEXT_3}">Dedupe skipped: {_esc(outcome.dedupe_note)}</p>'
        )

    yield (
        summary,
        render_cards(outcome.entries),
        gr.update(value=outcome.csv_path, visible=True),
    )


# --- ui --------------------------------------------------------------------

with gr.Blocks(title="Flashcard Generator") as demo:
    gr.HTML(header_html())

    with gr.Row(elem_id="main"):
        with gr.Column(elem_id="left"):
            notes_input = gr.Textbox(
                elem_id="notes",
                lines=10,
                max_lines=24,
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
                "Download CSV", visible=False, elem_id="dlbtn"
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
    # host and port from GRADIO_SERVER_NAME / GRADIO_SERVER_PORT, which is how
    # Hugging Face Spaces tells it to bind 0.0.0.0:7860 -- hardcoding a port here
    # would override that.
    port = os.environ.get("PORT")
    demo.launch(css=CSS, **({"server_port": int(port)} if port else {}))
