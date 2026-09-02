"""Generate the Press Room artboards from one definition.

Every artboard shares the same CSS core, so it lives in _core.css and is
inlined here rather than pasted thirteen times. Editing a token in one place
is the whole point; the .dc.html files are build output, not sources.
"""

from __future__ import annotations

import json
from pathlib import Path

from contrast import DARK as PAL_DARK, LIGHT as PAL_LIGHT, ratio

HERE = Path(__file__).parent
CORE = (HERE / "_core.css").read_text(encoding="utf-8")

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=IBM+Plex+Mono:wght@400;500;600&family=Instrument+Serif:ital@0;1&"
    'family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap">'
)

SHELL = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  {fonts}
  <style>
{css}
{extra}
  </style>
</helmet>
{body}
</x-dc>
</body>
</html>
"""


def write(name: str, body: str, extra: str = "") -> None:
    (HERE / f"{name}.dc.html").write_text(
        SHELL.format(fonts=FONTS, css=CORE, extra=extra, body=body), encoding="utf-8"
    )


# --- shared fragments ------------------------------------------------------


def ticks(used: int, total: int = 20, hot: bool = False) -> str:
    cls = "hot" if hot else "on"
    return "".join(
        f'<i class="{cls}"></i>' if i < used else "<i></i>" for i in range(total)
    )


def header(used: int, note: str, hot: bool = False, title: str = "Flashcards") -> str:
    return f"""<header class="hd">
    <div>
      <h1 class="ttl">{title}</h1>
      <p class="sub">notes in &middot; anki out</p>
    </div>
    <div class="ration">
      <div class="modes">
        <span class="m lt"><svg width="10" height="10" viewBox="0 0 16 16" fill="none"
          stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="3"/><path d="M8 1.2v1.6
          M8 13.2v1.6M1.2 8h1.6M13.2 8h1.6M3.3 3.3l1.1 1.1M11.6 11.6l1.1 1.1M12.7 3.3l-1.1 1.1
          M4.4 11.6l-1.1 1.1"/></svg>light</span><span class="m dk"><svg width="10" height="10"
          viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path
          d="M13.2 9.6A5.8 5.8 0 016.4 2.8a5.8 5.8 0 106.8 6.8z"/></svg>dark</span>
      </div>
      <span class="lbl">Daily ration</span>
      <div class="ticks">{ticks(used, hot=hot)}</div>
      <p class="rn">{note}</p>
    </div>
  </header>"""


DIFFS = {"easy": 1, "medium": 2, "hard": 3}


def diff(level: str) -> str:
    marks = "".join("<i></i>" for _ in range(DIFFS[level]))
    return f'<span class="diff d-{level[:4].rstrip("i")}"><span class="ds">{marks}</span>{level}</span>'


def _dcls(level: str) -> str:
    return {"easy": "easy", "medium": "med", "hard": "hard"}[level]


def dtag(level: str) -> str:
    marks = "".join("<i></i>" for _ in range(DIFFS[level]))
    return (
        f'<span class="diff d-{_dcls(level)}">'
        f'<span class="ds">{marks}</span>{level}</span>'
    )


def card(topic: str, q: str, level: str) -> str:
    return f"""<article class="card">
        <div class="ctop"><span class="topic">{topic}</span>{dtag(level)}</div>
        <p class="q">{q}</p>
        <div class="cfoot">flip for answer</div>
      </article>"""


CARDS = [
    ("Operating Systems", "What are the four Coffman conditions for deadlock?", "hard"),
    ("Operating Systems", "Why is breaking one Coffman condition enough to prevent deadlock?", "medium"),
    ("Databases", "What is an update anomaly?", "easy"),
    ("Databases", "How does BCNF differ from 3NF?", "hard"),
    ("Networks", "What problem does flow control solve that congestion control does not?", "medium"),
    ("Networks", "Why does TCP treat packet loss as its congestion signal?", "medium"),
    ("Thermodynamics", "What does the zeroth law establish?", "easy"),
    ("Operating Systems", "When is the ostrich algorithm a legitimate choice?", "medium"),
]

NOTES_TEXT = (
    "# Deadlocks in Operating Systems<br><br>A deadlock is a state in which a set "
    "of processes are each waiting for an event that only another process in the "
    "set can cause. None of them can proceed, and without intervention the system "
    "stays stuck indefinitely.<br><br>## The four Coffman conditions<br><br>"
    "Deadlock can arise only when all four of these hold simultaneously&hellip;"
)


def form(
    notes: str,
    chunks_note: str,
    gen_label: str = "Generate",
    gen_cost: str = "spends 4 of your 20",
    disabled: bool = False,
) -> str:
    gen_style = ' style="opacity:.4"' if disabled else ""
    return f"""<div class="field">
        <span class="lbl" style="margin-bottom:7px">Notes</span>
        <div class="ta">{notes}</div>
      </div>
      <div class="field acc"><span>Upload .md or .txt</span><span>+</span></div>
      <div class="field row2">
        <label style="flex:1">
          <span class="lbl" style="margin-bottom:6px">Max chunks</span>
          <div class="inp">5</div>
        </label>
        <label class="chk" style="padding-bottom:10px">
          <span class="box"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"
            stroke="#fbf9f2" stroke-width="1.8"><path d="M1 4.6L3.4 7L8 1.8"/></svg></span>
          Remove near-duplicates
        </label>
      </div>
      <p class="rn" style="margin:0 0 14px;color:var(--mute);font-size:11px">{chunks_note}</p>
      <div class="btn btn-prev" style="margin-bottom:12px">Preview &mdash; free</div>
      <div class="btn btn-gen"{gen_style}>{gen_label}<span class="cost">{gen_cost}</span></div>"""


def page(width: int, inner: str) -> str:
    return f"""<div class="wrap" style="width:{width}px">
  <div class="grain"></div>
  <div class="rel">
{inner}
  </div>
</div>"""


# --- artboards -------------------------------------------------------------


def build_main() -> None:
    cards = "\n      ".join(card(*c) for c in CARDS)
    write(
        "Main",
        page(
            1440,
            f"""{header(7, "<b>13</b> of 20 left &middot; resets 12:30")}
    <div class="main">
      <div class="left">
        {form(NOTES_TEXT, "4 chunks &middot; 4 requests &middot; ~2,400 tokens")}
      </div>
      <div class="right">
        <div class="summary">
          <div style="display:flex;gap:34px">
            <span class="stat"><b>19</b> cards</span>
            <span class="stat"><b>4</b> chunks</span>
            <span class="stat"><b>3</b> duplicates dropped</span>
            <span class="stat"><b>4</b> requests spent</span>
          </div>
          <span class="btn-dl">Download CSV</span>
        </div>
        <div class="grid">
      {cards}
        </div>
      </div>
    </div>""",
        ),
    )


def build_empty() -> None:
    write(
        "Empty",
        page(
            1440,
            f"""{header(0, "<b>20</b> of 20 left &middot; full ration")}
    <div class="main">
      <div class="left">
        {form('<span class="ph">Paste lecture notes here&hellip;</span>',
              "Preview costs nothing. Run it as often as you like.",
              gen_cost="paste notes first", disabled=True)}
      </div>
      <div class="right">
        <span class="lbl" style="margin-bottom:14px">What you will get</span>
        <div style="border:1.5px dashed var(--rule);padding:34px 38px;background:var(--paper2)">
          <div style="display:flex;gap:38px;align-items:flex-start">
            <div style="flex:0 0 300px;border:1.5px solid var(--rule);padding:16px 17px 14px;
              background:var(--paper)">
              <div class="ctop"><span class="topic">Topic</span>
                <span class="diff" style="color:var(--mute)">
                  <span class="ds"><i style="background:var(--rule)"></i>
                  <i style="background:var(--rule)"></i></span>difficulty</span></div>
              <p class="q" style="color:var(--mute)">The question, answerable on its own
                without the notes beside it.</p>
              <div class="cfoot" style="color:var(--rule)">flip for answer</div>
            </div>
            <div style="flex:1">
              <p style="margin:0 0 16px;font-size:19px;line-height:1.5;max-width:44ch">
                Every card carries a question, an answer on the back, the topic it came
                from, and a difficulty. Flip them here, or export the set as a CSV and
                import it into Anki.</p>
              <ul style="margin:0;padding-left:18px;font-size:14.5px;line-height:1.85;
                color:var(--ink2);max-width:46ch">
                <li>Paste notes, or upload a <span style="font-family:var(--mono);
                  font-size:13px">.md</span> / <span style="font-family:var(--mono);
                  font-size:13px">.txt</span> file.</li>
                <li>Press <b>Preview</b> to see what it will cost. It calls nothing.</li>
                <li>Press <b>Generate</b> when the estimate looks right.</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>""",
        ),
    )


def build_pasted() -> None:
    write(
        "Pasted",
        page(
            1440,
            f"""{header(7, "<b>13</b> of 20 left &middot; resets 12:30")}
    <div class="main">
      <div class="left">
        {form(NOTES_TEXT, "Not costed yet &mdash; press Preview.",
              gen_cost="cost unknown until you preview")}
      </div>
      <div class="right">
        <div style="border:1.5px dashed var(--rule);padding:64px 40px;background:var(--paper2);
          text-align:center">
          <p style="margin:0 0 10px;font-family:var(--disp);font-size:30px;line-height:1.1">
            2,180 characters pasted.</p>
          <p style="margin:0;font-size:15.5px;color:var(--ink2);max-width:40ch;
            margin-inline:auto;line-height:1.6">
            Preview will tell you how many chunks that splits into and what it will
            cost, without spending anything.</p>
        </div>
      </div>
    </div>""",
        ),
    )


def build_preview() -> None:
    rows = [
        ("Deadlocks in Operating Systems", "53 tok", True),
        ("The four Coffman conditions", "157 tok", False),
        ("Prevention versus avoidance", "224 tok", False),
        ("Detection and recovery", "157 tok", False),
    ]
    body = "\n          ".join(
        f"""<div style="display:flex;justify-content:space-between;gap:16px;padding:11px 0;
            border-bottom:1px solid var(--rule2)">
            <span style="font-size:15px">{name}</span>
            <span style="font-family:var(--mono);font-size:12px;color:{'var(--oranget)' if small else 'var(--mute)'}">
              {tok}{' &middot; thin' if small else ''}</span></div>"""
        for name, tok, small in rows
    )
    write(
        "Preview",
        page(
            1440,
            f"""{header(7, "<b>13</b> of 20 left &middot; resets 12:30")}
    <div class="main">
      <div class="left">
        {form(NOTES_TEXT, "4 chunks &middot; 4 requests &middot; ~2,400 tokens")}
      </div>
      <div class="right">
        <div class="knock" style="margin-bottom:22px">
          <span class="lbl" style="color:rgba(251,249,242,.72)">Estimate &mdash; nothing spent</span>
          <h2 style="margin-top:10px">4 chunks &middot; 4 requests &middot; ~2,400 tokens</h2>
          <p style="margin:6px 0 16px;font-size:15px;color:rgba(251,249,242,.9)">
            That is 4 of the 13 you have left today. About 20 cards.</p>
          <div class="ticks" style="justify-content:flex-start;margin:0">
            {ticks(7).replace('class="on"', 'class="on" style="border-color:#fbf9f2;background:rgba(251,249,242,.35)"')}
          </div>
          <p style="margin:10px 0 0;font-family:var(--mono);font-size:11px;
            color:rgba(251,249,242,.82)">
            &#9632; already spent &nbsp; &#9633; still yours</p>
        </div>
        <span class="lbl" style="margin-bottom:10px">How it splits</span>
        <div>
          {body}
        </div>
        <p style="margin:16px 0 0;font-size:14px;color:var(--ink2);max-width:52ch;line-height:1.6">
          One chunk is thin &mdash; a 53-token preamble before the first heading. It still
          costs a full request. Trim it, or accept a weaker card or two.</p>
      </div>
    </div>""",
        ),
    )


def build_generating() -> None:
    rows = [
        ("Deadlocks in Operating Systems", "done", "5 cards", "3.0s"),
        ("The four Coffman conditions", "done", "5 cards", "2.8s"),
        ("Prevention versus avoidance", "running", "", ""),
        ("Detection and recovery", "queued", "", ""),
    ]
    out = []
    for name, state, cards_n, secs in rows:
        if state == "done":
            mark = ('<span style="font-family:var(--mono);font-size:11px;color:var(--easy)">'
                    "&#9632; done</span>")
            right = (f'<span style="font-family:var(--mono);font-size:11px;color:var(--mute)">'
                     f"{cards_n} &middot; {secs}</span>")
            op = ""
        elif state == "running":
            mark = ('<span style="font-family:var(--mono);font-size:11px;color:var(--blue)">'
                    '<span class="pulse">&#9632;</span> calling&hellip;</span>')
            right = ('<span style="font-family:var(--mono);font-size:11px;color:var(--mute)">'
                     "~3s</span>")
            op = ""
        else:
            mark = ('<span style="font-family:var(--mono);font-size:11px;color:var(--mute)">'
                    "&#9633; queued</span>")
            right = ""
            op = "opacity:.5;"
        out.append(
            f"""<div style="display:flex;justify-content:space-between;align-items:center;gap:16px;
            padding:13px 0;border-bottom:1px solid var(--rule2);{op}">
            <span style="font-size:15px;flex:1">{name}</span>{mark}{right}</div>"""
        )
    write(
        "Generating",
        page(
            1440,
            f"""{header(9, "<b>11</b> of 20 left &middot; spending now", hot=True)}
    <div class="main">
      <div class="left">
        {form(NOTES_TEXT, "4 chunks &middot; 4 requests &middot; ~2,400 tokens",
              gen_label="Generating&hellip;", gen_cost="2 of 4 done", disabled=True)}
      </div>
      <div class="right">
        <span class="lbl" style="margin-bottom:12px">Progress</span>
        {"".join(out)}
        <div style="margin-top:22px;border:1.5px solid var(--oranget);background:#fdf0e8;
          padding:16px 20px;display:flex;gap:14px;align-items:flex-start">
          <span style="font-family:var(--mono);font-size:22px;color:var(--oranget);
            line-height:1">&#8987;</span>
          <div>
            <p style="margin:0 0 4px;font-size:15.5px;font-weight:500">
              Waiting 24s for the rate limit.</p>
            <p style="margin:0;font-size:14px;color:var(--ink2);line-height:1.55;max-width:52ch">
              The free tier allows 5 calls a minute. This pause is the limiter, not a
              stall &mdash; the next chunk starts on its own.</p>
          </div>
        </div>
      </div>
    </div>""",
        ),
        extra="""
.pulse{animation:pl 1.1s ease-in-out infinite}
@keyframes pl{0%,100%{opacity:1}50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){.pulse{animation:none}}""",
    )


def build_partial() -> None:
    cards = "\n      ".join(card(*c) for c in CARDS[:5])
    write(
        "Partial",
        page(
            1440,
            f"""{header(11, "<b>9</b> of 20 left &middot; resets 12:30")}
    <div class="main">
      <div class="left">
        {form(NOTES_TEXT, "4 chunks &middot; 4 requests &middot; ~2,400 tokens")}
      </div>
      <div class="right">
        <div class="summary">
          <div style="display:flex;gap:34px">
            <span class="stat"><b>12</b> cards</span>
            <span class="stat"><b>3</b> of 4 chunks</span>
            <span class="stat"><b>4</b> requests spent</span>
          </div>
          <span class="btn-dl">Download CSV</span>
        </div>
        <div style="border-left:4px solid var(--hard);background:#fbf1ee;padding:14px 18px;
          margin-bottom:20px">
          <p style="margin:0 0 6px;font-size:15px;font-weight:500">
            One chunk produced nothing.</p>
          <p style="margin:0;font-family:var(--mono);font-size:12px;color:var(--ink2);
            line-height:1.6">
            Detection and recovery &mdash; reply cut off at MAX_TOKENS.<br>
            The other three are below. Re-running costs 1 more request.</p>
        </div>
        <div class="grid">
      {cards}
        </div>
      </div>
    </div>""",
        ),
    )


def build_quota() -> None:
    write(
        "QuotaSpent",
        page(
            1440,
            f"""{header(20, "<b>0</b> of 20 left", hot=True)}
    <div style="margin-top:34px;max-width:none">
      <div class="knock" style="background:var(--ink);display:flex;gap:44px;align-items:flex-start">
        <div style="flex:1">
          <span class="lbl" style="color:rgba(251,249,242,.7)">Daily ration spent</span>
          <h2 style="margin:12px 0 10px;font-size:52px">That is today's twenty.</h2>
          <p style="margin:0;font-size:17px;line-height:1.6;color:rgba(251,249,242,.92);
            max-width:52ch">
            The free tier resets at <span style="font-family:var(--mono)">12:30</span>,
            in 4 hours 12 minutes. Nothing is lost &mdash; everything you generated today
            is still here.</p>
        </div>
        <div style="flex:0 0 300px">
          <div class="ticks" style="justify-content:flex-start;flex-wrap:wrap;gap:4px;margin:0">
            {ticks(20, hot=True)}
          </div>
        </div>
      </div>
      <div style="display:flex;gap:20px;margin-top:26px">
        <div style="flex:1;border:1.5px solid var(--ink);background:var(--paper2);padding:20px 24px">
          <span class="lbl">Still free</span>
          <p style="margin:9px 0 14px;font-size:16px;line-height:1.5">
            Preview keeps working. It never calls the API, so you can plan tomorrow's run now.</p>
          <span class="btn-prev" style="display:inline-block;width:auto;padding:11px 22px">
            Preview &mdash; free</span>
        </div>
        <div style="flex:1;border:1.5px solid var(--ink);background:var(--paper2);padding:20px 24px">
          <span class="lbl">Still yours</span>
          <p style="margin:9px 0 14px;font-size:16px;line-height:1.5">
            The 34 cards from today are still on the page and still exportable.</p>
          <span class="btn-dl">Download CSV</span>
        </div>
      </div>
    </div>""",
        ),
    )


def build_errors() -> None:
    items = [
        ("No API key", "GEMINI_API_KEY is not set",
         "Put your key in a file called <span style='font-family:var(--mono)'>.env</span> "
         "beside the app, then restart it. The file is gitignored, so the key stays local.",
         "var(--hard)"),
        ("File not readable", "notes.pdf is not a .md or .txt file",
         "Only plain text and Markdown are supported. Export the PDF to text first, or paste "
         "the content straight into the box.", "var(--med)"),
        ("Nothing to do", "The notes box is empty",
         "Paste some notes or upload a file. Preview will tell you what it costs before "
         "anything is spent.", "var(--mute)"),
    ]
    blocks = "\n      ".join(
        f"""<div style="border:1.5px solid var(--ink);border-left:5px solid {colour};
        background:var(--paper2);padding:20px 24px;box-shadow:4px 4px 0 var(--rule)">
        <span class="lbl">{title}</span>
        <p style="margin:9px 0 8px;font-family:var(--mono);font-size:14px;color:{colour}">{msg}</p>
        <p style="margin:0;font-size:15px;line-height:1.6;color:var(--ink2);max-width:60ch">{fix}</p>
      </div>"""
        for title, msg, fix, colour in items
    )
    write(
        "Errors",
        page(
            1440,
            f"""{header(7, "<b>13</b> of 20 left &middot; resets 12:30")}
    <div style="margin-top:32px">
      <span class="lbl" style="margin-bottom:16px">Error states &mdash; each says what to do next</span>
      <div style="display:grid;gap:18px;max-width:900px">
      {blocks}
      </div>
    </div>""",
        ),
    )


def build_cards() -> None:
    specs = [
        ("Operating Systems", "hard",
         "What are the four Coffman conditions for deadlock?",
         "Mutual exclusion, hold and wait, no preemption, and circular wait. All four "
         "must hold simultaneously, which is why breaking any single one is enough to "
         "make deadlock impossible."),
        ("Databases", "easy", "What is an update anomaly?",
         "The same fact stored in many rows drifting out of sync."),
        ("Networks", "medium",
         "Why does TCP treat packet loss as its congestion signal?",
         "Because routers do not tell endpoints they are congested, so it must be "
         "inferred. On wireless links and deeply buffered paths this inference is "
         "wrong, which is what BBR was built to fix."),
    ]
    flips = "\n      ".join(
        f"""<label class="fc">
        <input type="checkbox" hidden>
        <span class="fcin">
          <span class="face">
            <div class="ctop"><span class="topic">{topic}</span>{dtag(level)}</div>
            <p class="q">{q}</p>
            <div class="cfoot">flip for answer</div>
          </span>
          <span class="face bk">
            <div class="ctop"><span class="topic">{topic}</span>{dtag(level)}</div>
            <p class="ans">{a}</p>
            <div class="cfoot">flip back</div>
          </span>
        </span>
      </label>"""
        for topic, level, q, a in specs
    )
    write(
        "Cards",
        page(
            1240,
            f"""<div style="border-bottom:3px solid var(--ink);padding-bottom:14px">
      <h1 class="ttl" style="font-size:52px">The card</h1>
      <p class="sub">click to flip &middot; live, not a mockup</p>
    </div>
    <p style="margin:22px 0 26px;font-size:16px;line-height:1.6;max-width:64ch;color:var(--ink2)">
      Height follows content, so a one-line answer and a full paragraph both sit correctly.
      Difficulty reads twice over &mdash; one, two or three marks as well as colour &mdash; so it
      survives being printed, screenshotted, or seen by someone who cannot separate the hues.</p>
    <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;
      align-items:start">
      {flips}
    </div>
    <div style="margin-top:40px;border-top:1.5px solid var(--rule);padding-top:22px">
      <span class="lbl" style="margin-bottom:14px">Difficulty ramp &mdash; measured on the card surface</span>
      <div style="display:flex;gap:34px">
        <span class="stat"><span class="diff d-easy"><span class="ds"><i></i></span>easy</span>
          &nbsp; 5.91:1</span>
        <span class="stat"><span class="diff d-med"><span class="ds"><i></i><i></i></span>medium</span>
          &nbsp; 5.10:1</span>
        <span class="stat"><span class="diff d-hard"><span class="ds"><i></i><i></i><i></i></span>hard</span>
          &nbsp; 6.77:1</span>
      </div>
    </div>""",
        ),
        extra="""
.fc{display:block;perspective:1300px;cursor:pointer}
.fcin{display:grid;transition:transform .58s cubic-bezier(.2,.8,.2,1);transform-style:preserve-3d}
.fc input:checked ~ .fcin{transform:rotateY(180deg)}
.face{grid-area:1/1;backface-visibility:hidden;background:var(--paper2);
 border:1.5px solid var(--ink);padding:16px 17px 14px;box-shadow:4px 4px 0 var(--rule)}
.face.bk{transform:rotateY(180deg);background:var(--paper2);
 background-image:radial-gradient(circle at 1px 1px,rgba(43,74,139,.10) 1px,transparent 1.7px);
 background-size:6px 6px}
.fc:hover .fcin{transform:translateY(-3px)}
.fc:hover input:checked ~ .fcin{transform:translateY(-3px) rotateY(180deg)}
@media (prefers-reduced-motion:reduce){.fcin{transition:none}}""",
    )


def build_phone() -> None:
    cards = "\n        ".join(card(*c) for c in CARDS[:3])
    write(
        "Phone",
        f"""<div class="wrap ph" style="width:390px">
  <div class="grain"></div>
  <div class="rel">
    <header style="border-bottom:2.5px solid var(--ink);padding-bottom:12px">
      <h1 class="ttl" style="font-size:44px">Flashcards</h1>
      <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-top:10px">
        <p class="sub" style="margin:0">notes in &middot; anki out</p>
      </div>
      <div class="ticks" style="justify-content:flex-start;margin:12px 0 6px">
        {ticks(7)}
      </div>
      <p class="rn" style="margin:0"><b>13</b> of 20 left &middot; resets 12:30</p>
    </header>
    <div style="margin-top:20px">
      <div class="field">
        <span class="lbl" style="margin-bottom:7px">Notes</span>
        <div class="ta" style="font-size:14px">{NOTES_TEXT[:180]}&hellip;</div>
      </div>
      <div class="field acc"><span>Upload .md or .txt</span><span>+</span></div>
      <div class="field row2">
        <label style="flex:1"><span class="lbl" style="margin-bottom:6px">Max chunks</span>
          <div class="inp">5</div></label>
      </div>
      <label class="chk" style="margin-bottom:16px"><span class="box"></span>
        Remove near-duplicates</label>
      <div class="btn btn-prev" style="margin-bottom:11px">Preview &mdash; free</div>
      <div class="btn btn-gen">Generate<span class="cost">spends 4 of your 20</span></div>
    </div>
    <div class="summary" style="margin-top:26px;flex-direction:column;align-items:stretch;gap:14px">
      <div style="display:flex;gap:22px">
        <span class="stat"><b>19</b> cards</span>
        <span class="stat"><b>4</b> chunks</span>
      </div>
      <span class="btn-dl" style="text-align:center">Download CSV</span>
    </div>
    <div style="display:grid;gap:14px">
        {cards}
    </div>
  </div>
</div>""",
        extra="""
.wrap.ph{padding:22px 20px 30px}
.wrap.ph .ttl{text-shadow:3px -2px 0 var(--orange)}""",
    )


DARK = """
:root{--paper:#171612;--paper2:#211f19;--ink:#f1ede1;--ink2:#c9c3b3;--mute:#8e8776;
 --rule:#38342b;--rule2:#2b2820;--blue:#89a9e4;--blued:#a8c0ee;--orange:#ff8a5c;
 --oranget:#ff9d75;--easy:#8fc088;--med:#e0b45a;--hard:#e69182}
.grain{mix-blend-mode:screen;opacity:.07}
.ta,.card,.inp{box-shadow:4px 4px 0 #0e0d0a}
.btn-gen{background:var(--blue);color:#171612;box-shadow:5px 5px 0 #0e0d0a}
.btn-dl{background:var(--paper2);color:var(--ink);box-shadow:3px 3px 0 #0e0d0a}
.knock{background:var(--blue);color:#171612;box-shadow:6px 6px 0 #0e0d0a}
.knock h2{color:#171612}
.box{background:var(--blue)}
.m.lt{background:transparent;color:var(--mute)}
.m.dk{background:var(--ink);color:var(--paper)}
"""


# --- the two alternates, deliberately low-fi -------------------------------


def build_dir_terminal() -> None:
    write(
        "AltTerminal",
        f"""<div style="width:760px;background:#12140f;padding:34px 36px;font-family:'IBM Plex Mono',
  monospace;color:#c8d6bc">
  <p style="margin:0 0 4px;font-size:10px;letter-spacing:.18em;color:#6d7d5f">ALTERNATE A</p>
  <h2 style="margin:0 0 6px;font-size:26px;color:#d9f0c6;font-weight:500">Lab Terminal</h2>
  <p style="margin:0 0 22px;font-size:12px;line-height:1.6;color:#8d9d7f;max-width:56ch">
    Engineering-notebook grid, phosphor green on near-black, everything monospaced.
    The ration reads as a gauge. Dense and instrument-like.</p>
  <div style="border:1px solid #2f3a27;padding:16px;margin-bottom:14px">
    <p style="margin:0 0 8px;font-size:11px;color:#6d7d5f">QUOTA [||||||||------------] 13/20</p>
    <div style="height:1px;background:#2f3a27;margin:12px 0"></div>
    <p style="margin:0;font-size:12px">&gt; paste notes_ </p>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div style="border:1px solid #2f3a27;padding:12px;font-size:11px;line-height:1.6">
      <span style="color:#6d7d5f">[OS] hard</span><br>What are the four Coffman conditions?</div>
    <div style="border:1px solid #2f3a27;padding:12px;font-size:11px;line-height:1.6">
      <span style="color:#6d7d5f">[DB] easy</span><br>What is an update anomaly?</div>
  </div>
  <p style="margin:20px 0 0;font-size:11px;line-height:1.6;color:#8d9d7f;max-width:56ch">
    <b style="color:#d9f0c6">Trade-off:</b> reads as a tool, not a study aid. Long prose
    answers are hard going in mono, and it is bleak for a two-hour revision session.</p>
</div>""",
    )


def build_dir_editorial() -> None:
    write(
        "AltEditorial",
        f"""<div style="width:760px;background:#fdfcf9;padding:34px 36px;
  font-family:'Newsreader',Georgia,serif;color:#1a1a1a">
  <p style="margin:0 0 4px;font-family:'IBM Plex Mono',monospace;font-size:10px;
    letter-spacing:.18em;color:#9b9384">ALTERNATE B</p>
  <h2 style="margin:0 0 6px;font-family:'Instrument Serif',Georgia,serif;font-size:34px;
    font-weight:400">Specimen Sheet</h2>
  <p style="margin:0 0 22px;font-size:13.5px;line-height:1.6;color:#5a544a;max-width:58ch">
    Museum-catalogue restraint. Hairline rules, enormous type-scale contrast, one accent,
    acres of white. Cards laid out like plates in a reference volume.</p>
  <div style="border-top:2px solid #1a1a1a;border-bottom:1px solid #ddd8cc;padding:18px 0;
    display:flex;justify-content:space-between;align-items:baseline">
    <span style="font-family:'Instrument Serif',serif;font-size:56px;line-height:1">19</span>
    <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.16em;
      color:#9b9384">CARDS &middot; PLATE I&ndash;IV</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:0;margin-top:0">
    <div style="padding:16px 20px 16px 0;border-right:1px solid #ddd8cc;border-bottom:1px solid #ddd8cc">
      <p style="margin:0 0 6px;font-family:'IBM Plex Mono',monospace;font-size:9px;
        letter-spacing:.14em;color:#9b9384">I &middot; OPERATING SYSTEMS</p>
      <p style="margin:0;font-size:16px;line-height:1.4">What are the four Coffman
        conditions for deadlock?</p></div>
    <div style="padding:16px 0 16px 20px;border-bottom:1px solid #ddd8cc">
      <p style="margin:0 0 6px;font-family:'IBM Plex Mono',monospace;font-size:9px;
        letter-spacing:.14em;color:#9b9384">II &middot; DATABASES</p>
      <p style="margin:0;font-size:16px;line-height:1.4">What is an update anomaly?</p></div>
  </div>
  <p style="margin:20px 0 0;font-size:13px;line-height:1.6;color:#5a544a;max-width:58ch">
    <b>Trade-off:</b> beautiful and calm, but it is the safe iteration &mdash; closest to
    what you already have, and it does not solve the "everything is the same weight"
    complaint so much as tidy it.</p>
</div>""",
    )



def make_dark_twins(names: list[str]) -> None:
    """Write a dark twin of each screen by appending the override block.

    The two modes are one design with a single token set swapped, so generating
    the twin beats maintaining a parallel set of artboards that drift apart.
    """
    for name in names:
        src = (HERE / f"{name}.dc.html").read_text(encoding="utf-8")
        twin = src.replace("\n  </style>", f"\n{DARK}\n  </style>", 1)
        if twin == src:
            raise RuntimeError(f"{name}: no </style> to inject dark tokens before")
        (HERE / f"{name}Dark.dc.html").write_text(twin, encoding="utf-8")


PAL_ROWS = ["ink", "ink2", "mute", "blue", "oranget", "easy", "med", "hard"]
PAL_NOTE = {
    "ink": "body text", "ink2": "answers, secondary prose", "mute": "labels",
    "blue": "actions, links, ration", "oranget": "warnings, misregister",
    "easy": "difficulty 1", "med": "difficulty 2", "hard": "difficulty 3",
}


def palette_table(pal: dict) -> str:
    head = (
        '<span class="lbl">swatch</span><span class="lbl">token</span>'
        '<span class="lbl">hex</span><span class="lbl">on card</span>'
        '<span class="lbl">AA</span>'
    )
    rows = []
    for key in PAL_ROWS:
        r = ratio(pal[key], pal["paper2"])
        rows.append(
            f'<span><span class="sw" style="background:{pal[key]}"></span></span>'
            f'<span>{key}<span style="color:var(--mute)"> &middot; {PAL_NOTE[key]}</span></span>'
            f'<span style="color:var(--mute)">{pal[key]}</span>'
            f'<span>{r:.2f}:1</span>'
            f'<span style="color:var(--easy)">{"pass" if r >= 4.5 else "large only"}</span>'
        )
    return f'<div class="pal">{head}{"".join(rows)}</div>'


def build_palette() -> None:
    write(
        "Palette",
        page(
            1300,
            f"""<div style="border-bottom:3px solid var(--ink);padding-bottom:14px">
      <h1 class="ttl" style="font-size:52px">Two inks, two grounds</h1>
      <p class="sub">every ratio below is measured, not asserted</p>
    </div>
    <p style="margin:22px 0 26px;font-size:16px;line-height:1.6;max-width:70ch;color:var(--ink2)">
      Both modes are the same design with one token set swapped &mdash; layout, type and spacing
      never move. Dark is not a dimmed copy: the spot blue lightens so it still reads as the
      action colour, and the difficulty ramp lifts so all three stay separable on a dark card.</p>
    <div style="display:flex;gap:44px;align-items:flex-start">
      <div style="flex:1">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
          <span class="sw" style="background:{PAL_LIGHT['paper']}"></span>
          <span style="font-family:var(--mono);font-size:13px">LIGHT &middot; ground
            {PAL_LIGHT['paper']} &middot; card {PAL_LIGHT['paper2']}</span>
        </div>
        {palette_table(PAL_LIGHT)}
      </div>
      <div style="flex:1">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
          <span class="sw" style="background:{PAL_DARK['paper']}"></span>
          <span style="font-family:var(--mono);font-size:13px">DARK &middot; ground
            {PAL_DARK['paper']} &middot; card {PAL_DARK['paper2']}</span>
        </div>
        {palette_table(PAL_DARK)}
      </div>
    </div>
    <div style="margin-top:34px;border:1.5px solid var(--ink);background:var(--paper2);
      padding:20px 24px;max-width:780px">
      <span class="lbl">How the switch works</span>
      <p style="margin:9px 0 0;font-size:15px;line-height:1.62;color:var(--ink2)">
        The toggle in the header is a hidden checkbox plus
        <span style="font-family:var(--mono);font-size:13.5px">body:has(:checked)</span>
        re-declaring the custom properties. No JavaScript, so it is buildable in Gradio as it
        stands. The default follows
        <span style="font-family:var(--mono);font-size:13.5px">prefers-color-scheme</span>
        and the toggle overrides it for the session.</p>
    </div>
    <p style="margin:18px 0 0;font-size:13.5px;color:var(--mute);max-width:72ch;line-height:1.6">
      The two tightest pairs are light <b>med</b> at 5.10:1 and dark <b>mute</b> at 4.61:1.
      Both clear AA for body text; neither has room to be nudged further toward its ground.</p>""",
        ),
    )


DARK_TWINS = ["Main", "Empty", "Preview", "Generating", "QuotaSpent", "Cards", "Phone"]

_L = {
    "Main": (0, 0, 1440, 1240, "Results"),
    "Empty": (1560, 0, 1440, 900, "Empty / first load"),
    "Pasted": (3120, 0, 1440, 860, "Notes pasted"),
    "Preview": (0, 1400, 1440, 1000, "Preview - costs nothing"),
    "Generating": (1560, 1400, 1440, 960, "Generating - the dead air"),
    "Partial": (3120, 1400, 1440, 1120, "Partial success"),
    "QuotaSpent": (0, 2680, 1440, 800, "Daily ration spent"),
    "Errors": (1560, 2680, 1440, 820, "Error states"),
    "Cards": (0, 3620, 1240, 940, "The card - click to flip"),
    "Phone": (1400, 3620, 390, 1500, "Phone - below 900px"),
}
_D = {
    "Main": (0, 0, 1440, 1240, "Results"),
    "Empty": (1560, 0, 1440, 900, "Empty / first load"),
    "Preview": (3120, 0, 1440, 1000, "Preview - costs nothing"),
    "Generating": (0, 1400, 1440, 960, "Generating - the dead air"),
    "QuotaSpent": (1560, 1400, 1440, 800, "Daily ration spent"),
    "Cards": (3120, 1400, 1240, 940, "The card - click to flip"),
    "Phone": (0, 2500, 390, 1500, "Phone - below 900px"),
}

NOTE_RATION = (
    "PRESS ROOM - riso study desk.\n\nThe daily ration strip in every header is the spine of "
    "this design: 20 ticks, filled as you spend, so the invisible budget becomes a physical "
    "object you can read at a glance."
)
NOTE_MONEY = (
    "The two buttons carry different weight on purpose. Preview is a dashed, weightless "
    "outline. Generate is a knockout block that prints its own cost on the face: "
    "'spends 4 of your 20'."
)
NOTE_DEADAIR = (
    "Generating names the wait instead of hiding it - 'waiting 24s for the rate limit... this "
    "pause is the limiter, not a stall'. Dead air only reads as broken when nothing explains it."
)
NOTE_DARK = (
    "Same design, one token set swapped - nothing moves. The spot blue lightens so it still "
    "reads as the action colour, and the difficulty ramp lifts so all three stay separable on "
    "a dark card. Measured ratios are on the Foundations page."
)
NOTE_QUOTA_DARK = (
    "The ration block inverts rather than dimming: in dark mode it becomes a light slab on the "
    "dark ground, so 'you are out' still lands as the heaviest thing on the page."
)
NOTE_ALT = (
    "Two alternates, low-fi on purpose. Each names its own trade-off so this is a real choice "
    "and not a rigged vote. Say the word and either becomes the main direction."
)


def canvas() -> dict:
    boards = []
    for name, (x, y, w, h, title) in _L.items():
        entry = {"file": f"{name}.dc.html", "x": x, "y": y, "w": w, "h": h,
                 "title": title, "page": "page-1"}
        if name == "Cards":
            entry["is_interactive"] = True
        boards.append(entry)
    for name, (x, y, w, h, title) in _D.items():
        entry = {"file": f"{name}Dark.dc.html", "x": x, "y": y, "w": w, "h": h,
                 "title": title, "page": "page-2"}
        if name == "Cards":
            entry["is_interactive"] = True
        boards.append(entry)
    boards += [
        {"file": "Palette.dc.html", "x": 0, "y": 0, "w": 1300, "h": 900,
         "title": "Palette - both modes, measured", "page": "page-3"},
        {"file": "AltTerminal.dc.html", "x": 1400, "y": 0, "w": 760, "h": 560,
         "title": "Alternate A", "page": "page-3"},
        {"file": "AltEditorial.dc.html", "x": 2260, "y": 0, "w": 760, "h": 600,
         "title": "Alternate B", "page": "page-3"},
    ]
    return {
        "pages": [
            {"id": "page-1", "name": "Light mode"},
            {"id": "page-2", "name": "Dark mode"},
            {"id": "page-3", "name": "Foundations"},
        ],
        "artboards": boards,
        "annotations": [
            {"id": "ration-note", "x": 0, "y": -170, "w": 620, "page": "page-1",
             "text": NOTE_RATION},
            {"id": "money-note", "x": 0, "y": 1260, "w": 560, "page": "page-1",
             "text": NOTE_MONEY},
            {"id": "deadair-note", "x": 1560, "y": 2380, "w": 560, "page": "page-1",
             "text": NOTE_DEADAIR},
            {"id": "dark-note", "x": 0, "y": -170, "w": 640, "page": "page-2",
             "text": NOTE_DARK},
            {"id": "quota-dark-note", "x": 1560, "y": 2240, "w": 560, "page": "page-2",
             "text": NOTE_QUOTA_DARK},
            {"id": "alt-note", "x": 1400, "y": 680, "w": 700, "page": "page-3",
             "text": NOTE_ALT},
        ],
        "launch": {"view": "canvas", "page": "page-2"},
    }


def main() -> None:
    build_main()
    build_empty()
    build_pasted()
    build_preview()
    build_generating()
    build_partial()
    build_quota()
    build_errors()
    build_cards()
    build_phone()
    build_dir_terminal()
    build_dir_editorial()
    make_dark_twins(DARK_TWINS)
    build_palette()
    (HERE / "canvas.json").write_text(json.dumps(canvas(), indent=2), encoding="utf-8")
    built = sorted(q.name for q in HERE.glob("*.dc.html"))
    print(f"{len(built)} artboards")


if __name__ == "__main__":
    main()
