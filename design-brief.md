# Design brief: Flashcards

Redesign the web UI for a study tool that turns lecture notes into
Anki-importable flashcards. The current design is competent but flat — it reads
as a form with a list beside it. I want something with real visual character
that still survives the technical constraints below.

---

## What the product does

A student pastes lecture notes (or uploads a `.md`/`.txt` file), presses a
button, and gets flashcards — question on the front, answer on the back — which
they can flip in the browser and download as a CSV to import into Anki.

One page. No login, no navigation, no settings screen. It runs locally in a
browser on a laptop, occasionally on a phone.

The user is one final-year CS student studying for exams. Not a team, not
customers. This is a personal tool, so it can be opinionated and unusual rather
than safe and corporate.

---

## The constraint that shapes everything: a 20-call daily budget

The Gemini free tier allows **20 API requests per day and 5 per minute**.
Measured from the API, not from docs. Generating cards from one page of notes
typically costs 3–11 requests.

So the user is spending from a small, invisible, non-renewable daily budget
every time they press Generate. Running out means waiting until tomorrow.

This is the most interesting design problem in the product, and the current
design barely acknowledges it. There are two buttons:

- **Preview · free** — counts chunks and estimates cost. Calls nothing. Free,
  instant, repeatable.
- **Generate** — actually spends requests.

Preview should feel like the natural, inviting first move rather than the
timid one. Generate should feel deliberate — a considered act, not a reflex.
That tension is worth designing around rather than papering over. I'm not
asking for a scary warning; I'm asking for a design where the cheap action
feels good and the expensive one feels weighty.

---

## Screens and states — all of these need designing

It is one page, but it has real states, and the current design only handles
two of them well.

1. **Empty / first load.** Nothing pasted, no results. Currently a dashed box
   saying "Cards appear here once you generate." This is the weakest screen
   and the first thing anyone sees.
2. **Notes pasted, not yet previewed.**
3. **Preview result.** Shows chunk count, estimated requests, estimated
   tokens. Costs nothing. Example: *"4 chunks · 4 requests · ~2,400 tokens"*.
4. **Generating.** Takes 3 seconds per chunk, and with the 5-per-minute limit
   a large job visibly pauses between calls. A 10-chunk job takes over a
   minute with dead air in the middle. This needs to not feel broken.
5. **Results.** A grid of flip cards plus a summary line and a download button.
6. **Partial success.** Some chunks produced cards, others failed. Both must
   show at once.
7. **Quota exhausted.** The daily 20 are gone. Nothing will work until
   tomorrow. Currently surfaces as a raw-ish error message. Deserves a real
   designed state — it is a normal weekly occurrence, not an exception.
8. **Error.** Missing API key, unreadable file, empty input.

---

## The flashcards themselves

The centrepiece. Each card has four fields:

- **question** — e.g. *"What are the four Coffman conditions for deadlock?"*
- **answer** — e.g. *"Mutual exclusion, hold and wait, no preemption, and
  circular wait. All four must hold simultaneously."*
- **topic** — e.g. *"Operating Systems"*
- **difficulty** — exactly one of `easy`, `medium`, `hard`

Cards flip on click: question on the front, answer on the back. A generation
run produces roughly 5 cards per chunk, so 5–40 cards on screen at once.

Answers vary a lot in length — one line to a full paragraph. **Cards must size
to their content.** A previous version fixed the height and either clipped long
answers or left short ones swimming in space. Do not reintroduce a fixed
height.

Difficulty currently shows as a small coloured tick mark, using a sage /
ochre / oxblood ramp chosen because it passes WCAG AA (contrast 5.03, 5.32,
7.03) and the three hues are far enough apart to distinguish. Feel free to
redesign how difficulty is expressed, but keep it distinguishable without
relying on colour alone, and keep contrast at AA or better.

---

## Hard technical constraints — please read before designing

**The page is rendered by Gradio**, a Python UI framework. I style it with
injected CSS and blocks of hand-written HTML. This bounds what I can build,
and a design that ignores it cannot ship.

**What I can do:**

- Any CSS: gradients, transforms, animations, `clip-path`, blend modes,
  custom properties, grid, flexbox, `@media`, `prefers-reduced-motion`.
- Any static HTML I generate from Python — arbitrary markup, inline SVG.
- CSS-only interactivity: `:hover`, `:focus-visible`, `:checked`, `:has()`,
  sibling selectors. The card flip already works this way — a hidden checkbox
  plus `transform: rotateY(180deg)`.
- Web fonts from Google Fonts.
- Server round-trips on button click: click → Python runs → HTML re-renders.

**What I cannot do:**

- **No client-side JavaScript state.** No React, no component library, no
  drag-and-drop, no canvas, no charting library, no virtualised scrolling.
  Anything needing JS to maintain state between clicks is out.
- No routing or multiple pages.
- No custom form controls. The text area, file upload, number input,
  checkbox and buttons are Gradio widgets. I can restyle them heavily with
  CSS but cannot replace them with bespoke components.
- Nothing depending on knowing scroll position, element size, or cursor
  coordinates.

**Rule of thumb:** if it works with CSS and a page re-render, I can build it.
If it needs `useState`, I can't.

**The widget inventory**, so you know exactly what exists:

| Element | Type |
|---|---|
| Notes | multiline textarea, placeholder "Paste lecture notes here…" |
| Upload | collapsible file input, `.md` / `.txt` |
| Max chunks | number input, default 5 — the quota throttle |
| Remove near-duplicates | checkbox, default on |
| Preview · free | button |
| Generate | button |
| Status / results area | server-rendered HTML |
| Download CSV | button, hidden until there are cards |

---

## What exists now

Warm off-white paper ground (`#faf7f2`), near-black ink text, Newsreader serif
for prose, IBM Plex Mono for labels and numbers. Two columns on desktop — form
left, results right — collapsing to one below 900px. A slow-drifting background
of faint blooms and horizontal rules. Cards are cream panels with a hairline
border.

**Keep:** the paper/ink feeling is right for a study tool, and the serif +
mono pairing works. Content-sized cards. AA contrast. Reduced-motion support.

**Change:** it's monotonous. Everything is the same weight, the same rectangle,
the same spacing. There's no focal point, no rhythm, nothing that rewards
looking at it. The empty state is a dashed box. The header is a title and a
rule. It looks like a form, and it should look like a tool someone made on
purpose.

You are not obliged to keep the paper palette. If a different direction is
stronger, show me — I'd rather see a real point of view than a safe iteration.
Just keep it legible for long study sessions and keep contrast at AA.

---

## What I'm asking for

Artboards covering: empty state, notes pasted, preview result, generating,
results with cards, quota exhausted, and an error state. Plus the card itself
in both faces, at short and long answer lengths, across all three difficulty
levels.

Desktop first, since that's where it's mostly used, but show the single-column
phone layout too — the breakpoint is 900px.

Include a light and dark treatment if the direction supports one.

---

## Explicit non-goals

No landing page, marketing section, onboarding, or feature tour. No login,
account, or settings screen. No dashboard, statistics, or study-streak
tracking — reviewing happens in Anki, not here. No AI-assistant chrome:
no chat bubbles, no sparkle icons, no "powered by" badges. This tool has one
job and should look like it knows that.
