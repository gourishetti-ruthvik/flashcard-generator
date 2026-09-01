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

**Free tier is 5 RPM on `gemini-2.5-flash`**, measured — the API rejects the 6th
call in a minute reporting `quotaValue: 5`, not the widely quoted 15.

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
per arm. Both arms bypass the cache, so it costs `chunks x 2` fresh calls.

**Results are not yet recorded.** Every attempted run so far exhausted the free
tier's quota and spent its time in 429 backoff rather than producing numbers.
This section should be filled in from a real run once quota allows — writing
plausible-looking figures here would defeat the point of measuring.
