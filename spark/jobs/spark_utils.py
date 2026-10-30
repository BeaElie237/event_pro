"""Shared SparkSession factory and helpers for EventPro jobs."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from pyspark.sql import SparkSession


def build_spark(app_name: str) -> SparkSession:
    """Session tuned for the local[*] mode used inside the Airflow worker.

    On a real cluster, master/memory come from spark-submit and the
    eventpro_common package must be shipped (wheel via --py-files or image).
    """
    builder = (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.execution.arrow.pyspark.enabled", "true")
        # Small Arrow batches bound the memory used by the embedding UDF
        .config("spark.sql.execution.arrow.maxRecordsPerBatch", os.getenv("SPARK_ARROW_BATCH", "64"))
        .config("spark.sql.shuffle.partitions", os.getenv("SPARK_SHUFFLE_PARTITIONS", "8"))
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
    )
    jars = os.getenv("SPARK_EXTRA_JARS")
    if jars:
        builder = builder.config("spark.jars", jars)
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel(os.getenv("SPARK_LOG_LEVEL", "WARN"))
    return spark


def configure_logging() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    return logging.getLogger("eventpro.spark")


def emit_metrics(metrics: dict[str, Any]) -> None:
    """Print metrics as the LAST stdout line: Airflow's BashOperator pushes it to XCom."""
    print(json.dumps(metrics, default=str), flush=True)
