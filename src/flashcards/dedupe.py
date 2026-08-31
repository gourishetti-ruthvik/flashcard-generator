from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from flashcards.models import SourcedCard

Encoder = Callable[[list[str]], Sequence[Sequence[float]]]


class DedupeUnavailable(RuntimeError):
    """sentence-transformers is not installed."""


def load_encoder(model_name: str) -> Encoder:
    # Imported here rather than at module scope so the package stays usable
    # without torch, which is ~2 GB of optional dependency.
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise DedupeUnavailable(
            'sentence-transformers is not installed. Run: pip install -e ".[dedupe]"'
        ) from exc

    model = SentenceTransformer(model_name)
    return lambda texts: model.encode(texts, normalize_embeddings=False).tolist()


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def deduplicate(
    entries: list[SourcedCard],
    threshold: float,
    model_name: str,
    encoder: Encoder | None = None,
) -> tuple[list[SourcedCard], list[SourcedCard]]:
    """Greedily keep the first of each near-duplicate group of questions."""
    if len(entries) < 2:
        return list(entries), []

    encode = encoder if encoder is not None else load_encoder(model_name)
    vectors = encode([entry.card.question for entry in entries])

    kept: list[SourcedCard] = []
    kept_vectors: list[Sequence[float]] = []
    dropped: list[SourcedCard] = []

    # ponytail: O(n^2) pairwise scan. Fine for the hundreds of cards a note
    # collection produces; swap for a vector index if it ever reaches tens of
    # thousands.
    for entry, vector in zip(entries, vectors):
        if any(cosine(vector, other) > threshold for other in kept_vectors):
            dropped.append(entry)
        else:
            kept.append(entry)
            kept_vectors.append(vector)

    return kept, dropped
