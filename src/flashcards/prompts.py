from __future__ import annotations

from flashcards.models import Chunk

# "Answerable without seeing the source notes" cannot be expressed in the JSON
# schema, so it has to be carried by the prompt and then enforced again by the
# validator stage.
_RULES = """You are writing study flashcards from one section of a student's notes.

Write at most {max_cards} flashcards covering the most important ideas in the
source text below.

Rules:
- Each question must stand alone. Someone who has never seen these notes must be
  able to answer it. Never write "according to the text", "in the passage",
  "as mentioned above", or similar.
- Name the subject explicitly in the question. Do not write "this concept",
  "this method", or a bare "it".
- Answers must be self-contained and factual, one to three sentences.
- topic: the subject area the card belongs to, two to four words.
- difficulty: "easy" for recall or a definition, "medium" for comparison or
  application, "hard" for trade-offs or edge cases.
- Prefer fewer excellent cards over padding the list to the limit.
"""

# Only the benchmark's control arm uses this. In JSON mode the schema is
# enforced server-side and none of it is needed.
_JSON_FORMAT = """
Return ONLY a JSON array and nothing else: no prose, no explanation, no markdown
code fences. Each element must be an object with exactly these four keys:
  "question": string
  "answer": string
  "topic": string
  "difficulty": one of "easy", "medium", "hard"
"""

_SOURCE = """
Section heading: {heading}

Source text:
{text}"""


def _compose(chunk: Chunk, max_cards: int, extra: str = "") -> str:
    return (
        _RULES.format(max_cards=max_cards)
        + extra
        + _SOURCE.format(heading=chunk.heading or "(none)", text=chunk.text)
    )


def build_generation_prompt(chunk: Chunk, max_cards: int) -> str:
    return _compose(chunk, max_cards)


def build_json_instruction_prompt(chunk: Chunk, max_cards: int) -> str:
    return _compose(chunk, max_cards, _JSON_FORMAT)
