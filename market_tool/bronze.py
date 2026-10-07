from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4


def write_bronze_batch(
    records: Sequence[Mapping[str, Any]],
    bronze_dir: Path,
    *,
    source_type: str,
    source_name: str,
    source_reference: str = "",
    ingested_at: datetime | None = None,
) -> Path:
    """Persist an immutable JSONL batch of unnormalized source records."""
    if not records:
        raise ValueError("A Bronze batch must contain at least one record.")
    if any(not isinstance(record, Mapping) for record in records):
        raise ValueError("Every Bronze record must be a mapping.")

    timestamp = ingested_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("ingested_at must include a timezone.")
    timestamp = timestamp.astimezone(timezone.utc)
    timestamp_text = timestamp.isoformat(timespec="seconds")
    batch_id = str(uuid4())
    partition = timestamp.date().isoformat()
    batch_dir = Path(bronze_dir) / "properties" / f"ingestion_date={partition}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    output_path = batch_dir / f"{batch_id}.jsonl"

    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{batch_id}.",
            suffix=".tmp",
            dir=batch_dir,
            delete=False,
        ) as temporary_file:
            temp_path = Path(temporary_file.name)
            for row_number, record in enumerate(records, start=1):
                row = {
                    "batch_id": batch_id,
                    "row_number": row_number,
                    "ingested_at": timestamp_text,
                    "source_type": source_type,
                    "source_name": source_name,
                    "source_reference": source_reference,
                    "raw_record": dict(record),
                }
                temporary_file.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        temp_path.replace(output_path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    return output_path