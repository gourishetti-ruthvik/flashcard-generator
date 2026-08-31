"""Generate the sibling artboards from Main.dc.html.

Every full-page artboard shares the same header and sidebar; only the results
column differs. Hand-copying that shell eight times is how artboards drift apart,
so Main is the template and the rest are built from it.

Run from this directory:  python build_artboards.py
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent
MAIN = HERE / "Main.dc.html"

MONO = "font-family:'IBM Plex Mono',ui-monospace,monospace"
SERIF = "font-family:'Literata',Georgia,serif"
DIFFICULTY = {"easy": "#7fa87f", "medium": "#d2a24c", "hard": "#c47f66"}


def meter(level: str) -> str:
    colour = DIFFICULTY[level]
    filled = {"easy": 1, "medium": 2, "hard": 3}[level]
    bars = "".join(
        f'<span style="width:3px;border-radius:1px;height:{h}px;'
        f'background:{colour if i < filled else "#2e323b"}"></span>'
        for i, h in enumerate((4, 7, 11))
    )
    return (
        f'<div style="display:flex;align-items:center;gap:7px">'
        f'<span style="display:inline-flex;align-items:flex-end;gap:2px;height:11px">{bars}</span>'
        f'<span style="font-size:11.5px;font-weight:500;color:{colour}">{level}</span></div>'
    )


def card(question: str, topic: str, level: str, answer: str | None = None) -> str:
    body = (
        f'<p style="margin:10px 0 0;{SERIF};font-size:14px;line-height:1.68;'
        f'color:#ccd1d8;text-wrap:pretty">{answer}</p>'
        if answer
        else ""
    )
    return (
        f'<div style="background:#1a1c22;border:1px solid #2a2d35;border-radius:10px;'
        f'padding:14px 15px;display:flex;flex-direction:column;gap:10px">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;gap:10px">'
        f'{meter(level)}<span style="{MONO};font-size:11px;color:#6b7280">{topic}</span></div>'
        f'<p style="margin:0;font-size:14.5px;font-weight:500;line-height:1.4;color:#e8e9ec;'
        f'text-wrap:pretty">{question}</p>'
        f'<div><span style="font-size:11.5px;color:#6b7280">'
        f'{"Hide answer" if answer else "Show answer"}</span>{body}</div></div>'
    )


CARDS = [
    card(
        "What is supervised learning in machine learning?",
        "Supervised Learning Basics",
        "easy",
        "Supervised learning trains a model on labelled data, where every input has "
        "a corresponding correct output. The goal is to learn the relationship "
        "between input features and the target variable.",
    ),
    card(
        "What are the two main types of tasks in supervised learning?",
        "Supervised Learning Tasks",
        "easy",
        "Classification and regression. Classification predicts categories, while "
        "regression predicts continuous values.",
    ),
    card("What is an example of a classification task?", "Supervised Learning Examples", "medium"),
    card("What is an example of a regression task?", "Supervised Learning Examples", "medium"),
    card("What is tokenization in Natural Language Processing?", "NLP Preprocessing", "easy"),
    card("How do modern NLP models handle rare or unseen words?", "Modern NLP Tokenization", "medium"),
]

GRID = (
    '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));'
    'gap:14px;align-items:start;padding-top:20px">{}</div>'
)

SUMMARY = (
    '<div style="display:flex;flex-direction:column;gap:7px">'
    '<p style="margin:0;font-size:15px;line-height:1.4;color:#d5d9df">'
    f'<span style="{MONO};font-size:17px;font-weight:500;color:#e8e9ec">12</span> cards from '
    f'<span style="{MONO};color:#e8e9ec">3</span> chunks.</p>'
    f'<p style="margin:0;{MONO};font-size:11.5px;line-height:1.6;color:#6b7280">'
    "dropped 0 &nbsp;·&nbsp; duplicates 1 &nbsp;·&nbsp; requests 0 &nbsp;·&nbsp; cached 3</p></div>"
)

DOWNLOAD = (
    '<div style="height:52px;border-radius:8px;background:#d99a4e;display:flex;'
    'align-items:center;justify-content:center;gap:9px;margin-top:16px">'
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#17140f" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 3v12"></path><path d="M7 11l5 5 5-5"></path><path d="M4 20h16"></path></svg>'
    '<span style="font-size:15px;font-weight:600;color:#17140f">Download CSV</span></div>'
)

ESTIMATE = (
    '<div style="border:1px solid #33383f;background:#1b1e24;border-radius:10px;overflow:hidden">'
    '<div style="padding:13px 16px 0"><span style="font-size:11px;letter-spacing:.09em;'
    'text-transform:uppercase;font-weight:500;color:#7f858f">Estimate</span></div>'
    '<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;padding:12px 16px 18px">'
    + "".join(
        f'<div style="display:flex;flex-direction:column;gap:4px">'
        f'<span style="{MONO};font-size:30px;font-weight:500;line-height:1;color:#e8e9ec">{value}</span>'
        f'<span style="font-size:11.5px;color:#7f858f">{label}</span></div>'
        for value, label in ((3, "chunks"), (3, "requests"), (758, "tokens approx"))
    )
    + '</div><div style="display:flex;align-items:center;gap:9px;padding:12px 16px;'
    'background:#1e241f;border-top:1px solid #2b3430">'
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#7fa87f" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M20 6L9 17l-5-5"></path></svg>'
    '<span style="font-size:12.5px;color:#a8c0a8">No API calls were made.</span></div></div>'
    '<p style="margin:10px 2px 0;font-size:11.5px;line-height:1.5;color:#6b7280">'
    "Token count is estimated locally at 4 characters per token, not measured by the API. "
    "About 0s of that is waiting on the rate limit.</p>"
)

_DONE = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#7fa87f" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0">'
    '<circle cx="12" cy="12" r="10" stroke="#31463a"></circle><path d="M17 9l-6.2 6L7 11.6"></path></svg>'
)
_ACTIVE = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" '
    'style="flex-shrink:0"><circle cx="12" cy="12" r="10" stroke="#3a3f49"></circle>'
    '<path d="M12 2a10 10 0 0 1 8.7 5" stroke="#d99a4e"></path></svg>'
)
_PENDING = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#3a3f49" stroke-width="2" '
    'style="flex-shrink:0"><circle cx="12" cy="12" r="10"></circle></svg>'
)


def stage(state: str, label: str, sub: str, meta: str, first: bool, last: bool) -> str:
    radius = "8px 8px 0 0" if first else ("0 0 8px 8px" if last else "0")
    background = {"done": "#1a1c22", "active": "#1f2229"}.get(state, "#17191e")
    border = "#3a3f49" if state == "active" else "#2a2d35"
    icon = {"done": _DONE, "active": _ACTIVE}.get(state, _PENDING)
    label_colour = {"done": "#d5d9df", "active": "#e8e9ec"}.get(state, "#7c828c")
    meta_colour = {"done": "#7fa87f", "active": "#d99a4e"}.get(state, "#575d67")
    sub_html = (
        f'<span style="font-size:11.5px;line-height:1.4;color:#9ba1ac">{sub}</span>'
        if sub and state == "active"
        else ""
    )
    return (
        f'<div style="display:flex;align-items:center;gap:13px;min-height:56px;padding:11px 15px;'
        f'background:{background};border:1px solid {border};'
        f'{"" if first else "border-top:none;"}border-radius:{radius}">{icon}'
        f'<div style="display:flex;flex-direction:column;gap:3px;flex-grow:1">'
        f'<span style="font-size:13.5px;color:{label_colour}">{label}</span>{sub_html}</div>'
        f'<span style="{MONO};font-size:11.5px;color:{meta_colour}">{meta}</span></div>'
    )


PROGRESS = (
    '<div style="display:flex;align-items:baseline;justify-content:space-between;padding-bottom:10px">'
    '<span style="font-size:11px;letter-spacing:.09em;text-transform:uppercase;font-weight:500;'
    'color:#6b7280">Progress</span>'
    f'<span style="{MONO};font-size:11.5px;color:#9ba1ac">step 3 of 4</span></div>'
    '<div style="height:6px;border-radius:3px;background:#24272f;overflow:hidden;display:flex">'
    '<div style="width:68%;background:#d99a4e;border-radius:3px"></div></div>'
    '<div style="display:flex;flex-direction:column;gap:2px;padding-top:20px">'
    + stage("done", "Splitting notes into chunks", "", "3 chunks", True, False)
    + stage("done", "Generating cards", "", "3 / 3", False, False)
    + stage("active", "Removing near-duplicates", "First run loads a model, ~25s", "24s", False, False)
    + stage("pending", "Writing CSV", "", "", False, True)
    + "</div>"
)


def build(name: str, results: str, height: int = 860, empty_sidebar: bool = False) -> None:
    template = MAIN.read_text(encoding="utf-8")
    head, _, rest = template.partition('<div class="res">')
    _, _, tail = rest.partition("</div>\n\n  </div>")

    if empty_sidebar:
        head = head.replace("3,157 chars", "0 chars")
        head = head.replace(
            "border: 1px solid #2e323b", "border: 1px dashed #2e323b", 1
        )
        start = head.index("color: #c3c8d0;\">") + len("color: #c3c8d0;\">")
        end = head.index("</div>", start)
        head = head[:start] + "Paste lecture notes here…" + head[end:]
        head = head.replace("color: #c3c8d0;\">Paste", "color: #575d67;\">Paste")
        head = head.replace(
            'background: #d99a4e; color: #17140f;\n            font-size: 15px',
            'background: #2a2620; color: #6b6152;\n            font-size: 15px',
        )

    page = f"{head}<div class=\"res\">{results}</div>\n\n  </div>{tail}"
    page = page.replace("min-height: 860px", f"min-height: {height}px")
    (HERE / f"{name}.dc.html").write_text(page, encoding="utf-8")
    print(f"wrote {name}.dc.html")


if __name__ == "__main__":
    build(
        "Empty",
        '<div style="border:1px dashed #2a2d35;border-radius:10px;padding:120px 24px;'
        'text-align:center"><p style="margin:0;font-size:13px;color:#575d67">'
        "Cards appear here once you generate.</p></div>",
        empty_sidebar=True,
    )
    build("Preview", ESTIMATE)
    build("Generating", PROGRESS + GRID.format("".join(CARDS[:2])), height=980)
    build("Results", SUMMARY + DOWNLOAD + GRID.format("".join(CARDS)), height=1080)
