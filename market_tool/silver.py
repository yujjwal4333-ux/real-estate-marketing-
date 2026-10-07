from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .ingest import PROPERTY_COLUMNS, ImportValidationError, normalize_record


LISTING_DATE_ALIASES = ("listing_date", "list_date", "date_listed", "listed_at")
SALE_DATE_ALIASES = ("sale_date", "sold_date", "date_sold", "close_date", "closing_date")
SILVER_COLUMNS = ["batch_id", *PROPERTY_COLUMNS, "listing_date", "sale_date", "geography_key"]


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _first_date_value(raw: Mapping[str, Any], aliases: Sequence[str]) -> Any:
    normalized = {_key(key).replace("_", ""): value for key, value in raw.items()}
    for alias in aliases:
        value = normalized.get(_key(alias).replace("_", ""))
        if value is not None and str(value).strip():
            return value
    return None


def _normalize_date(value: Any, field: str) -> str:
    if value is None or not str(value).strip():
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        for date_format in ("%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, date_format).date().isoformat()
            except ValueError:
                continue
    raise ImportValidationError(f"{field.replace('_', ' ').title()} must be a valid date.")


def _geography_key(record: Mapping[str, Any]) -> str:
    state = " ".join(str(record.get("state", "")).split()).casefold()
    postal_code = re.sub(r"[^a-z0-9]", "", str(record.get("postal_code", "")).casefold())
    if re.fullmatch(r"\d{9}", postal_code):
        postal_code = postal_code[:5]
    if postal_code:
        return f"postal:{state}:{postal_code}" if state else f"postal:{postal_code}"

    city = " ".join(str(record.get("city", "")).split()).casefold()
    neighborhood = " ".join(str(record.get("neighborhood", "")).split()).casefold()
    if city and state:
        return f"city:{city}|state:{state}"
    if neighborhood and state:
        return f"neighborhood:{neighborhood}|state:{state}"
    return ""


def normalize_bronze_record(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one Bronze envelope and return its canonical Silver row."""
    raw = envelope.get("raw_record")
    if not isinstance(raw, Mapping):
        raise ImportValidationError("Bronze row must contain a raw_record object.")

    source_type = str(envelope.get("source_type", ""))
    source_name = str(envelope.get("source_name", ""))
    if not source_type.strip() or not source_name.strip():
        raise ImportValidationError("Bronze row must include source type and source name.")

    record = normalize_record(
        dict(raw),
        source_type=source_type,
        source_name=source_name,
        source_reference=str(envelope.get("source_reference", "")),
    )
    record["listing_date"] = _normalize_date(
        _first_date_value(raw, LISTING_DATE_ALIASES), "listing_date"
    )
    record["sale_date"] = _normalize_date(
        _first_date_value(raw, SALE_DATE_ALIASES), "sale_date"
    )
    record["geography_key"] = _geography_key(record)

    ingested_at = envelope.get("ingested_at")
    if ingested_at:
        try:
            timestamp = datetime.fromisoformat(str(ingested_at).replace("Z", "+00:00"))
        except ValueError as error:
            raise ImportValidationError("Bronze ingestion timestamp must be ISO formatted.") from error
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ImportValidationError("Bronze ingestion timestamp must include a timezone.")
        record["captured_at"] = timestamp.astimezone(timezone.utc).isoformat(timespec="seconds")

    return record


def summarize_quality(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Summarize date, geography, sale-price, and duplicate coverage."""
    fingerprints = [
        str(record.get("record_fingerprint", ""))
        for record in records
        if record.get("record_fingerprint")
    ]
    fingerprint_counts = Counter(fingerprints)
    return {
        "total_records": len(records),
        "with_listing_date": sum(bool(record.get("listing_date")) for record in records),
        "with_sale_date": sum(bool(record.get("sale_date")) for record in records),
        "missing_geography": sum(not record.get("geography_key") for record in records),
        "closed_without_sale_price": sum(
            str(record.get("listing_status", "")).strip().casefold() in {"sold", "closed"}
            and record.get("sale_price") in (None, "")
            for record in records
        ),
        "duplicate_records": sum(count - 1 for count in fingerprint_counts.values() if count > 1),
    }


def transform_bronze_batch(bronze_path: Path, silver_dir: Path) -> tuple[Path, dict[str, int]]:
    """Transform one Bronze JSONL batch into an immutable canonical Silver CSV."""
    bronze_path = Path(bronze_path)
    envelopes = []
    try:
        with bronze_path.open(encoding="utf-8") as source_file:
            for row_number, line in enumerate(source_file, start=1):
                try:
                    envelope = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ImportValidationError(f"Bronze row {row_number} is not valid JSON.") from error
                if not isinstance(envelope, Mapping):
                    raise ImportValidationError(f"Bronze row {row_number} must be an object.")
                envelopes.append(envelope)
    except OSError:
        raise

    if not envelopes:
        raise ImportValidationError("Bronze batch contains no records.")

    batch_ids = {str(envelope.get("batch_id", "")) for envelope in envelopes}
    if len(batch_ids) != 1 or not next(iter(batch_ids)).strip():
        raise ImportValidationError("Bronze batch must have one consistent batch ID.")
    batch_id = next(iter(batch_ids))

    records = []
    for row_number, envelope in enumerate(envelopes, start=1):
        try:
            record = normalize_bronze_record(envelope)
        except ImportValidationError as error:
            raise ImportValidationError(f"Bronze row {row_number}: {error}") from error
        records.append({"batch_id": batch_id, **record})

    quality = summarize_quality(records)
    partition_date = records[0]["captured_at"][:10]
    batch_dir = Path(silver_dir) / "properties" / f"ingestion_date={partition_date}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    output_path = batch_dir / f"{batch_id}.csv"
    if output_path.exists():
        raise FileExistsError(f"Silver batch already exists: {output_path}")

    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{batch_id}.",
            suffix=".tmp",
            dir=batch_dir,
            delete=False,
        ) as temporary_file:
            temp_path = Path(temporary_file.name)
            writer = csv.DictWriter(temporary_file, fieldnames=SILVER_COLUMNS)
            writer.writeheader()
            writer.writerows(records)
        temp_path.replace(output_path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise

    return output_path, quality