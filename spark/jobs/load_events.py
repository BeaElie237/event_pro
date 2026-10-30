"""Batch job: processed parquet -> PostgreSQL ``staging_events`` (JDBC).

    spark-submit --jars /opt/spark-jars/postgresql.jar spark/jobs/load_events.py \
        --data-dir data --batch-date 2026-10-30

The staging table is TRUNCATEd then reloaded (idempotent). Vectors, tags and
payloads are sent as text and cast server-side by merge_staging_events.sql,
which upserts into ``events`` ON CONFLICT (fingerprint).
"""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from spark_utils import build_spark, configure_logging, emit_metrics

log = configure_logging()

STAGING_COLUMNS = (
    "fingerprint", "source", "source_event_id", "title", "description", "url", "category",
    "funding_type", "event_format", "organizer", "location_raw", "city", "country_code",
    "country_name", "continent", "start_date", "end_date", "deadline", "tags", "language",
    "embedding", "embedding_model", "raw_payload", "scraped_at", "batch_date",
)


def to_staging(df: DataFrame, batch_date: date) -> DataFrame:
    pgvector_literal = F.when(
        F.col("embedding").isNotNull(),
        F.concat(F.lit("["), F.concat_ws(",", F.col("embedding").cast("array<string>")), F.lit("]")),
    )
    return df.select(
        *[c for c in STAGING_COLUMNS if c not in {"tags", "embedding", "batch_date"}],
        F.to_json("tags").alias("tags"),
        pgvector_literal.alias("embedding"),
        F.lit(batch_date.isoformat()).cast("date").alias("batch_date"),
    ).select(*STAGING_COLUMNS)


def jdbc_options() -> dict[str, str]:
    host = os.getenv("EVENTPRO_DB_HOST", "localhost")
    port = os.getenv("EVENTPRO_DB_PORT", "5432")
    name = os.getenv("EVENTPRO_DB_NAME", "eventpro")
    return {
        "url": f"jdbc:postgresql://{host}:{port}/{name}",
        "user": os.environ["EVENTPRO_DB_USER"],
        "password": os.environ["EVENTPRO_DB_PASSWORD"],
        "driver": "org.postgresql.Driver",
        "dbtable": "staging_events",
        "truncate": "true",  # keep the table definition, only delete rows
        "batchsize": "1000",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=os.getenv("EVENTPRO_DATA_DIR", "data"))
    parser.add_argument("--batch-date", required=True, type=date.fromisoformat)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = str(Path(args.data_dir) / "processed" / "events" / f"batch_date={args.batch_date.isoformat()}")

    spark = build_spark(f"eventpro-load-{args.batch_date.isoformat()}")
    staging = to_staging(spark.read.parquet(source), args.batch_date).cache()
    rows = staging.count()

    staging.write.format("jdbc").options(**jdbc_options()).mode("overwrite").save()
    log.info("Loaded %d rows into staging_events from %s", rows, source)
    spark.stop()
    emit_metrics({"batch_date": args.batch_date.isoformat(), "staged_rows": rows})


if __name__ == "__main__":
    main()
