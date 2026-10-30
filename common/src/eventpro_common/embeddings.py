"""Embedding model wrapper and canonical text builders.

Events and user profiles MUST be embedded with the same model and comparable
text templates, otherwise cosine similarity is meaningless. Vectors are
L2-normalized so cosine similarity == dot product.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterable, Sequence
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
MAX_DESCRIPTION_CHARS = 2000


class EventEmbedder:
    """Thread-safe, lazily loaded sentence-transformers model."""

    def __init__(self, model_name: str | None = None, *, device: str | None = None, batch_size: int = 32) -> None:
        self.model_name = model_name or os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL)
        self.device = device or os.getenv("EMBEDDING_DEVICE", "cpu")
        self.batch_size = batch_size
        self._model: SentenceTransformer | None = None
        self._lock = threading.Lock()

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    @property
    def dimension(self) -> int:
        dim = self.model.get_sentence_embedding_dimension()
        return int(dim) if dim is not None else EMBEDDING_DIM

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.astype("float32").tolist()

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]


@lru_cache(maxsize=4)
def get_embedder(model_name: str | None = None) -> EventEmbedder:
    """Process-wide singleton (one model per Python worker / Spark executor)."""
    return EventEmbedder(model_name)


def _join(values: Iterable[str] | None) -> str:
    return ", ".join(v.strip() for v in (values or ()) if v and v.strip())


def build_event_text(
    *,
    title: str,
    description: str | None,
    category: str | None,
    funding_type: str | None,
    location: str | None,
    organizer: str | None,
    tags: Iterable[str] | None,
) -> str:
    parts = [
        title.strip(),
        f"Type: {category}" if category else "",
        f"Financement: {funding_type}" if funding_type else "",
        f"Lieu: {location}" if location else "",
        f"Organisateur: {organizer}" if organizer else "",
        f"Thèmes: {_join(tags)}" if tags else "",
        (description or "")[:MAX_DESCRIPTION_CHARS],
    ]
    return "\n".join(p for p in parts if p)


def build_profile_text(
    *,
    headline: str | None,
    bio: str | None,
    skills: Iterable[str] | None,
    interests: Iterable[str] | None,
    goals: Iterable[str] | None,
    preferred_categories: Iterable[str] | None = None,
    location: str | None = None,
) -> str:
    parts = [
        headline or "",
        f"Compétences: {_join(skills)}" if skills else "",
        f"Centres d'intérêt: {_join(interests)}" if interests else "",
        f"Objectifs: {_join(goals)}" if goals else "",
        f"Recherche: {_join(preferred_categories)}" if preferred_categories else "",
        f"Lieu: {location}" if location else "",
        (bio or "")[:MAX_DESCRIPTION_CHARS],
    ]
    return "\n".join(p for p in parts if p)


def to_pgvector_literal(vector: Sequence[float]) -> str:
    """Text literal accepted by pgvector (``'[0.1,0.2]'::vector``)."""
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"
