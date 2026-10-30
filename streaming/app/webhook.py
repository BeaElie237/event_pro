"""Webhook receiver (producer side): partners/alerts POST events, we publish them to Kafka.

The HTTP layer only authenticates, validates and enqueues: heavy work
(normalization, embeddings, DB writes) happens in the consumer, so a burst of
webhooks never blocks or loses data.

Signature: header ``X-EventPro-Signature: sha256=<hex(hmac_sha256(secret, raw_body))>``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from aiokafka import AIOKafkaProducer
from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import TypeAdapter, ValidationError

from app.config import get_settings
from eventpro_common.schemas import RawEvent

logger = logging.getLogger("eventpro.webhook")
_payload_adapter: TypeAdapter[RawEvent | list[RawEvent]] = TypeAdapter(RawEvent | list[RawEvent])


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks="all",
        enable_idempotence=True,
        compression_type="gzip",
        linger_ms=20,
    )
    await producer.start()
    app.state.producer = producer
    try:
        yield
    finally:
        await producer.stop()


app = FastAPI(title="EventPro Ingestion Webhook", version="0.1.0", lifespan=lifespan)


def verify_signature(body: bytes, signature: str | None) -> None:
    settings = get_settings()
    secret = settings.webhook_secret.get_secret_value()
    if not settings.webhook_require_signature:
        return
    if not secret or not signature or not signature.startswith("sha256="):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or malformed signature")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.removeprefix("sha256=")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/events", status_code=status.HTTP_202_ACCEPTED)
async def receive_events(
    request: Request,
    x_eventpro_signature: Annotated[str | None, Header()] = None,
) -> dict[str, int]:
    body = await request.body()
    verify_signature(body, x_eventpro_signature)

    try:
        parsed = _payload_adapter.validate_json(body)
    except ValidationError as exc:
        # exc.json() is always serializable (errors() may embed exception objects)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, json.loads(exc.json(include_url=False))) from exc
    events = parsed if isinstance(parsed, list) else [parsed]
    if len(events) > get_settings().webhook_max_batch:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Too many events in one call")

    producer: AIOKafkaProducer = request.app.state.producer
    topic = get_settings().kafka_topic_events
    for event in events:
        # Same key -> same partition -> per-source ordering preserved
        key = f"{event.source}:{event.source_event_id or event.title}".encode()
        await producer.send(topic, key=key, value=event.model_dump_json().encode())
    await producer.flush()
    logger.info("Accepted %d event(s) from webhook", len(events))
    return {"accepted": len(events)}


def sign(body: dict | list, secret: str) -> str:
    """Helper for partners/tests: compute the expected signature header value."""
    raw = json.dumps(body).encode()
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
