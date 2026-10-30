"""Async facade over the (CPU-bound) sentence-transformers model."""

from __future__ import annotations

import logging

from starlette.concurrency import run_in_threadpool

from eventpro_common.embeddings import EventEmbedder

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, model_name: str) -> None:
        self._embedder = EventEmbedder(model_name)
        self._ready = False

    @property
    def model_name(self) -> str:
        return self._embedder.model_name

    @property
    def ready(self) -> bool:
        return self._ready

    async def warmup(self) -> None:
        """Load the model at startup so the first request does not pay the download/load cost."""
        logger.info("Loading embedding model %s", self.model_name)
        await self.embed("warmup")
        logger.info("Embedding model ready (dim=%d)", self._embedder.dimension)

    async def embed(self, text: str) -> list[float]:
        # Encoding blocks for tens of ms: keep it off the event loop.
        vector = await run_in_threadpool(self._embedder.encode_one, text)
        self._ready = True
        return vector
