"""Atomic JSONL writer for the raw zone (data/raw/<source>/batch_date=YYYY-MM-DD/)."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from eventpro_common.schemas import RawEvent


def raw_partition(data_dir: str | Path, source: str, batch_date: str) -> Path:
    return Path(data_dir) / "raw" / source / f"batch_date={batch_date}"


def write_jsonl(events: Iterable[RawEvent], target_dir: Path) -> int:
    """Write events then rename: Spark never sees a half-written file. Idempotent per partition."""
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / "events.jsonl"
    tmp_path = target_dir / ".events.jsonl.tmp"

    count = 0
    with tmp_path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(event.model_dump_json())
            fh.write("\n")
            count += 1
    os.replace(tmp_path, final_path)
    return count
