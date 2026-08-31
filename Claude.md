# Project: Flashcard Generator

Converts study notes (Markdown/text) into Anki-importable flashcards
using the Gemini API. CLI tool, no web UI.

## Environment

- Windows. VS Code terminal, PowerShell.
- Python 3.11+, virtual env at `.venv` (already created and activated).
- Use `pathlib.Path` for ALL filesystem paths. Never build paths with
  string concatenation or hardcoded `/` separators.
- Always pass `encoding="utf-8"` explicitly to `open()` and to any CSV
  writer. Windows defaults to cp1252 and will mangle output.
- When suggesting terminal commands, give PowerShell syntax.
  No `&&` chaining, no `printf`, no `source`.

## Stack

- `google-genai` SDK, Pydantic v2, Typer, python-dotenv, pytest
- `sentence-transformers` for local deduplication only
- NOT allowed: LangChain, LlamaIndex, any vector database, any web framework
- Add no dependency without asking me first

## Code conventions

- Type hints on every function signature.
- Pydantic models at every LLM input/output boundary.
- No bare `except:`. Catch specific exceptions.
- Secrets loaded from `.env`. Never hardcode or log an API key.
- Comments explain *why*, not *what*. No docstrings that restate the signature.
- Prefer small, testable functions over clever one-liners.

## API constraints

- Gemini free tier: 5 RPM on `gemini-2.5-flash` (measured — the API rejects the
  6th call in a minute reporting `quotaValue: 5`, not the widely quoted 15),
  ~1500 RPD. This is a hard ceiling.
- Every API call MUST route through the client wrapper in
  `src/flashcards/client.py`. Nothing else touches the API directly.
- The wrapper provides: disk cache keyed on prompt hash, token-bucket rate
  limiter, exponential backoff with jitter on 429, request counter.
- Tests must never make real API calls. Mock the client.
- Model ID is a config value, never a string literal in business logic.

## Working style

I am a final-year CS student learning this stack. So:

- Default to Plan Mode. Do not write code until I approve a plan.
- After each phase, give me 3 bullets: the key design decision, the
  alternative you rejected, and why. Do not skip this.
- If you are unsure about SDK syntax or a library's current API, say so
  and verify. Do not invent a plausible-looking method name.
- Prefer the boring, readable solution over the clever one.