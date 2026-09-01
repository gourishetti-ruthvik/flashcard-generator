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

To reach it from another device on the same network:

```powershell
$env:GRADIO_SERVER_NAME="0.0.0.0"; python app.py
```

Then open `http://<this-machine's-lan-ip>:7860`.

For a temporary public link set `GRADIO_SHARE="True"` instead — but add
`auth=("user", "password")` to `launch()` first, because the generated URL is
publicly guessable and anyone holding it spends your quota.

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
| `design/` | Retired. A pointer saying the old dark layout was superseded. |

The folder names predate what they ended up holding; `design-directions/` is the
current design, not a set of options.

## Tests

```powershell
pytest
```

175 tests, no network calls. The SDK client is stubbed and the embedding encoder
is faked, so the suite runs offline in about 3 seconds.

## Benchmark results

`flashcards benchmark` compares JSON mode (`response_schema`) against
prompt-based JSON instructions, reporting parse-failure rate and mean latency
per arm. Both arms bypass the cache, so it costs `chunks x 2 x repeats` fresh
calls.

Run over `notes/` on 2026-09-01, `gemini-2.5-flash`, `--repeats 5`:

| Arm | Runs | Failed | Rate | Mean latency |
|---|---|---|---|---|
| JSON mode (`response_schema`) | 9 | 0 | 0% | 8.81s |
| Prompt-based JSON instructions | 6 | 0 | 0% | 7.36s |

Cards produced: 40 against 26. Code fences stripped: **0 of 6** prompt-based
replies. 75 requests were spent to land those 15 runs.

**Neither arm failed to parse, and the control arm needed no cleaning up after.**
That last number answers the caveat from the first run: the prompt-based arm's
0% is not an artefact of a lenient parser, because the model never fenced its
output. On short, clean prose it returns valid JSON to a well-specified prompt.

Three things stop this being a clean result:

- **30 calls were requested and 15 landed.** The rest exhausted quota and were
  counted as API errors, deliberately kept out of the failure rate -- running out
  of quota says nothing about whether an arm can produce JSON. 75 requests for 15
  runs is the retry overhead.
- **The latency figures include throttling.** The timer wrapped the whole call,
  which blocks on the rate limiter and on backoff, so 8.81s is mostly waiting.
  This is fixed -- the client now exposes `last_call_seconds` for the HTTP call
  alone -- but the numbers above were measured before the fix and are not
  comparable to the 3.19s / 3.25s of the earlier 3-run pass.
- **The arms saw different sample sizes** (9 against 6), because quota ran out
  mid-run rather than evenly.

JSON mode stays the default: it moves the guarantee from a prompt the model may
ignore to a constraint applied at decode time. This run gives no evidence it is
faster or more reliable on inputs like these -- it gives evidence that on inputs
like these, the guarantee is not the thing doing the work.
