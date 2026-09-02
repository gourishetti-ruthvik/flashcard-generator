"""Gradio web front end, served in a browser.

Press Room: a riso-print study desk. Warm newsprint ground, two spot inks,
grain, and display type offset the way a misregistered print run looks. Two
columns on a desktop window -- the form on the left, results on the right --
collapsing to one column below 900px.

The spine of the design is the daily ration: twenty tick marks in the header
that fill as requests are spent, because the free tier's 20-a-day cap is the
constraint that governs everything and it is otherwise invisible until it bites.
The count is real, not decoration: it is recorded inside the client wrapper, so
the CLI, the benchmark and this page all draw on one number, and it is re-read
on every page load rather than baked in when the server booted.

All real work is done by the same package the CLI uses; the key is read
server-side and never reaches the browser. Everything non-interactive is
rendered as inline-styled HTML rather than Gradio components: it is the only way
to control the layout precisely, and inline styles are immune to Gradio's own
stylesheet. Colours are referenced as CSS custom properties rather than literal
hex so that one token swap gives the whole page a dark mode.
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
from flashcards.client import (
    DAILY_CAP,
    GeminiClient,
    is_daily_cap,
    quota_day,
    record_spend,
    resets_in,
    spent_today,
    usage_file,
)
from flashcards.config import ConfigError, Settings, load_settings
from flashcards.models import Chunk, SourcedCard

# --- design tokens ---------------------------------------------------------

# Every ratio was measured against the surface it actually sits on, not
# asserted: this project has twice shipped colours that looked fine and failed
# AA. The tightest pairs are light `med` at 5.10:1 and dark `mute` at 4.61:1.
LIGHT_TOKENS = (
    "--paper:#f2efe4;--paper2:#fbf9f2;--ink:#1b1a17;--ink2:#413d35;"
    "--mute:#6f6858;--rule:#d8d2c2;--rule2:#e7e2d5;--blue:#2b4a8b;"
    "--blued:#1d3462;--orange:#ff6a3d;--oranget:#b03c12;--warmbg:#fdf0e8;"
    "--easy:#3f6b3a;--med:#8a6410;--hard:#9c3520;--shadow:#d8d2c2;"
    "--knockfg:#fbf9f2;--grainblend:multiply;--grainop:.14"
)
DARK_TOKENS = (
    "--paper:#171612;--paper2:#211f19;--ink:#f1ede1;--ink2:#c9c3b3;"
    "--mute:#8e8776;--rule:#38342b;--rule2:#2b2820;--blue:#89a9e4;"
    "--blued:#a8c0ee;--orange:#ff8a5c;--oranget:#ff9d75;--warmbg:#2a211b;"
    "--easy:#8fc088;--med:#e0b45a;--hard:#e69182;--shadow:#0e0d0a;"
    "--knockfg:#171612;--grainblend:screen;--grainop:.07"
)

DIFFICULTY = {"easy": 1, "medium": 2, "hard": 3}
DIFF_VAR = {"easy": "--easy", "medium": "--med", "hard": "--hard"}

SERIF = "'Newsreader', Georgia, serif"
DISP = "'Instrument Serif', Georgia, serif"
MONO = "'IBM Plex Mono', ui-monospace, monospace"

FONTS = (
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600"
    "&family=Instrument+Serif:ital@0;1"
    "&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap"
)

GRAIN = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E"
    "%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' "
    "numOctaves='3'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' "
    "filter='url(%23n)'/%3E%3C/svg%3E\")"
)

LBL = (
    f"font-family:{MONO};font-size:10px;letter-spacing:.14em;"
    "text-transform:uppercase;color:var(--mute)"
)

CSS = f"""
@import url('{FONTS}');

:root{{{LIGHT_TOKENS}}}
/* Default follows the OS while the toggle is untouched; either pill then wins
   over it, which is why the explicit rules are declared last. */
@media (prefers-color-scheme: dark){{
  body:not(:has(#m-light:checked)):not(:has(#m-dark:checked)){{{DARK_TOKENS}}}
}}
body:has(#m-dark:checked){{{DARK_TOKENS}}}
body:has(#m-light:checked){{{LIGHT_TOKENS}}}

body{{background:var(--paper);margin:0}}
/* The ground carries its own opaque paper: the grain multiplies, and over a
   transparent layer that turned the whole page almost black. */
#ground{{position:fixed;inset:0;z-index:0;pointer-events:none;background:var(--paper)}}
#ground .grain{{position:absolute;inset:0;mix-blend-mode:var(--grainblend);
 opacity:var(--grainop);background-image:{GRAIN}}}
#ground .bloom{{position:absolute;border-radius:50%;filter:blur(90px);opacity:.30}}
#ground .b1{{width:460px;height:460px;left:-120px;top:-140px;background:var(--blue);
 opacity:.055;animation:drift1 54s ease-in-out infinite}}
#ground .b2{{width:400px;height:400px;right:-100px;bottom:-120px;background:var(--orange);
 opacity:.05;animation:drift2 67s ease-in-out infinite}}
@keyframes drift1{{0%,100%{{transform:translate(0,0)}}50%{{transform:translate(70px,50px)}}}}
@keyframes drift2{{0%,100%{{transform:translate(0,0)}}50%{{transform:translate(-60px,-45px)}}}}
#groundwrap{{position:static !important;height:0 !important;margin:0 !important;
 padding:0 !important;overflow:visible !important}}

/* Gradio caps the container at 854px; without this the two columns never fit. */
.gradio-container{{background:transparent !important;position:relative;z-index:1;
 width:100% !important;max-width:1440px !important;padding:26px 40px 46px !important;
 font-family:{SERIF} !important}}
.gradio-container .prose,.block,.form{{background:transparent !important;border:none !important}}
.gap,.panel{{background:transparent !important}}
.gradio-container > .main{{max-width:none !important;padding:0 !important}}
/* The loading tracker keeps its box while hidden, leaving a 68px gap. */
.wrap.hide{{display:none !important}}

#main{{gap:44px !important;align-items:flex-start !important}}
#left{{flex:0 0 400px !important;position:sticky;top:20px;
 max-height:calc(100vh - 44px);overflow-y:auto;overflow-x:hidden}}
/* flex-basis:auto lets the card grid size the column by its content, which blew
   the right column past the container. */
#right{{flex:1 1 0 !important;min-width:0}}
@media (max-width:900px){{
  #main{{flex-direction:column !important}}
  /* The header is inline-styled flex; at 375px the 20-tick ration ran off the
     right edge and the counter was clipped. Inline styles lose to !important. */
  .hd{{flex-direction:column !important;align-items:flex-start !important;gap:14px}}
  .hd h1{{font-size:46px !important}}
  .meta{{flex-wrap:wrap;gap:12px;width:100%}}
  .ration{{flex-wrap:wrap;gap:9px;text-align:left !important;width:100%}}
  .ticks{{justify-content:flex-start !important}}
  #left{{flex:1 1 auto !important;position:static;max-height:none;width:100%}}
  .gradio-container{{padding:20px 18px 34px !important}}
}}

/* Gradio nests the textarea inside its label, so hiding `label` hides the input. */
#notes label > span{{display:none}}
#notes textarea{{background:var(--paper2) !important;border:1.5px solid var(--ink) !important;
 border-radius:0 !important;box-shadow:4px 4px 0 var(--shadow);color:var(--ink2) !important;
 font-family:{SERIF} !important;font-size:14.5px !important;line-height:1.6 !important;
 padding:14px 16px !important;max-height:300px}}
#notes textarea::placeholder{{color:var(--mute) !important}}
#notes textarea:focus{{outline:2px solid var(--blue);outline-offset:2px}}

#upload{{border:1.5px dashed var(--rule) !important;border-radius:0 !important;
 background:transparent !important;margin-top:14px}}
#upload button, #upload .label-wrap span{{font-family:{MONO} !important;font-size:11.5px !important;
 letter-spacing:.1em;text-transform:uppercase;color:var(--mute) !important}}

#maxchunks label span,#dedupe label span{{font-family:{MONO} !important;font-size:10px !important;
 letter-spacing:.14em;text-transform:uppercase;color:var(--mute) !important}}
#maxchunks input{{background:var(--paper2) !important;border:1.5px solid var(--ink) !important;
 border-radius:0 !important;box-shadow:3px 3px 0 var(--shadow);color:var(--ink) !important;
 font-family:{MONO} !important}}
#dedupe input[type=checkbox]{{border:1.5px solid var(--ink) !important;border-radius:0 !important;
 background:var(--paper2) !important}}
#dedupe input[type=checkbox]:checked{{background:var(--blue) !important}}

#previewbtn,#genbtn,#dlbtn{{border-radius:0 !important;font-family:{MONO} !important;
 letter-spacing:.13em;text-transform:uppercase}}
#previewbtn{{background:transparent !important;border:1.5px dashed var(--blue) !important;
 color:var(--blue) !important;font-size:12px !important;padding:13px !important}}
#previewbtn:hover{{background:var(--paper2) !important}}
#genbtn{{background:var(--blue) !important;border:1.5px solid var(--ink) !important;
 color:var(--knockfg) !important;font-size:12.5px !important;padding:15px !important;
 box-shadow:5px 5px 0 var(--ink);transition:transform .12s,box-shadow .12s}}
#genbtn:hover{{transform:translate(2px,2px);box-shadow:3px 3px 0 var(--ink)}}
#dlbtn{{background:var(--paper2) !important;border:1.5px solid var(--ink) !important;
 color:var(--ink) !important;font-size:11px !important;box-shadow:3px 3px 0 var(--ink);
 min-width:0 !important;flex:0 0 auto !important}}

/* The mode pills are three radios, so "auto" can follow the OS and either pill
   can override it. No JavaScript: the whole switch is :has(). */
#m-light,#m-dark{{position:absolute;opacity:0;width:0;height:0;pointer-events:none}}
/* Between the 900px breakpoint and roughly 1130px the cluster no longer fits
   beside the title, and the dark pill was being silently clipped rather than
   scrolling. Wrapping drops it onto its own line, still right-aligned. */
.hd{{flex-wrap:wrap}}
.meta{{display:flex;align-items:center;gap:22px;flex:0 0 auto;
 flex-wrap:wrap;justify-content:flex-end;margin-left:auto}}
.ration{{display:flex;align-items:center;gap:12px}}
.ration .lbl{{display:block}}
.modes{{display:inline-flex;border:1.5px solid var(--ink);flex:0 0 auto}}
.m{{display:inline-flex;align-items:center;gap:5px;padding:4px 9px;font-family:{MONO};
 font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--mute);cursor:pointer}}
.m.lt{{background:var(--ink);color:var(--paper)}}
@media (prefers-color-scheme: dark){{
  body:not(:has(#m-light:checked)):not(:has(#m-dark:checked)) .m.lt{{
    background:transparent;color:var(--mute)}}
  body:not(:has(#m-light:checked)):not(:has(#m-dark:checked)) .m.dk{{
    background:var(--ink);color:var(--paper)}}
}}
body:has(#m-dark:checked) .m.lt{{background:transparent;color:var(--mute)}}
body:has(#m-dark:checked) .m.dk{{background:var(--ink);color:var(--paper)}}
body:has(#m-light:checked) .m.lt{{background:var(--ink);color:var(--paper)}}
body:has(#m-light:checked) .m.dk{{background:transparent;color:var(--mute)}}

/* Cards stack in a grid cell rather than being absolutely positioned, so the
   card takes the height of its taller face instead of a fixed one. */
.fc{{display:block;perspective:1300px;cursor:pointer}}
.fc input{{position:absolute;opacity:0;width:0;height:0}}
.fc-inner{{display:grid;transition:transform .58s cubic-bezier(.2,.8,.2,1);
 transform-style:preserve-3d}}
.fc input:checked ~ .fc-inner{{transform:rotateY(180deg)}}
.fc-face{{grid-area:1/1;backface-visibility:hidden;-webkit-backface-visibility:hidden;
 background:var(--paper2);border:1.5px solid var(--ink);padding:15px 16px 13px;
 box-shadow:4px 4px 0 var(--shadow);display:flex;flex-direction:column;gap:11px}}
.fc-back{{transform:rotateY(180deg);
 background-image:radial-gradient(circle at 1px 1px,rgba(43,74,139,.09) 1px,transparent 1.7px);
 background-size:6px 6px}}
/* backwards, not both: `both` pins the final keyframe forever and outranks the
   hover transform, which is why the lift silently never worked. */
.fc{{animation:fcin .42s cubic-bezier(.2,.8,.2,1) backwards}}
@keyframes fcin{{from{{opacity:0;transform:translateY(9px)}}to{{opacity:1;transform:none}}}}
.fc:hover .fc-inner{{transform:translateY(-3px)}}
.fc:hover input:checked ~ .fc-inner{{transform:translateY(-3px) rotateY(180deg)}}
.fc:focus-within .fc-face{{outline:2px solid var(--blue);outline-offset:2px}}

@media (prefers-reduced-motion: reduce){{
  #ground .bloom{{animation:none}}
  .fc,.fc-inner{{animation:none;transition:none}}
  .fc:hover .fc-inner{{transform:none}}
  .fc:hover input:checked ~ .fc-inner{{transform:rotateY(180deg)}}
  #genbtn{{transition:none}}
}}
"""


# --- rendering helpers -----------------------------------------------------


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


_SUN = (
    '<svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
    'stroke-width="1.5"><circle cx="8" cy="8" r="3"></circle><path d="M8 1.2v1.6M8 13.2v1.6'
    'M1.2 8h1.6M13.2 8h1.6M3.3 3.3l1.1 1.1M11.6 11.6l1.1 1.1M12.7 3.3l-1.1 1.1'
    'M4.4 11.6l-1.1 1.1"></path></svg>'
)
_MOON = (
    '<svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
    'stroke-width="1.5"><path d="M13.2 9.6A5.8 5.8 0 016.4 2.8a5.8 5.8 0 106.8 6.8z"></path></svg>'
)


def ticks_html(spent: int, cap: int = DAILY_CAP) -> str:
    """The ration strip: one mark per request in the day's allowance."""
    marks = []
    for index in range(cap):
        if index < spent:
            fill = "var(--orange)" if spent >= cap else "var(--blue)"
            edge = "var(--oranget)" if spent >= cap else "var(--blue)"
            marks.append(
                f'<i style="width:9px;height:20px;display:block;background:{fill};'
                f'border:1.5px solid {edge}"></i>'
            )
        else:
            marks.append(
                '<i style="width:9px;height:20px;display:block;'
                'border:1.5px solid var(--blue)"></i>'
            )
    return (
        '<div class="ticks" style="display:flex;gap:3px;margin:0;justify-content:flex-end;'
        f'flex-wrap:wrap">{"".join(marks)}</div>'
    )


def header_html(spent: int) -> str:
    left = max(0, DAILY_CAP - spent)
    note = (
        f'<b style="color:var(--ink);font-weight:600">{left}</b> of {DAILY_CAP} left '
        f"&middot; resets in {resets_in()}"
        if left
        else f"<b style=\"color:var(--oranget);font-weight:600\">none left</b> "
        f"&middot; resets in {resets_in()}"
    )
    return (
        # No "auto" radio: the absence of a choice is auto. A third radio
        # carrying `checked` relies on that attribute surviving Gradio's
        # re-render of the block, and it did not.
        '<input type="radio" name="fcmode" id="m-light">'
        '<input type="radio" name="fcmode" id="m-dark">'
        '<header class="hd" style="display:flex;align-items:flex-end;justify-content:space-between;'
        'gap:32px;padding-bottom:16px;border-bottom:3px solid var(--ink)">'
        "<div>"
        f'<h1 style="font-family:{DISP};font-size:64px;line-height:.86;margin:0;'
        'letter-spacing:-.012em;color:var(--ink);text-shadow:4px -3px 0 var(--orange)">'
        "Flashcards</h1>"
        f'<p style="margin:9px 0 0;font-family:{MONO};font-size:11px;letter-spacing:.16em;'
        'text-transform:uppercase;color:var(--mute)">notes in &middot; anki out</p></div>'
        # One right-aligned row rather than four stacked ones: the ration read
        # as a block of chrome when its label, strip and count each took a line.
        '<div class="meta">'
        '<div class="ration">'
        f'<span class="lbl" style="{LBL}">Daily ration</span>'
        f"{ticks_html(spent)}"
        f'<p class="rn" style="margin:0;font-family:{MONO};font-size:11px;'
        f'color:var(--ink2);white-space:nowrap">{note}</p></div>'
        '<div class="modes">'
        f'<label for="m-light" class="m lt">{_SUN}light</label>'
        f'<label for="m-dark" class="m dk">{_MOON}dark</label></div>'
        "</div></header>"
    )


def dtag(difficulty: str) -> str:
    """Marks plus the word.

    The count carries the level, so it survives greyscale, a screenshot, and
    colour blindness. Colour only reinforces it.
    """
    filled = DIFFICULTY.get(difficulty, 0)
    var = DIFF_VAR.get(difficulty, "--mute")
    marks = "".join(
        f'<i style="width:5px;height:10px;display:block;background:var({var})"></i>'
        if index < filled
        else '<i style="width:5px;height:10px;display:block;border:1px solid var(--rule)"></i>'
        for index in range(3)
    )
    return (
        f'<span style="font-family:{MONO};font-size:9.5px;letter-spacing:.11em;'
        f"text-transform:uppercase;display:inline-flex;align-items:center;gap:5px;"
        f'color:var({var})"><span style="display:inline-flex;gap:2px">{marks}</span>'
        f"{_esc(difficulty)}</span>"
    )


def _knock(inner: str, background: str = "var(--blue)") -> str:
    return (
        f'<div style="background:{background};color:var(--knockfg);'
        "border:1.5px solid var(--ink);padding:22px 26px;box-shadow:6px 6px 0 var(--ink);"
        f'font-family:{SERIF}">{inner}</div>'
    )


def render_estimate(chunks: int, tokens: int, rpm: int, spent: int) -> str:
    left = max(0, DAILY_CAP - spent)
    waiting = max(0, (chunks - rpm) * 12)
    over = chunks > left
    headline = (
        f"{chunks} chunk{'' if chunks == 1 else 's'} &middot; {chunks} "
        f"request{'' if chunks == 1 else 's'} &middot; ~{tokens:,} tokens"
    )
    if not over:
        verdict = (
            f"That is {chunks} of the {left} you have left today. "
            f"About {chunks * 5} cards."
        )
    elif left:
        verdict = (
            f"That is more than the {left} you have left today. Lower Max chunks "
            f"to {left}, or come back after the reset."
        )
    else:
        # "Lower Max chunks to 0" was the old wording here, which is advice that
        # cannot be taken and would not help if it could.
        verdict = (
            f"Today&rsquo;s twenty are gone. Preview stays free, but generating "
            f"has to wait {resets_in()} for the reset."
        )
    wait_line = (
        f" About {waiting}s of the run is waiting on the {rpm}-a-minute limit."
        if waiting
        else ""
    )
    body = (
        f'<span style="{LBL};color:rgba(251,249,242,.72)">Estimate &mdash; nothing spent</span>'
        f'<h2 style="font-family:{DISP};font-size:30px;margin:10px 0 6px;line-height:1.05;'
        f'color:var(--knockfg)">{headline}</h2>'
        f'<p style="margin:0;font-size:15px;line-height:1.5;color:var(--knockfg);opacity:.92">'
        f"{verdict}</p>"
    )
    return (
        _knock(body, "var(--oranget)" if over else "var(--blue)")
        + f'<p style="margin:14px 2px 0;font-family:{SERIF};font-size:13px;line-height:1.6;'
        f'color:var(--mute)">Tokens are estimated locally at four characters per token, '
        f"not measured by the API.{wait_line}</p>"
    )


def render_error(title: str, code: str, detail: str, steps: tuple[str, ...] = ()) -> str:
    code_html = (
        f'<span style="font-family:{MONO};font-size:11px;color:var(--mute)">{_esc(code)}</span>'
        if code
        else ""
    )
    rows = ""
    if steps:
        items = "".join(
            '<div style="display:flex;align-items:baseline;gap:14px;padding:10px 0;'
            'border-bottom:1px solid var(--rule2)">'
            f'<span style="font-family:{MONO};font-size:13px;color:var(--blue);width:14px">'
            f"{index}</span>"
            f'<span style="font-size:14.5px;color:var(--ink2);line-height:1.5">{step}</span></div>'
            for index, step in enumerate(steps, 1)
        )
        rows = (
            f'<div style="padding-top:18px"><span style="{LBL}">What you can do</span>'
            f'<div style="padding-top:6px">{items}</div></div>'
        )
    return (
        f'<div style="font-family:{SERIF}">'
        '<div style="border:1.5px solid var(--ink);border-left:5px solid var(--hard);'
        "background:var(--paper2);padding:18px 22px;box-shadow:4px 4px 0 var(--shadow);"
        'display:flex;flex-direction:column;gap:7px">'
        '<div style="display:flex;align-items:baseline;gap:10px">'
        f'<span style="font-size:19px;font-weight:600;color:var(--ink)">{_esc(title)}</span>'
        f"{code_html}</div>"
        f'<p style="margin:0;font-size:14.5px;line-height:1.6;color:var(--ink2)">{detail}</p>'
        f"</div>{rows}</div>"
    )


def render_quota_spent(spent: int, kept: int) -> str:
    """The daily cap is a weekly event on this tier, not an exception.

    So it gets a designed state that says what still works rather than a red
    box that reads as a fault.
    """
    body = (
        f'<span style="{LBL};color:rgba(251,249,242,.7)">Daily ration spent</span>'
        f'<h2 style="font-family:{DISP};font-size:40px;margin:10px 0 8px;line-height:1;'
        f'color:var(--knockfg)">That is today&rsquo;s twenty.</h2>'
        f'<p style="margin:0;font-size:16px;line-height:1.55;color:var(--knockfg);opacity:.92">'
        f"The free tier resets in {resets_in()}. Nothing is lost &mdash; "
        f"{'the ' + str(kept) + ' cards already generated are still below' if kept else 'your notes are still here'}."
        "</p>"
    )
    return (
        _knock(body, "var(--ink)")
        + '<div style="display:flex;gap:16px;margin-top:20px;flex-wrap:wrap">'
        '<div style="flex:1 1 240px;border:1.5px solid var(--ink);background:var(--paper2);'
        'padding:16px 20px">'
        f'<span style="{LBL}">Still free</span>'
        f'<p style="margin:8px 0 0;font-family:{SERIF};font-size:15px;line-height:1.5;'
        'color:var(--ink2)">Preview keeps working. It never calls the API, so you can size '
        "tomorrow&rsquo;s run now.</p></div>"
        '<div style="flex:1 1 240px;border:1.5px solid var(--ink);background:var(--paper2);'
        'padding:16px 20px">'
        f'<span style="{LBL}">Still yours</span>'
        f'<p style="margin:8px 0 0;font-family:{SERIF};font-size:15px;line-height:1.5;'
        f'color:var(--ink2)">Everything generated today is still on the page and still '
        "exportable.</p></div></div>"
    )


def render_progress(
    rows: list[list[str]], extra: list[list[str]], waiting: str = ""
) -> str:
    """A per-chunk ledger rather than a spinner.

    At five requests a minute a run visibly stalls between calls. Naming the
    pause is the whole fix: dead air only reads as broken when nothing on the
    page accounts for it.
    """
    out = []
    for name, state, meta in rows + extra:
        colour, mark = {
            "done": ("var(--easy)", "&#9632; done"),
            "active": ("var(--blue)", "&#9632; calling&hellip;"),
            "skipped": ("var(--mute)", "&#9633; skipped"),
        }.get(state, ("var(--mute)", "&#9633; queued"))
        dim = "opacity:.55;" if state == "queued" else ""
        meta_html = (
            f'<span style="font-family:{MONO};font-size:11px;color:var(--mute);'
            f'white-space:nowrap">{_esc(meta)}</span>'
            if meta
            else ""
        )
        out.append(
            '<div style="display:flex;justify-content:space-between;align-items:center;'
            f'gap:16px;padding:12px 0;border-bottom:1px solid var(--rule2);{dim}">'
            f'<span style="font-size:15px;flex:1;min-width:0;color:var(--ink)">'
            f"{_esc(name)}</span>"
            f'<span style="font-family:{MONO};font-size:11px;color:{colour};'
            f'white-space:nowrap">{mark}</span>{meta_html}</div>'
        )
    wait_block = ""
    if waiting:
        wait_block = (
            '<div style="margin-top:20px;border:1.5px solid var(--oranget);'
            "background:var(--warmbg);padding:15px 19px;display:flex;gap:14px;"
            'align-items:flex-start">'
            f'<span style="font-family:{MONO};font-size:20px;color:var(--oranget);'
            'line-height:1">&#8987;</span><div>'
            f'<p style="margin:0 0 4px;font-size:15px;font-weight:500;color:var(--ink)">'
            f"{_esc(waiting)}</p>"
            f'<p style="margin:0;font-size:13.5px;line-height:1.55;color:var(--ink2)">'
            "This pause is the rate limiter, not a stall. The next chunk starts on its "
            "own.</p></div></div>"
        )
    return (
        f'<div style="font-family:{SERIF}">'
        f'<span style="{LBL};display:block;margin-bottom:10px">Progress</span>'
        f'{"".join(out)}{wait_block}</div>'
    )


def render_summary(
    cards: int, chunks: int, dropped: int, duplicates: int, requests: int, cached: int
) -> str:
    stats = "".join(
        # The colour is repeated on every span: without it Gradio's own theme
        # text colour wins over the inherited value and this renders near-white.
        f'<span style="font-family:{MONO};font-size:12px;color:var(--ink2)">'
        f'<b style="font-size:19px;color:var(--ink);font-weight:600">{value}</b> {label}</span>'
        for value, label in (
            (cards, "cards"),
            (chunks, "chunk" if chunks == 1 else "chunks"),
            (duplicates, "duplicates"),
            (requests, "requests"),
        )
    )
    return (
        f'<div style="font-family:{SERIF};display:flex;justify-content:space-between;'
        "align-items:center;gap:20px;flex-wrap:wrap;border-bottom:1.5px solid var(--ink);"
        'padding-bottom:12px">'
        f'<div style="display:flex;gap:28px;flex-wrap:wrap">{stats}</div>'
        f'<span style="font-family:{MONO};font-size:10px;letter-spacing:.12em;'
        f'text-transform:uppercase;color:var(--mute)">dropped {dropped} &middot; '
        f"cached {cached}</span></div>"
    )


def render_cards(entries: list[SourcedCard]) -> str:
    if not entries:
        return ""
    blocks = []
    for index, entry in enumerate(entries):
        card = entry.card
        # Stagger the entrance so a dozen cards arrive as a wave, not a slab.
        delay = f"animation-delay:{min(index, 11) * 42}ms"
        head = (
            '<div style="display:flex;justify-content:space-between;align-items:center;'
            "gap:10px;padding-bottom:8px;border-bottom:1px solid var(--rule2);"
            'flex-shrink:0">'
            f'<span style="{LBL}">{_esc(card.topic)}</span>{dtag(card.difficulty)}</div>'
        )
        blocks.append(
            f'<label class="fc" style="{delay}"><input type="checkbox">'
            f'<div class="fc-inner">'
            f'<div class="fc-face">{head}'
            f'<p style="margin:0;font-size:16.5px;font-weight:500;line-height:1.45;'
            f'color:var(--ink);text-wrap:pretty;flex-grow:1">{_esc(card.question)}</p>'
            f'<span style="{LBL};color:var(--blue);flex-shrink:0">flip for answer</span></div>'
            f'<div class="fc-face fc-back">{head}'
            f'<p style="margin:0;font-size:14.5px;line-height:1.62;color:var(--ink2);'
            f'text-wrap:pretty;flex-grow:1">{_esc(card.answer)}</p>'
            f'<span style="{LBL};color:var(--blue);flex-shrink:0">flip back</span></div>'
            "</div></label>"
        )
    return (
        '<div style="padding-top:20px;display:grid;'
        "grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;"
        f'align-items:start">{"".join(blocks)}</div>'
    )


def render_partial(failures: list[str]) -> str:
    lines = "".join(
        f'<p style="margin:5px 0 0;font-family:{MONO};font-size:12px;line-height:1.55;'
        f'color:var(--ink2)">{_esc(failure)}</p>'
        for failure in failures
    )
    count = len(failures)
    return (
        f'<div style="font-family:{SERIF};padding-top:18px">'
        '<div style="border:1.5px solid var(--ink);border-left:5px solid var(--hard);'
        'background:var(--paper2);padding:15px 19px">'
        f'<span style="font-size:16px;font-weight:600;color:var(--ink)">'
        f'{count} chunk{"" if count == 1 else "s"} produced nothing</span>{lines}</div></div>'
    )


EMPTY_RESULTS = (
    f'<div style="font-family:{SERIF}">'
    f'<span style="{LBL};display:block;margin-bottom:14px">What you will get</span>'
    '<div style="border:1.5px dashed var(--rule);padding:30px 32px;background:var(--paper2)">'
    '<div style="display:flex;gap:34px;align-items:flex-start;flex-wrap:wrap">'
    '<div style="flex:0 0 260px;border:1.5px solid var(--rule);padding:15px 16px;'
    'background:var(--paper)">'
    '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;'
    'padding-bottom:8px;border-bottom:1px solid var(--rule2)">'
    f'<span style="{LBL}">Topic</span>'
    f'<span style="font-family:{MONO};font-size:9.5px;letter-spacing:.11em;'
    'text-transform:uppercase;color:var(--mute)">difficulty</span></div>'
    '<p style="margin:11px 0 0;font-size:16.5px;line-height:1.45;color:var(--mute)">'
    "The question, answerable on its own without the notes beside it.</p>"
    f'<p style="margin:11px 0 0;{LBL};color:var(--rule)">flip for answer</p></div>'
    '<div style="flex:1 1 300px">'
    '<p style="margin:0 0 14px;font-size:18px;line-height:1.5;color:var(--ink)">'
    "Every card carries a question, an answer on the back, the topic it came from, "
    "and a difficulty. Flip them here, or export the set and import it into Anki.</p>"
    '<ol style="margin:0;padding-left:18px;font-size:14.5px;line-height:1.9;'
    'color:var(--ink2)">'
    "<li>Paste notes, or upload a .md / .txt file.</li>"
    "<li>Press <b style=\"color:var(--ink)\">Preview</b> to see what it will cost. "
    "It calls nothing.</li>"
    "<li>Press <b style=\"color:var(--ink)\">Generate</b> when the estimate looks right.</li>"
    "</ol></div></div></div></div>"
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
    f'<div style="font-family:{SERIF};border:1.5px solid var(--ink);'
    'border-left:5px solid var(--mute);background:var(--paper2);padding:18px 22px">'
    '<p style="margin:0;font-size:17px;font-weight:600;color:var(--ink)">Nothing to do</p>'
    '<p style="margin:7px 0 0;font-size:14.5px;line-height:1.6;color:var(--ink2)">'
    "Paste notes on the left or upload a .md or .txt file. Preview will tell you what "
    "it costs before anything is spent.</p></div>"
)

_NO_KEY_STEPS = (
    "Put your key in a file called .env beside the app",
    "Restart the app once it is set",
    "The file is gitignored, so the key stays on this machine",
)

_RATE_STEPS = (
    "Wait a minute, then press Generate again",
    "Lower Max chunks so fewer calls go out at once",
)


DEFAULT_MAX_CHUNKS = 5


def chunk_limit(value: object) -> int:
    """Coerce the Max chunks field into a usable positive limit.

    Gradio hands back None when the number box is cleared and a string when it
    holds something unparsable, and int() raised on both -- surfacing in the UI
    as a bare "Error" with nothing to act on. Zero or a negative would also
    slice the chunk list from the wrong end, silently dropping work.
    """
    try:
        limit = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_MAX_CHUNKS
    return max(1, limit)


def chunk_label(chunk: Chunk) -> str:
    return chunk.heading or chunk.source_path.stem


# --- gradio handlers -------------------------------------------------------


def preview(notes_text: str, files: list[str] | None, max_chunks: float):
    """Costs nothing, so it is the move the design invites first."""
    generate_label = gr.update()
    try:
        settings = load_settings()
    except ConfigError as exc:
        return (
            render_error("No API key", "", _esc(str(exc)), _NO_KEY_STEPS),
            generate_label,
            header_html(0),
        )

    chunks = gather_chunks(notes_text, files, settings)[: chunk_limit(max_chunks)]
    spent = spent_today(settings)
    if not chunks:
        return NO_INPUT, generate_label, header_html(spent)

    tokens = sum(estimate_tokens(chunk.text) for chunk in chunks)
    left = max(0, DAILY_CAP - spent)
    return (
        render_estimate(len(chunks), tokens, settings.requests_per_minute, spent),
        # The cost rides on the button itself, so pressing Generate is a
        # considered act rather than a reflex.
        gr.update(
            value=f"Generate · spends {len(chunks)} of your {left}"
            if left
            else "Generate · nothing left today"
        ),
        header_html(spent),
    )


def generate(
    notes_text: str, files: list[str] | None, max_chunks: float, use_dedupe: bool
):
    hide = gr.update(visible=False)

    try:
        settings = load_settings()
    except ConfigError as exc:
        yield (
            header_html(0),
            render_error("No API key", "", _esc(str(exc)), _NO_KEY_STEPS),
            "",
            hide,
        )
        return

    spent = spent_today(settings)
    chunks = gather_chunks(notes_text, files, settings)[: chunk_limit(max_chunks)]
    if not chunks:
        yield header_html(spent), NO_INPUT, "", hide
        return

    rpm = settings.requests_per_minute
    rows = [[chunk_label(chunk), "queued", ""] for chunk in chunks]
    extra: list[list[str]] = []
    if use_dedupe:
        extra.append(["Remove near-duplicates", "queued", ""])
    extra.append(["Write CSV", "queued", ""])

    client = GeminiClient(settings)
    outcome = Outcome(chunks=len(chunks))

    for index, chunk in enumerate(chunks):
        rows[index][1] = "active"
        waiting = (
            f"Waiting for the {rpm}-a-minute limit." if index and index % rpm == 0 else ""
        )
        yield (
            header_html(spent_today(settings)),
            render_progress(rows, extra, waiting),
            render_cards(outcome.entries),
            hide,
        )

        result = pipeline.run([chunk], settings, client)
        if result.api_error is not None:
            exc = result.api_error
            spent = spent_today(settings)
            if is_daily_cap(exc):
                status = render_quota_spent(spent, len(outcome.entries))
            else:
                detail = (
                    f"{_esc(str(exc.message))} Your notes and any cards already "
                    "generated are still here."
                )
                status = render_error(
                    "Rate limited" if exc.code == 429 else "API error",
                    f"HTTP {exc.code}",
                    detail,
                    _RATE_STEPS if exc.code == 429 else (),
                )
            yield (
                header_html(spent),
                status,
                render_cards(outcome.entries),
                hide,
            )
            return

        outcome.entries.extend(result.cards)
        outcome.dropped += result.dropped
        outcome.failures.extend(result.failures)
        rows[index][1] = "done"
        rows[index][2] = f"{len(result.cards)} cards"
        yield (
            header_html(spent_today(settings)),
            render_progress(rows, extra),
            render_cards(outcome.entries),
            hide,
        )

    if use_dedupe:
        extra[0][1] = "active"
        yield (
            header_html(spent_today(settings)),
            render_progress(rows, extra),
            render_cards(outcome.entries),
            hide,
        )
        try:
            kept, dropped = dedupe.deduplicate(
                outcome.entries, settings.similarity_threshold, settings.embedding_model
            )
            outcome.entries, outcome.duplicates = kept, len(dropped)
            extra[0][1], extra[0][2] = "done", f"-{len(dropped)}"
        except dedupe.DedupeUnavailable as exc:
            outcome.dedupe_note = str(exc)
            extra[0][1] = "skipped"

    extra[-1][1] = "done"
    outcome.csv_path = write_csv(outcome.entries)
    outcome.requests = client.request_count
    outcome.cache_hits = client.cache_hits
    # Cached replies never reach _call_with_retry, so they never counted.
    spent = spent_today(settings)

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
            f'color:var(--mute)">Dedupe skipped: {_esc(outcome.dedupe_note)}</p>'
        )

    yield (
        header_html(spent),
        summary,
        render_cards(outcome.entries),
        gr.update(value=outcome.csv_path, visible=True),
    )


# --- ui --------------------------------------------------------------------

GROUND = (
    '<div id="ground"><div class="bloom b1"></div><div class="bloom b2"></div>'
    '<div class="grain"></div></div>'
)


def initial_spent() -> int:
    try:
        return spent_today(load_settings())
    except ConfigError:
        return 0


def refresh_header() -> str:
    """Re-read the count on every page load.

    header_html() is evaluated once when the Blocks are built, so without this
    the strip froze at whatever the count was when the server booted. A CLI or
    benchmark run spends from the same twenty and would never have shown up.
    """
    return header_html(initial_spent())


with gr.Blocks(title="Flashcards") as demo:
    gr.HTML(GROUND, elem_id="groundwrap")
    header = gr.HTML(header_html(initial_spent()))

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
                    value=DEFAULT_MAX_CHUNKS,
                    minimum=1,
                    precision=0,
                    elem_id="maxchunks",
                )
                use_dedupe = gr.Checkbox(
                    label="Remove near-duplicates",
                    value=True,
                    elem_id="dedupe",
                )

            preview_button = gr.Button("Preview — free", elem_id="previewbtn")
            generate_button = gr.Button("Generate", elem_id="genbtn")

        with gr.Column(elem_id="right"):
            status = gr.HTML(EMPTY_RESULTS)
            download = gr.DownloadButton(
                "DOWNLOAD CSV", visible=False, elem_id="dlbtn"
            )
            cards = gr.HTML()

    demo.load(refresh_header, outputs=header)
    preview_button.click(
        preview,
        inputs=[notes_input, file_input, max_chunks],
        outputs=[status, generate_button, header],
    )
    generate_button.click(
        generate,
        inputs=[notes_input, file_input, max_chunks, use_dedupe],
        outputs=[header, status, cards, download],
    )


if __name__ == "__main__":
    # server_port is passed only when PORT is set. Gradio otherwise resolves the
    # host and port from GRADIO_SERVER_NAME / GRADIO_SERVER_PORT.
    port = os.environ.get("PORT")
    demo.launch(css=CSS, **({"server_port": int(port)} if port else {}))
