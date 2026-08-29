from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Flashcard(BaseModel):
    question: str
    answer: str
    topic: str
    difficulty: Literal["easy", "medium", "hard"]


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    # Provenance travels with the chunk so the exporter can tag cards by source
    # and a bad card can be traced back to the note that produced it.
    source_path: Path
    heading: str
    index: int
