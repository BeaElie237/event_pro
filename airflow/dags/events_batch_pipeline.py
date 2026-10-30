"""
### events_batch_pipeline

Pipeline batch quotidien d'agrégation d'événements professionnels et académiques.

1. **resolve_batch_date** — date de partition (logical date, sinon aujourd'hui UTC).
2. **scrape_source** — une tâche mappée par source active de `include/sources.yaml`,
   écrit `data/raw/<source>/batch_date=<d>/events.jsonl`. Une source en échec
   n'empêche pas les autres d'être traitées.
3. **check_raw_data** — saute la suite si aucun événement brut n'a été collecté.
4. **spark_clean_events** — PySpark : nettoyage, normalisation, déduplication, embeddings
   → `data/processed/events/batch_date=<d>/`.
5. **spark_load_staging** — PySpark JDBC → table `staging_events`.
6. **merge_into_events** — upsert idempotent `ON CONFLICT (fingerprint)`.
7. **expire_past_events** — passe en `expired` les opportunités échues.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from airflow.exceptions import AirflowSkipException
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag, get_current_context, task

DATA_DIR = os.getenv("EVENTPRO_DATA_DIR", "/opt/airflow/data")
SPARK_DIR = os.getenv("EVENTPRO_SPARK_DIR", "/opt/airflow/spark")
SOURCES_FILE = os.getenv("EVENTPRO_SOURCES_FILE", "/opt/airflow/include/sources.yaml")
DB_CONN_ID = "eventpro_db"

# local[2] : chaque worker Python charge le modèle d'embedding (~500 Mo de RAM)
SPARK_SUBMIT = (
    "spark-submit --master ${SPARK_MASTER:-local[2]} "
    "--driver-memory ${SPARK_DRIVER_MEMORY:-2g} "
    "--jars /opt/spark-jars/postgresql.jar"
)
BATCH_DATE = "{{ ti.xcom_pull(task_ids='resolve_batch_date') }}"

default_args: dict[str, Any] = {
    "owner": "data-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(hours=1),
}


@dag(
    dag_id="events_batch_pipeline",
    description="Scraping multi-sources -> PySpark (clean/dedup/embed) -> PostgreSQL/pgvector",
    schedule="0 3 * * *",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    template_searchpath=[str(Path(__file__).parent / "sql")],
    tags=["eventpro", "batch", "spark", "pgvector"],
    doc_md=__doc__,
)
def events_batch_pipeline() -> None:
    @task
    def resolve_batch_date() -> str:
        logical_date = get_current_context().get("logical_date")
        return (logical_date or datetime.now(UTC)).date().isoformat()

    @task
    def list_sources() -> list[dict[str, Any]]:
        from scrapers import load_sources

        sources = load_sources(SOURCES_FILE)
        if not sources:
            raise AirflowSkipException(f"No enabled source in {SOURCES_FILE}")
        return [source.model_dump() for source in sources]

    @task(retries=3, max_active_tis_per_dagrun=4, execution_timeout=timedelta(minutes=15))
    def scrape_source(source: dict[str, Any], batch_date: str) -> dict[str, Any]:
        from scrapers import SourceConfig, build_scraper
        from scrapers.writer import raw_partition, write_jsonl

        config = SourceConfig.model_validate(source)
        target = raw_partition(DATA_DIR, config.name, batch_date)
        count = write_jsonl(build_scraper(config).scrape(), target)
        return {"source": config.name, "records": count, "path": str(target)}

    @task(trigger_rule="all_done")
    def check_raw_data(batch_date: str) -> int:
        """Reads the raw zone on disk (not XComs) so that failed sources are simply ignored."""
        files = sorted(Path(DATA_DIR, "raw").glob(f"*/batch_date={batch_date}/events.jsonl"))
        total = 0
        for path in files:
            with path.open(encoding="utf-8") as fh:
                total += sum(1 for line in fh if line.strip())
        if total == 0:
            raise AirflowSkipException(f"No raw events collected for {batch_date}")
        return total

    batch_date = resolve_batch_date()
    scraped = scrape_source.partial(batch_date=batch_date).expand(source=list_sources())
    raw_count = check_raw_data(batch_date)

    spark_clean = BashOperator(
        task_id="spark_clean_events",
        bash_command=(
            f"{SPARK_SUBMIT} {SPARK_DIR}/jobs/clean_events.py "
            f"--data-dir {DATA_DIR} --batch-date {BATCH_DATE}"
        ),
        execution_timeout=timedelta(hours=2),
    )

    spark_load = BashOperator(
        task_id="spark_load_staging",
        bash_command=(
            f"{SPARK_SUBMIT} {SPARK_DIR}/jobs/load_events.py "
            f"--data-dir {DATA_DIR} --batch-date {BATCH_DATE}"
        ),
    )

    merge = SQLExecuteQueryOperator(
        task_id="merge_into_events",
        conn_id=DB_CONN_ID,
        sql="merge_staging_events.sql",
    )

    expire = SQLExecuteQueryOperator(
        task_id="expire_past_events",
        conn_id=DB_CONN_ID,
        sql="expire_events.sql",
    )

    scraped >> raw_count >> spark_clean >> spark_load >> merge >> expire


events_batch_pipeline()
