# Flashcard Generator

Turns study notes into Anki-importable flashcards using the Gemini API.
Runs as a CLI, or as a website in the browser.

## Install

```powershell
cd C:\Users\gouri\Desktop\Claude_Projects\Project_1\flashcard-generator
.\.venv\Scripts\Activate.ps1
pip install -e .
```

Put your key in `.env` (already gitignored):

```
GEMINI_API_KEY=your-key-here
```

Optional extras: `pip install -e ".[dedupe]"` for near-duplicate removal,
`pip install -e ".[app]"` for the web UI.

## CLI usage

```powershell
flashcards generate notes/ --dry-run
flashcards generate notes/ --out cards.csv
flashcards generate notes/ --out cards.csv --limit 5
flashcards benchmark notes/
```

| Flag | Meaning |
|---|---|
| `--out` | Write an Anki CSV |
| `--dry-run` | Report chunks and estimated requests, call nothing |
| `--limit N` | Process only N chunks — the throttle that matters on a free tier |
| `--no-dedupe` | Skip near-duplicate removal |

`flashcards benchmark` has its own flags, all of them there because 20 calls a
day is not enough to finish a run in one sitting:

| Flag | Meaning |
|---|---|
| `--results PATH` | Append each call's outcome as it happens (default `benchmark-results.jsonl`) |
| `--resume` | Skip calls already recorded, and retry the ones quota refused |
| `--repeats N` | Passes over each arm |
| `--quota-stop N` | Give up after N consecutive API errors instead of grinding |
| `--max-attempts N` | Attempts per call, default 2 — each retry spends a request |

Import the CSV with **File → Import** in Anki. The file carries
`#separator:Comma` and `#columns:Front,Back,Tags`, so field mapping is automatic.

## Website

```powershell
python app.py
```

Serves on `http://127.0.0.1:7860`. Two columns on a desktop window — the form on
the left, results on the right — collapsing to one column below 900px. Paste
notes or upload `.md`/`.txt`, press **Preview** for a free estimate, then
**Generate**.

The header carries a **daily ration**: twenty tick marks that fill as requests
are spent, because the 20-a-day cap is otherwise invisible until it bites. The
count is recorded inside the client wrapper, so the CLI, the benchmark and the
website all move the same number — `flashcards generate` and `flashcards
benchmark` print it too. It lives in `.llm_cache/daily-usage.json`, keyed by
Pacific day so it resets when Google's cap does, and a 429 does not count
against it: that is the quota refusing a request, not consuming one.

Preview costs nothing and prices the run before you commit: the Generate button
relabels itself to *"spends 3 of your 20"*. Light and dark both ship, following
`prefers-color-scheme` until you pick one from the header toggle — three radios
and `:has()`, no JavaScript.

To reach it from another device on the same network:

```powershell
$env:GRADIO_SERVER_NAME="0.0.0.0"; python app.py
```

Then open `http://<this-machine's-lan-ip>:7860`.

### Reaching it from outside the house

```powershell
$env:GRADIO_SHARE="True"
$env:FLASHCARDS_USER="you"; $env:FLASHCARDS_PASSWORD="something-long"
python app.py
```

The app **refuses to start if it would be reachable beyond localhost** unless
both are set — that covers a share tunnel *and* binding to `0.0.0.0`, which is
what LAN access and every hosting platform need. If your home network is
genuinely trusted and a password on every phone visit is just friction, set
`FLASHCARDS_ALLOW_OPEN=1` to opt out by name. The default stays closed. A share URL is
reachable by anyone holding it and guessable enough to be found, and behind it
sits a key spending a 20-a-day allowance, so an unauthenticated tunnel is not a
convenience — it is someone else's quota.

The tunnel needs **outbound TCP 7000** to `gradio-tunneling.hf.space`. That port
times out on some networks (it does on the one this was built on), and the only
symptom Gradio gives is "Could not create share link. Please check your internet
connection", which points at the wrong thing. Test it before blaming the app:

```powershell
python -c "import socket; s=socket.socket(); s.settimeout(15); s.connect(('gradio-tunneling.hf.space',7000)); print('open')"
```

If that times out, the share link cannot work on that network. A different one
— a phone hotspot, say — may well be fine.

### Deploying it (Render free tier)

`render.yaml` is a blueprint: in Render, **New → Blueprint**, point it at this
repo, and it creates the service. Then set three variables in the dashboard —
`GEMINI_API_KEY`, `FLASHCARDS_USER`, `FLASHCARDS_PASSWORD`. They are marked
`sync: false`, so Render asks for them and stores them itself; none of the three
is ever in git.

What the free plan costs you, both specific to this app:

- **The disk is wiped on every spin down** (15 minutes idle). That resets the
  ration counter, so the header says *"spent since restart"* there instead of
  claiming to know the day's total — the blueprint sets `FLASHCARDS_EPHEMERAL=1`
  to switch that wording. It also wipes `.llm_cache/`, so notes you have already
  processed cost quota again.
- **About a minute to wake up** from idle before the page loads.

### Why not Hugging Face Spaces

Because it is not free. From [their own docs](https://huggingface.co/docs/hub/spaces-overview#hardware-resources):

> The default CPU Basic hardware has no hourly cost, but creating a Space that
> runs on compute (Gradio or Docker) requires a paid plan, while Static Spaces
> are free for everyone.

Static Spaces serve files only. This app needs a server, because the API key has
to stay server-side — that is the whole reason it never reaches the browser. So
a Space means a paid plan, and if you ever take one, **make the Space private**:
a public one lets anyone spend your twenty a day.

## Architecture

```
loader -> chunker -> [client] -> validator -> dedupe -> exporter
```

| Module | Job |
|---|---|
| `config.py` | Settings from `.env`; the only place the model ID lives |
| `loader.py` | Find note files, strip Markdown (headings survive) |
| `chunker.py` | Split on headings, then paragraphs, then sentences |
| `prompts.py` | Build both prompt variants |
| `client.py` | The only thing that touches the API |
| `validator.py` | Semantic checks the JSON schema cannot express |
| `dedupe.py` | Cosine-similarity near-duplicate removal |
| `exporter.py` | Anki CSV |
| `pipeline.py` | Wires the stages |
| `cli.py` / `app.py` | Two front ends over the same pipeline |

### Decisions worth knowing

**Everything goes through `client.py`.** It owns the disk cache, a token-bucket
rate limiter, and jittered backoff. Nothing else imports `google.genai`.

**The cache key covers the model and every generation knob**, not just the
prompt. Keyed on the prompt alone it would replay one model's answers for
another, and would let a benchmark arm compare against its own cache.

**Cache lookup happens before the rate limiter.** A cached run consumes no quota,
so throttling it would be pure waiting.

**The validator checks meaning, not shape.** In JSON mode the schema is enforced
server-side, so malformed JSON is not the risk. The real failures are truncation
at `MAX_TOKENS` and safety blocks, and questions like "according to the text..."
that become unanswerable once the card is in Anki.

**Chunk sizes use a 4-chars-per-token estimate.** The real tokenizer is a network
call, and `--dry-run` must not make one.

**Free tier is 5 requests per minute and 20 per day on `gemini-2.5-flash`**, both
read off the API's own `QuotaFailure` details rather than the docs. The daily cap
is the one that bites: it is 20, not the widely quoted 1500, and every retry
spends one of the 20. That is why `--limit` exists, why the cache keys on the
model and every generation knob, and why the benchmark is resumable — anything
needing more than 20 calls simply cannot finish in a day.

## Design

Three canvases, none of them needed to run the app:

| Folder | What it holds |
|---|---|
| `design-directions/` | The current Ruled Paper design: nine screens plus the flip-card anatomy. `build_screens.py` generates them from one definition. |
| `design-motion/` | The drifting-ledger ground and card motion, as living artboards. |
| `design-press/` | **Press Room**, the current design: riso ground, the ration strip, every screen state in light and dark. `build_screens.py` generates the artboards; `contrast.py` measures the palette. |
| `design/` | Retired. A pointer saying the old dark layout was superseded. |

The folder names predate what they ended up holding; `design-directions/` is the
current design, not a set of options.

## Tests

```powershell
pytest
```

283 tests, no network calls. The SDK client is stubbed and the embedding encoder
is faked, so the suite runs offline in about 3 seconds.

## Benchmark results

`flashcards benchmark` compares JSON mode (`response_schema`) against
prompt-based JSON instructions, reporting parse-failure rate and mean latency
per arm. Both arms bypass the cache, so it costs `chunks x 2 x repeats` fresh
calls.

### Sizing a run

The free tier allows **20 requests per day**. That is the whole design
constraint:

| Run | Calls | Fits in a day? |
|---|---|---|
| 3 chunks, `--repeats 1` | 6 | yes, comfortably |
| 3 chunks, `--repeats 3` | 18 | yes — the largest that fits |
| 3 chunks, `--repeats 5` | 30 | **no** |

The 30-call version was attempted three times and never finished. It cannot:
the cap stops it at 20, and retries count too. Nine runs per arm from
`--repeats 3` is the most one day can buy.

### Running it across days

```powershell
flashcards benchmark notes/ --repeats 3
flashcards benchmark notes/ --repeats 3 --resume
```

The first command runs until quota stops it. Every completed call is already on
disk, so the second picks up exactly where it left off — the next day if need
be. Quota errors are not recorded, so `--resume` retries the calls that were
refused rather than skipping them.

### Method notes worth knowing

**Latency is the HTTP call alone.** The client exposes `last_call_seconds`.
Timing the wrapper instead folds in the rate limiter and backoff sleeps, which
is how a 3.2s call was once reported as 8.8s.

**The arms are interleaved and alternate which one leads.** Running every schema
call before every prompt call gives the first arm all the available quota; that
is what produced an earlier lopsided 9-vs-6 sample that looked like a property
of the arms.

**Quota errors are kept out of the failure rate.** Running out of quota says
nothing about whether an arm can produce valid JSON.

**The daily cap is never retried.** The client tells it apart from the
per-minute window by its `quotaId` and fails immediately. Its `RetryInfo` is
actively misleading -- probed once a minute for four minutes it returned 52s,
6s, 19s, 33s, 46s and finally 0s while refusing every call -- so backing off on
that hint costs another of the 20 requests to learn nothing. The per-minute
window is still retried, because waiting it out is what backoff is for.

**Fenced replies are counted.** The control arm strips Markdown code fences
before parsing, so without that count its 0% failure rate could equally mean
"the model always returned clean JSON" or "the harness cleaned up every time".

### Results

3 chunks, `--repeats 3`, full 18-call run (`benchmark-results.jsonl`), timer
fixed to the HTTP call alone:

| Arm | Runs | Failed | Rate | Mean latency | Cards |
|---|---|---|---|---|---|
| JSON mode (`response_schema`) | 9 | 0 | 0% | 2.90s | 38 |
| Prompt-based JSON instructions | 9 | 0 | 0% | 2.98s | 37 |

Code fences stripped: **0 of 9** prompt-based replies.

Nine runs per arm is a small sample, and the 0.08s latency gap is well within
call-to-call noise at this n — not a meaningful difference either way. No
parse failure occurred in either arm, so on this note set a well-specified
prompt returns valid JSON without the schema just as reliably as with it.

JSON mode stays the default regardless: it moves the guarantee from a prompt
the model may ignore to a constraint applied at decode time. This run gives no
evidence it is faster, but none that it is slower either, and the cost of a
prompt the model ignores (a failed chunk) is still worse than the cost of the
schema (nothing measurable).
