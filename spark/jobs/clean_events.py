"""Batch job: raw scraped events -> cleaned, normalized, deduplicated, embedded parquet.

    spark-submit spark/jobs/clean_events.py \
        --data-dir data --batch-date 2026-10-30

Input  : <data-dir>/raw/*/batch_date=<d>/*.jsonl          (RawEvent JSON lines)
Output : <data-dir>/processed/events/batch_date=<d>/       (parquet, 1 row per unique event)
         <data-dir>/processed/rejected/batch_date=<d>/     (json, invalid records + reason)

Normalization rules live in ``eventpro_common`` so that the streaming consumer
produces exactly the same fingerprints, categories and embedding texts.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

from spark_utils import build_spark, configure_logging, emit_metrics

log = configure_logging()

RAW_SCHEMA = T.StructType(
    [
        T.StructField(name, T.ArrayType(T.StringType()) if name == "tags" else T.StringType())
        for name in (
            "source", "source_event_id", "title", "description", "url", "start_date", "end_date",
            "deadline", "location", "organizer", "category_hint", "funding_hint", "tags", "language",
            "scraped_at",
            "extra",  # JSON object kept as raw string by Spark when declared StringType
        )
    ]
)

_STRING_OUTPUTS = (
    "fingerprint", "source", "source_event_id", "title", "description", "url", "category",
    "funding_type", "event_format", "organizer", "location_raw", "city", "country_code",
    "country_name", "continent", "start_date", "end_date", "deadline", "tags", "language",
    "scraped_at", "embedding_text", "raw_payload", "error",
)
NORMALIZED_SCHEMA = T.StructType(
    [T.StructField(name, T.StringType()) for name in _STRING_OUTPUTS]
    + [T.StructField("completeness", T.IntegerType()), T.StructField("expired", T.BooleanType())]
)
NORMALIZED_COLUMNS = [f.name for f in NORMALIZED_SCHEMA.fields]


def _normalize_record(record: dict[str, Any], today: date) -> dict[str, Any]:
    """Runs on Python workers. Never raises: failures become rows with ``error`` set."""
    from eventpro_common.normalization import normalize_event
    from eventpro_common.schemas import RawEvent

    payload = {k: v for k, v in record.items() if v is not None}
    try:
        payload["tags"] = json.loads(payload.get("tags") or "[]")
        payload["extra"] = json.loads(payload["extra"]) if payload.get("extra") else {}
        event = normalize_event(RawEvent.model_validate(payload))
    except Exception as exc:  # noqa: BLE001 - any bad record is quarantined, not fatal
        empty = dict.fromkeys(NORMALIZED_COLUMNS)
        return {
            **empty,
            "source": record.get("source"),
            "title": record.get("title"),
            "raw_payload": json.dumps(record, default=str, ensure_ascii=False),
            "error": f"{type(exc).__name__}: {exc}"[:1000],
            "completeness": 0,
            "expired": False,
        }

    def iso(value: date | None) -> str | None:
        return value.isoformat() if value else None

    return {
        "fingerprint": event.fingerprint,
        "source": event.source,
        "source_event_id": event.source_event_id,
        "title": event.title,
        "description": event.description,
        "url": event.url,
        "category": event.category.value,
        "funding_type": event.funding_type.value,
        "event_format": event.event_format.value,
        "organizer": event.organizer,
        "location_raw": event.location_raw,
        "city": event.city,
        "country_code": event.country_code,
        "country_name": event.country_name,
        "continent": event.continent,
        "start_date": iso(event.start_date),
        "end_date": iso(event.end_date),
        "deadline": iso(event.deadline),
        "tags": json.dumps(event.tags, ensure_ascii=False),
        "language": event.language,
        "scraped_at": event.scraped_at.isoformat(),
        "embedding_text": event.embedding_text,
        "raw_payload": json.dumps(event.raw_payload, ensure_ascii=False),
        "error": None,
        "completeness": event.completeness,
        "expired": event.is_expired(today),
    }


def make_normalize_udf(today: date):  # noqa: ANN201 - returns a pandas UDF
    @F.pandas_udf(NORMALIZED_SCHEMA)  # type: ignore[call-overload]
    def normalize(raw: pd.DataFrame) -> pd.DataFrame:
        rows = [_normalize_record(record, today) for record in raw.to_dict("records")]
        return pd.DataFrame(rows, columns=NORMALIZED_COLUMNS)

    return normalize


@F.pandas_udf(T.ArrayType(T.FloatType()))  # type: ignore[call-overload]
def embed(texts: pd.Series) -> pd.Series:
    """One model instance per Python worker (cached by get_embedder)."""
    from eventpro_common.embeddings import get_embedder

    return pd.Series(get_embedder().encode(texts.fillna("").tolist()))


def normalize(raw: DataFrame, today: date) -> DataFrame:
    # Arrays/objects travel as JSON strings: simpler and safer through Arrow.
    struct_cols: list[Column] = [
        F.to_json("tags").alias("tags") if f.name == "tags" else F.col(f.name) for f in RAW_SCHEMA.fields
    ]
    return raw.select(make_normalize_udf(today)(F.struct(*struct_cols)).alias("n")).select("n.*")


def cast_types(df: DataFrame) -> DataFrame:
    return (
        df.withColumn("start_date", F.to_date("start_date"))
        .withColumn("end_date", F.to_date("end_date"))
        .withColumn("deadline", F.to_date("deadline"))
        .withColumn("scraped_at", F.col("scraped_at").cast("timestamp"))
        .withColumn("tags", F.from_json("tags", T.ArrayType(T.StringType())))
    )


def deduplicate(df: DataFrame) -> DataFrame:
    """Two passes: same canonical URL, then same fingerprint (title + date + place).

    Within a duplicate group, the most complete then most recent record wins.
    """
    best_first = [F.col("completeness").desc(), F.col("scraped_at").desc_nulls_last(), F.col("source")]

    by_url = Window.partitionBy("url").orderBy(*best_first)
    with_url = (
        df.filter(F.col("url").isNotNull())
        .withColumn("_rank", F.row_number().over(by_url))
        .filter(F.col("_rank") == 1)
        .drop("_rank")
    )
    df = with_url.unionByName(df.filter(F.col("url").isNull()))

    by_fingerprint = Window.partitionBy("fingerprint").orderBy(*best_first)
    return (
        df.withColumn("_rank", F.row_number().over(by_fingerprint))
        .filter(F.col("_rank") == 1)
        .drop("_rank")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=os.getenv("EVENTPRO_DATA_DIR", "data"))
    parser.add_argument("--batch-date", required=True, type=date.fromisoformat)
    parser.add_argument("--keep-expired", action="store_true", help="Keep events whose deadline/dates are past")
    parser.add_argument("--skip-embeddings", action="store_true", help="Debug only: no vectors produced")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    batch = args.batch_date.isoformat()
    data_dir = Path(args.data_dir)
    raw_glob = str(data_dir / "raw" / "*" / f"batch_date={batch}" / "*.jsonl")
    out_events = str(data_dir / "processed" / "events" / f"batch_date={batch}")
    out_rejected = str(data_dir / "processed" / "rejected" / f"batch_date={batch}")

    spark = build_spark(f"eventpro-clean-{batch}")
    raw = spark.read.schema(RAW_SCHEMA).option("mode", "PERMISSIVE").json(raw_glob)

    normalized = normalize(raw, today=args.batch_date).cache()
    rejected = normalized.filter(F.col("error").isNotNull())
    valid = cast_types(normalized.filter(F.col("error").isNull()))
    if not args.keep_expired:
        valid = valid.filter(~F.col("expired"))

    unique = deduplicate(valid).drop("error", "expired")
    model_name = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    if args.skip_embeddings:
        unique = unique.withColumn("embedding", F.lit(None).cast(T.ArrayType(T.FloatType())))
    else:
        unique = unique.withColumn("embedding", embed(F.col("embedding_text")))
    unique = unique.withColumn("embedding_model", F.lit(model_name)).withColumn("batch_date", F.lit(batch))

    unique.coalesce(4).write.mode("overwrite").parquet(out_events)
    rejected.select("source", "title", "error", "raw_payload").coalesce(1).write.mode("overwrite").json(out_rejected)

    written = spark.read.parquet(out_events)
    metrics = {
        "batch_date": batch,
        "raw_records": normalized.count(),
        "rejected": rejected.count(),
        "valid": valid.count(),
        "unique_events": written.count(),
        "by_category": {r["category"]: r["count"] for r in written.groupBy("category").count().collect()},
        "output": out_events,
    }
    log.info("clean_events done: %s", metrics)
    spark.stop()
    emit_metrics(metrics)


if __name__ == "__main__":
    main()
