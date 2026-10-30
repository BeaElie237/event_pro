"""Kafka consumer: events.incoming -> normalize -> embed -> upsert PostgreSQL.

Delivery: at-least-once (offsets committed after the DB transaction) +
idempotent upsert on ``fingerprint`` => effectively-once in the database.
Invalid messages go to the dead-letter topic instead of blocking the partition.

    python -m app.consumer
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from datetime import UTC, date, datetime

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord
from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError

from app.config import StreamingSettings, get_settings
from app.repository import EventWriter
from eventpro_common.embeddings import get_embedder
from eventpro_common.normalization import normalize_event
from eventpro_common.schemas import NormalizedEvent, RawEvent

logger = logging.getLogger("eventpro.consumer")


class IngestionConsumer:
    def __init__(self, settings: StreamingSettings) -> None:
        self.settings = settings
        self.embedder = get_embedder()
        self._stop = asyncio.Event()
        self._consumer = AIOKafkaConsumer(
            settings.kafka_topic_events,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_poll_records=settings.consumer_batch_size,
        )
        self._dlq = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers, acks="all")
        self._pool = AsyncConnectionPool(settings.database_dsn, min_size=1, max_size=4, open=False)
        self._writer = EventWriter(self._pool, self.embedder.model_name)

    def request_stop(self) -> None:
        logger.info("Shutdown requested")
        self._stop.set()

    async def _to_dlq(self, record: ConsumerRecord, reason: str) -> None:
        envelope = {
            "reason": reason[:2000],
            "topic": record.topic,
            "partition": record.partition,
            "offset": record.offset,
            "failed_at": datetime.now(UTC).isoformat(),
            "payload": record.value.decode("utf-8", errors="replace") if record.value else None,
        }
        await self._dlq.send_and_wait(self.settings.kafka_topic_dlq, json.dumps(envelope).encode(), key=record.key)

    async def _parse(self, records: list[ConsumerRecord]) -> list[NormalizedEvent]:
        today = date.today()
        events: dict[str, NormalizedEvent] = {}
        for record in records:
            try:
                event = normalize_event(RawEvent.model_validate_json(record.value or b""))
            except (ValidationError, ValueError) as exc:
                await self._to_dlq(record, f"{type(exc).__name__}: {exc}")
                continue
            if event.is_expired(today):
                logger.debug("Skipping expired event %s", event.fingerprint)
                continue
            # Deduplicate inside the batch (ON CONFLICT cannot touch the same row twice)
            events[event.fingerprint] = event
        return list(events.values())

    async def _process(self, records: list[ConsumerRecord]) -> None:
        events = await self._parse(records)
        if events:
            vectors = await asyncio.to_thread(self.embedder.encode, [e.embedding_text for e in events])
            written = await self._writer.upsert_many(events, vectors)
            logger.info("Upserted %d event(s) from %d message(s)", written, len(records))

    async def run(self) -> None:
        await asyncio.to_thread(self.embedder.encode_one, "warmup")
        await self._pool.open(wait=True)
        await self._dlq.start()
        await self._consumer.start()
        logger.info("Consuming %s as group %s", self.settings.kafka_topic_events, self.settings.kafka_consumer_group)
        try:
            while not self._stop.is_set():
                batches = await self._consumer.getmany(
                    timeout_ms=self.settings.consumer_poll_timeout_ms,
                    max_records=self.settings.consumer_batch_size,
                )
                records = [record for partition_records in batches.values() for record in partition_records]
                if not records:
                    continue
                # On DB failure the exception propagates: offsets are NOT committed,
                # the container restarts and the batch is replayed (idempotent upsert).
                await self._process(records)
                await self._consumer.commit()
        finally:
            await self._consumer.stop()
            await self._dlq.stop()
            await self._pool.close()


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    consumer = IngestionConsumer(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, consumer.request_stop)
        except NotImplementedError:  # Windows dev runs
            pass
    await consumer.run()


if __name__ == "__main__":
    asyncio.run(main())
