"""Generate the Ruled Paper screen set.

Every screen shares the same header and form sidebar; only the results column
and a few sidebar states differ. One source here keeps them from drifting.

Run from this directory:  python build_screens.py
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent

PAPER, CARD_BG = "#faf7f2", "#fffdfa"
INK, INK_2, INK_3 = "#23201c", "#4a443b", "#6d6559"
RULE, RULE_2 = "#d9d2c6", "#e6e0d5"
MUTE = "#8c8578"
# Difficulty is a sequential ramp, cool to hot; every step clears WCAG AA on
# the card ground. Actions use a separate hue so a card edge never reads as a
# button -- blue ink on ruled paper, which is what the metaphor wants.
SAGE, OCHRE, OXBLOOD = "#5b7553", "#8f6116", "#9c3520"
RED, AMBER, OX = "#2c4a6b", OCHRE, OXBLOOD

SERIF = "'Newsreader', Georgia, serif"
MONO = "font-family:'IBM Plex Mono',ui-monospace,monospace"

FONTS = (
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
    "&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap"
)


def head(height: int, width: int = 1280, pad: str = "0 56px 48px") -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="{FONTS}">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ margin: 0; background: {PAPER}; color: {INK};
           font-family: {SERIF}; }}
    a {{ color: {RED}; }} a:hover {{ color: #213952; }}
    .mono {{ font-family: 'IBM Plex Mono', ui-monospace, monospace; }}
    .lbl {{ font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 10.5px;
           letter-spacing: .12em; text-transform: uppercase; color: {MUTE}; }}
    .field {{ border: 1px solid {RULE}; background: {CARD_BG}; border-radius: 2px; }}
    .btn {{ border-radius: 2px; display: flex; align-items: center;
           justify-content: center; gap: 8px; font-size: 15px; }}
    .card {{ background: {CARD_BG}; border: 1px solid {RULE}; border-radius: 2px;
            padding: 16px 18px 18px; display: flex; flex-direction: column; gap: 12px; }}
  </style>
</helmet>

<div style="width: {width}px; min-height: {height}px; background: {PAPER}; padding: {pad};">

  <div style="display: flex; align-items: flex-end; justify-content: space-between; padding: 34px 0 20px; border-bottom: 2px solid {INK};">
    <div style="display: flex; align-items: baseline; gap: 14px;">
      <h1 style="margin: 0; font-size: 34px; font-weight: 600; letter-spacing: -0.02em;">Flashcards</h1>
      <span style="font-size: 16px; color: {INK_3};">notes in, Anki cards out</span>
    </div>
    <span class="mono" style="font-size: 11px; color: {MUTE};">gemini-2.5-flash</span>
  </div>
"""


TAIL = "</div>\n</x-dc>\n</body>\n</html>\n"

NOTES_TEXT = (
    "Supervised learning is one of the most fundamental concepts in machine "
    "learning. It is a learning approach where a model is trained using labeled "
    "data, meaning every input has a corresponding correct output…"
)


def sidebar(filled: bool = True, note: str = "") -> str:
    chars = "3,157 chars" if filled else "0 chars"
    body = NOTES_TEXT if filled else "Paste lecture notes here…"
    body_colour = INK_2 if filled else "#a49c8f"
    border = f"1px solid {RULE}" if filled else f"1px dashed {RULE}"
    gen = (
        f'<div class="btn" style="height:48px;background:{INK};color:{PAPER};font-weight:500">Generate</div>'
        if filled
        else f'<div class="btn" style="height:48px;background:#e4ded2;color:#a49c8f;font-weight:500">Generate</div>'
    )
    hint = (
        f'<p style="margin:8px 0 0;font-size:12.5px;line-height:1.5;color:{MUTE}">{note}</p>'
        if note
        else ""
    )
    return f"""
    <div style="flex: 0 0 320px; display: flex; flex-direction: column; gap: 14px;">
      <span class="lbl">Notes</span>
      <div class="field" style="height: 232px; padding: 14px 16px; border: {border}; font-size: 14px; line-height: 1.62; color: {body_colour}; overflow: hidden;">{body}</div>
      <div class="field" style="display: flex; align-items: center; justify-content: space-between; height: 46px; padding: 0 16px; font-size: 14px; color: {INK_3};">
        <span>Upload .md or .txt</span><span class="mono" style="font-size: 15px;">+</span>
      </div>
      <div style="display: flex; flex-direction: column; gap: 10px; padding-top: 4px;">
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <span style="font-size: 14.5px;">Max chunks</span>
          <div class="field mono" style="width: 74px; height: 38px; display: flex; align-items: center; justify-content: center; font-size: 15px;">5</div>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <span style="font-size: 14.5px;">Remove near-duplicates</span>
          <div style="width: 42px; height: 24px; border-radius: 12px; background: {RED}; display: flex; align-items: center; justify-content: flex-end; padding: 3px;">
            <div style="width: 18px; height: 18px; border-radius: 9px; background: {CARD_BG};"></div>
          </div>
        </div>
      </div>
      <p style="margin: 2px 0 0; font-size: 12.5px; line-height: 1.5; color: {MUTE};">Free tier allows <span class="mono" style="color: {INK_3};">5</span> requests a minute. Higher values wait between calls.</p>
      <div style="display: flex; flex-direction: column; gap: 9px; padding-top: 4px;">
        <div class="btn" style="height: 44px; border: 1px solid {INK}; background: transparent; color: {INK};">Preview <span class="mono" style="font-size: 11px; color: {INK_3};">free</span></div>
        {gen}
      </div>
      {hint}
    </div>
"""


LEVELS = {"easy": (1, SAGE), "medium": (2, OCHRE), "hard": (3, OXBLOOD)}


def squares(level: str) -> str:
    filled = LEVELS[level][0]
    return "".join(
        f'<span style="width:7px;height:7px;background:{INK}"></span>'
        if i < filled
        else '<span style="width:7px;height:7px;border:1px solid #b9b1a3"></span>'
        for i in range(3)
    )


FLIP_ICON = (
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 7.5 4"></path><path d="M20 3v4h-4"></path>'
    '<path d="M21 12a9 9 0 0 1-9 9 9 9 0 0 1-7.5-4"></path><path d="M4 21v-4h4"></path></svg>'
)

# The back of an index card is ruled; the answer's line-height matches the pitch.
RULED = (
    f"background-image:repeating-linear-gradient({CARD_BG} 0 27px,#ece5d8 27px 28px);"
    "background-position:0 52px;"
)

# Content-driven, not a fixed box: the app stacks both faces in one grid cell,
# so a card is as tall as its taller face and no answer scrolls inside it.
FACE = (
    f"min-height:220px;height:100%;background:{CARD_BG};border:1px solid {RULE};"
    "border-radius:2px;padding:16px 18px;display:flex;flex-direction:column;gap:11px;"
)


def card(question: str, topic: str, level: str, answer: str, back: bool = False) -> str:
    """One face of a flip card: the question, or the ruled reverse."""
    rule_colour = LEVELS[level][1]
    edge = f"border-left:3px solid {rule_colour};"

    if back:
        return (
            f'<div style="{FACE}{RULED}{edge}">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;flex-shrink:0">'
            f'<span class="lbl">{topic}</span>'
            f'<span class="lbl" style="color:{rule_colour}">answer</span></div>'
            f'<p style="margin:0;font-size:15px;line-height:28px;color:{INK_2};'
            f'text-wrap:pretty;flex-grow:1">{answer}</p></div>'
        )

    return (
        f'<div style="{FACE}{edge}box-shadow:0 8px 22px rgba(35,32,28,.06)">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;flex-shrink:0">'
        f'<div style="display:flex;align-items:center;gap:8px">'
        f'<span style="display:inline-flex;gap:3px">{squares(level)}</span>'
        f'<span class="lbl" style="color:{INK}">{level}</span></div>'
        f'<span class="lbl">{topic}</span></div>'
        f'<p style="margin:0;font-size:18px;font-weight:500;line-height:1.36;'
        f'text-wrap:pretty;flex-grow:1">{question}</p>'
        f'<div style="display:flex;align-items:center;gap:6px;color:{rule_colour};flex-shrink:0">'
        f'{FLIP_ICON}<span class="lbl" style="color:{rule_colour}">flip for answer</span></div></div>'
    )


CARD_DATA = [
    (
        "What is supervised learning in machine learning?",
        "Supervised Learning Basics",
        "easy",
        "Supervised learning trains a model on labelled data, where every input has a "
        "corresponding correct output. The goal is to learn the relationship between "
        "input features and the target variable.",
    ),
    (
        "What is tokenization in Natural Language Processing?",
        "NLP Preprocessing",
        "easy",
        "Tokenization is the process of breaking text into smaller units called tokens, "
        "such as words, subwords, or characters. It is a crucial initial preprocessing "
        "step because machine learning models cannot directly process raw text.",
    ),
    (
        "How do modern NLP models often handle tokenization for rare or unseen words?",
        "Modern NLP Tokenization",
        "medium",
        "Modern NLP models often use subword tokenization techniques, such as Byte Pair "
        "Encoding (BPE) or WordPiece, to handle rare or unseen words more effectively "
        "than traditional word-level tokenization.",
    ),
    (
        "Why do contextual embeddings from BERT cost more to compute than static "
        "Word2Vec vectors?",
        "Embedding Trade-offs",
        "hard",
        "Static vectors are looked up once per word, while contextual embeddings run the "
        "whole sentence through a transformer for every inference.",
    ),
]


def grid(cards_html: str, columns: int = 2) -> str:
    return (
        f'<div style="display:grid;grid-template-columns:repeat({columns},minmax(0,1fr));'
        f'gap:18px;padding-top:22px;align-items:stretch">{cards_html}</div>'
    )


def summary(cards: int = 12, chunks: int = 3, extra: str = "") -> str:
    line = extra or "dropped 0 &nbsp;·&nbsp; duplicates 1 &nbsp;·&nbsp; requests 0 &nbsp;·&nbsp; cached 3"
    return (
        f'<div style="display:flex;align-items:flex-end;justify-content:space-between;'
        f'padding-bottom:18px;border-bottom:1px solid {RULE}">'
        f'<p style="margin:0;font-size:26px;line-height:1.1">'
        f'<span style="font-weight:600">{cards} cards</span> '
        f'<span style="color:{INK_3}">from {chunks} chunks</span></p>'
        f'<div class="btn mono" style="height:44px;padding:0 22px;background:{RED};'
        f'color:{CARD_BG};font-size:13px;letter-spacing:.04em">DOWNLOAD CSV</div></div>'
        f'<p class="mono" style="margin:10px 0 0;font-size:11px;color:{MUTE}">{line}</p>'
    )


EMPTY_RESULTS = (
    f'<div style="border:1px dashed {RULE};border-radius:2px;padding:150px 24px;'
    f'text-align:center"><p style="margin:0;font-size:15px;color:{MUTE}">'
    "Cards appear here once you generate.</p></div>"
)

ESTIMATE = (
    f'<div style="border:1px solid {RULE};background:{CARD_BG};border-radius:2px;overflow:hidden">'
    f'<div style="padding:16px 20px 0"><span class="lbl">Estimate</span></div>'
    '<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:14px 20px 20px">'
    + "".join(
        f'<div style="display:flex;flex-direction:column;gap:4px">'
        f'<span style="font-size:38px;font-weight:600;line-height:1;letter-spacing:-0.02em">{v}</span>'
        f'<span class="lbl">{label}</span></div>'
        for v, label in ((3, "chunks"), (3, "requests"),
                         ("758", "tokens approx"))
    )
    + f'</div><div style="display:flex;align-items:center;gap:10px;padding:14px 20px;'
    f'background:#f2f5ee;border-top:1px solid #dfe5d8">'
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#4f7a48" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M20 6L9 17l-5-5"></path></svg>'
    '<span style="font-size:14px;color:#3f5c3a">No API calls were made.</span></div></div>'
    f'<p style="margin:12px 2px 0;font-size:13px;line-height:1.55;color:{MUTE}">'
    "Token count is estimated locally at four characters per token, not measured by the API.</p>"
)


def stage(state: str, label: str, sub: str, meta: str, first: bool, last: bool) -> str:
    tick = (
        f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{INK}" '
        'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M20 6L9 17l-5-5"></path></svg>'
    )
    ring = (
        f'<span style="width:14px;height:14px;border:2px solid {RED};border-right-color:'
        f'{RULE};border-radius:50%;display:inline-block"></span>'
    )
    dot = f'<span style="width:12px;height:12px;border:1px solid {RULE};border-radius:50%;display:inline-block"></span>'
    icon = {"done": tick, "active": ring}.get(state, dot)
    label_colour = {"done": INK_2, "active": INK}.get(state, "#a49c8f")
    weight = "500" if state == "active" else "400"
    background = CARD_BG if state == "active" else "transparent"
    sub_html = (
        f'<span style="font-size:12.5px;color:{INK_3}">{sub}</span>'
        if sub and state == "active"
        else ""
    )
    return (
        f'<div style="display:flex;align-items:center;gap:14px;min-height:54px;'
        f'padding:10px 18px;background:{background};border-bottom:1px solid {RULE_2};'
        f'{"border-top:1px solid " + RULE_2 + ";" if first else ""}">'
        f'<span style="width:16px;display:flex;justify-content:center">{icon}</span>'
        f'<div style="display:flex;flex-direction:column;gap:2px;flex-grow:1">'
        f'<span style="font-size:15px;font-weight:{weight};color:{label_colour}">{label}</span>{sub_html}</div>'
        f'<span class="mono" style="font-size:11.5px;color:{MUTE}">{meta}</span></div>'
    )


PROGRESS = (
    f'<div style="display:flex;align-items:baseline;justify-content:space-between;'
    f'padding-bottom:12px"><span class="lbl">Progress</span>'
    f'<span class="mono" style="font-size:11.5px;color:{INK_3}">step 3 of 4</span></div>'
    f'<div style="height:3px;background:{RULE};display:flex">'
    f'<div style="width:68%;background:{RED}"></div></div>'
    '<div style="padding-top:18px">'
    + stage("done", "Splitting notes into chunks", "", "3 chunks", True, False)
    + stage("done", "Generating cards", "", "3 / 3", False, False)
    + stage("active", "Removing near-duplicates", "First run loads a model, about 25 seconds", "24s", False, False)
    + stage("pending", "Writing CSV", "", "", False, True)
    + "</div>"
)


def err(title: str, code: str, detail: str, tone: str = "red") -> str:
    edge = RED if tone == "red" else AMBER
    tint = "#fbf1ee" if tone == "red" else "#faf4e8"
    return (
        f'<div style="border:1px solid {RULE};border-left:3px solid {edge};background:{tint};'
        f'border-radius:2px;padding:16px 20px;display:flex;flex-direction:column;gap:7px">'
        f'<div style="display:flex;align-items:baseline;gap:10px">'
        f'<span style="font-size:18px;font-weight:600;color:{INK}">{title}</span>'
        f'<span class="mono" style="font-size:11px;color:{MUTE}">{code}</span></div>'
        f'<p style="margin:0;font-size:14.5px;line-height:1.6;color:{INK_2}">{detail}</p></div>'
    )


def page(name: str, results: str, height: int, filled: bool = True, note: str = "") -> None:
    body = (
        f'<div style="display: flex; gap: 44px; align-items: flex-start; padding-top: 28px;">'
        f"{sidebar(filled, note)}"
        f'<div style="flex: 1 1 0; min-width: 0;">{results}</div></div>'
    )
    (HERE / f"{name}.dc.html").write_text(head(height) + body + TAIL, encoding="utf-8")
    print(f"wrote {name}.dc.html")


def anatomy() -> str:
    """Front, mid-flip and back in a row, to document the rotation."""
    question, topic, level, answer = CARD_DATA[0]
    mid = (
        '<div style="perspective:1400px">'
        '<div style="transform:rotateY(-52deg);transform-origin:center">'
        f"{card(question, topic, level, answer)}</div></div>"
    )
    labels = ("Front · at rest", "Mid-flip · 0.6s rotateY", "Back · ruled, answer")
    faces = (card(question, topic, level, answer), mid,
             card(question, topic, level, answer, back=True))
    cells = "".join(
        f'<div style="display:flex;flex-direction:column;gap:12px">'
        f'<span class="lbl">{label}</span>{face}</div>'
        for label, face in zip(labels, faces)
    )
    return (
        f'<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));'
        f'gap:36px;padding-top:26px">{cells}</div>'
        f'<p style="margin:30px 0 0;font-size:14.5px;line-height:1.6;color:{INK_3};max-width:640px">'
        "The flip is a hidden checkbox driving a rotateY, so it needs no JavaScript and "
        "stays keyboard-operable. Both faces share one grid cell, so a card is as tall "
        "as its taller face and no answer scrolls inside a box. Hover lifts the card "
        "3px; entrance is staggered 45ms per card. All "
        "motion is dropped under prefers-reduced-motion, where the flip still works.</p>"
    )


if __name__ == "__main__":
    collapsed = "".join(card(*c) for c in CARD_DATA)
    opened = (
        card(*CARD_DATA[0], back=True) + card(*CARD_DATA[1])
        + card(*CARD_DATA[2]) + card(*CARD_DATA[3], back=True)
    )

    page("Main", summary() + grid(collapsed), 1120)

    # Standalone sheet: no form sidebar, it documents the card itself.
    (HERE / "FlipAnatomy.dc.html").write_text(
        head(700, width=1180) + f'<div style="padding-top:8px">{anatomy()}</div>' + TAIL,
        encoding="utf-8",
    )
    print("wrote FlipAnatomy.dc.html")
    page("Empty", EMPTY_RESULTS, 900, filled=False)
    page("Filled", EMPTY_RESULTS, 900)
    page("Preview", ESTIMATE, 900)
    page("Generating", PROGRESS + grid("".join(card(*c) for c in CARD_DATA[:2])), 1020)
    page("CardOpen", summary() + grid(opened), 1220)

    partial = (
        err("1 chunk failed", "MAX_TOKENS", "lecture_04#2 stopped early. The other three "
            "finished, and their cards are below.", tone="amber")
        + '<div style="height:18px"></div>'
        + summary(9, 4, "dropped 1 &nbsp;·&nbsp; duplicates 2 &nbsp;·&nbsp; requests 4 &nbsp;·&nbsp; cached 0")
        + grid("".join(card(*c) for c in CARD_DATA[:2]))
    )
    page("Partial", partial, 1020)

    errors = (
        err("Out of quota", "HTTP 429",
            "The free tier allows 5 requests a minute. Google asked to wait 47 seconds "
            "before trying again. Your notes are still here.")
        + '<div style="height:20px"></div>'
        + err("No API key", "",
              "GEMINI_API_KEY is not set, so nothing can be generated. Put it in .env at "
              "the project root and reload.")
        + '<div style="height:20px"></div>'
        + f'<div style="border:1px dashed {RULE};border-radius:2px;padding:44px 24px;text-align:center">'
        f'<p style="margin:0;font-size:16px;color:{INK_2}">Nothing to work with</p>'
        f'<p style="margin:7px 0 0;font-size:13.5px;color:{MUTE}">Paste notes on the left '
        "or upload a file, then try again.</p></div>"
    )
    page("Errors", errors, 900)

    # Narrow: same page under 900px, one column.
    narrow_body = (
        f'<div style="display: flex; flex-direction: column; padding-top: 24px;">'
        f"{sidebar(True)}"
        f'<div style="width: 100%; padding-top: 30px;">'
        f"{summary()}{grid(collapsed, columns=1)}</div></div>"
    )
    narrow = head(2000, width=760, pad="0 28px 44px") + narrow_body + TAIL
    narrow = narrow.replace("flex: 0 0 320px;", "width: 100%;")
    (HERE / "Narrow.dc.html").write_text(narrow, encoding="utf-8")
    print("wrote Narrow.dc.html")
