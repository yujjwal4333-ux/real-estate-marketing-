from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_HTML_CHARS = 1_000_000

PROPERTY_COLUMNS = [
    "record_id",
    "source_type",
    "source_name",
    "source_reference",
    "captured_at",
    "address",
    "city",
    "state",
    "postal_code",
    "neighborhood",
    "property_type",
    "listing_status",
    "list_price",
    "sale_price",
    "bedrooms",
    "bathrooms",
    "living_area_sqft",
    "lot_area_sqft",
    "year_built",
    "description",
    "raw_data_json",
    "record_fingerprint",
]

ALIASES = {
    "address": {"address", "street", "street_address", "property_address", "full_address"},
    "city": {"city", "town", "municipality"},
    "state": {"state", "state_code", "province"},
    "postal_code": {"zip", "zipcode", "zip_code", "postal", "postal_code"},
    "neighborhood": {"neighborhood", "subdivision", "district", "area"},
    "property_type": {"property_type", "type", "home_type", "building_type"},
    "listing_status": {"listing_status", "status", "sale_status"},
    "list_price": {"list_price", "asking_price", "price", "listing_price", "asking"},
    "sale_price": {"sale_price", "sold_price", "closed_price", "transaction_price"},
    "bedrooms": {"bedrooms", "beds", "bed", "bedroom_count", "number_of_bedrooms"},
    "bathrooms": {"bathrooms", "baths", "bath", "bathroom_count", "number_of_bathrooms_total"},
    "living_area_sqft": {
        "living_area_sqft", "living_area", "sqft", "square_feet", "square_footage",
        "interior_sqft", "gr_liv_area", "above_grade_living_area",
    },
    "lot_area_sqft": {"lot_area_sqft", "lot_area", "lot_size_sqft", "lot_sqft"},
    "year_built": {"year_built", "built_year", "year_constructed"},
    "description": {"description", "remarks", "summary", "property_description"},
    "source_reference": {"source_reference", "source_url", "listing_url", "url"},
}

NUMERIC_COLUMNS = {
    "list_price", "sale_price", "bedrooms", "bathrooms", "living_area_sqft",
    "lot_area_sqft", "year_built",
}


class ImportValidationError(ValueError):
    pass


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _first_value(row: dict[str, Any], field: str) -> Any:
    normalized = {_key(key).replace("_", ""): value for key, value in row.items()}
    candidates = [field, *ALIASES[field]]
    for candidate in candidates:
        value = normalized.get(_key(candidate).replace("_", ""))
        if value is not None and not pd.isna(value) and str(value).strip() != "":
            return value
    return None


def _number(value: Any, field: str) -> float | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    cleaned = re.sub(r"[$,\s]", "", str(value))
    try:
        result = float(cleaned)
    except ValueError as error:
        raise ImportValidationError(f"{field.replace('_', ' ').title()} must be numeric.") from error
    if not np.isfinite(result):
        raise ImportValidationError(f"{field.replace('_', ' ').title()} must be a finite number.")
    return int(result) if field == "year_built" and result.is_integer() else result


def normalize_record(
    raw: dict[str, Any],
    *,
    source_type: str,
    source_name: str,
    source_reference: str = "",
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ImportValidationError("Each property record must be an object with named fields.")

    record: dict[str, Any] = {
        "record_id": str(uuid4()),
        "source_type": source_type,
        "source_name": Path(source_name).name[:200],
        "source_reference": str(_first_value(raw, "source_reference") or source_reference).strip()[:1000],
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    for field in PROPERTY_COLUMNS[5:-2]:
        value = _first_value(raw, field)
        if field in NUMERIC_COLUMNS:
            record[field] = _number(value, field)
        else:
            record[field] = str(value).strip()[:4000] if value is not None else ""

    if not any(record[field] for field in ("address", "postal_code", "neighborhood")):
        raise ImportValidationError("Provide at least an address, postal code, or neighborhood.")
    if record["list_price"] is None and record["sale_price"] is None:
        raise ImportValidationError("Provide a list price or a completed sale price.")
    for field in ("list_price", "sale_price", "living_area_sqft", "lot_area_sqft"):
        if record[field] is not None and record[field] <= 0:
            raise ImportValidationError(f"{field.replace('_', ' ').title()} must be greater than zero.")
    for field in ("bedrooms", "bathrooms"):
        if record[field] is not None and not 0 <= record[field] <= 100:
            raise ImportValidationError(f"{field.title()} must be between 0 and 100.")
    if record["year_built"] is not None and not 1600 <= record["year_built"] <= datetime.now().year + 2:
        raise ImportValidationError("Year built is outside the supported range.")

    record["raw_data_json"] = json.dumps(raw, ensure_ascii=False, default=str)
    fingerprint_fields = (
        record["address"], record["city"], record["state"], record["postal_code"],
        record["neighborhood"], record["property_type"], record["listing_status"],
        record["list_price"], record["sale_price"], record["bedrooms"], record["bathrooms"],
        record["living_area_sqft"], record["year_built"],
    )
    fingerprint_text = "|".join(str(value).strip().casefold() for value in fingerprint_fields)
    record["record_fingerprint"] = hashlib.sha256(fingerprint_text.encode("utf-8")).hexdigest()
    return record


def raw_records_from_upload(filename: str, content: bytes) -> list[dict[str, Any]]:
    if len(content) > MAX_UPLOAD_BYTES:
        raise ImportValidationError("Upload must be 10 MB or smaller.")
    extension = Path(filename).suffix.lower()
    if extension == ".csv":
        try:
            frame = pd.read_csv(BytesIO(content), dtype=object)
        except (UnicodeDecodeError, pd.errors.ParserError) as error:
            raise ImportValidationError(f"Could not read CSV: {error}") from error
        raw_records = frame.replace({np.nan: None}).to_dict(orient="records")
    elif extension == ".json":
        try:
            parsed = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ImportValidationError(f"Could not read JSON: {error}") from error
        if isinstance(parsed, dict) and isinstance(parsed.get("properties"), list):
            raw_records = parsed["properties"]
        elif isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
            raw_records = parsed["data"]
        else:
            raw_records = parsed if isinstance(parsed, list) else [parsed]
    else:
        raise ImportValidationError("Choose a .csv or .json file.")

    if not raw_records:
        raise ImportValidationError("The selected file contains no property records.")
    if len(raw_records) > 10_000:
        raise ImportValidationError("A single import is limited to 10,000 records.")
    return raw_records


def records_from_upload(filename: str, content: bytes) -> list[dict[str, Any]]:
    raw_records = raw_records_from_upload(filename, content)
    extension = Path(filename).suffix.lower()
    records = []
    errors = []
    for row_number, raw in enumerate(raw_records, start=2 if extension == ".csv" else 1):
        try:
            records.append(normalize_record(raw, source_type=extension[1:], source_name=filename))
        except ImportValidationError as error:
            errors.append(f"Row {row_number}: {error}")
            if len(errors) == 5:
                break
    if errors:
        raise ImportValidationError("Import rejected; fix these rows and retry. " + " ".join(errors))
    return records


def parse_listing_html_raw(html: str, source_reference: str = "") -> dict[str, Any]:
    if not isinstance(html, str) or not html.strip():
        raise ImportValidationError("Paste listing-page HTML to parse.")
    if len(html) > MAX_HTML_CHARS:
        raise ImportValidationError("Pasted HTML must be under 1 MB.")

    soup = BeautifulSoup(html, "html.parser")
    records: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            parsed = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = parsed if isinstance(parsed, list) else [parsed]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            graph = candidate.get("@graph", [])
            if isinstance(graph, list):
                candidates.extend(item for item in graph if isinstance(item, dict))
            records.append(candidate)

    property_record: dict[str, Any] = {}
    for record in records:
        record_type = record.get("@type", [])
        types = record_type if isinstance(record_type, list) else [record_type]
        if not any("house" in str(item).lower() or "residence" in str(item).lower() or "product" in str(item).lower() for item in types):
            continue
        property_record = record
        break

    if property_record:
        address_data = property_record.get("address", {})
        address_data = address_data if isinstance(address_data, dict) else {"streetAddress": address_data}
        offers = property_record.get("offers", {})
        offer = offers[0] if isinstance(offers, list) and offers else offers
        offer = offer if isinstance(offer, dict) else {}
        floor_size = property_record.get("floorSize", {})
        if isinstance(floor_size, dict):
            floor_size = floor_size.get("value")
        raw = {
            "address": address_data.get("streetAddress", ""),
            "city": address_data.get("addressLocality", ""),
            "state": address_data.get("addressRegion", ""),
            "postal_code": address_data.get("postalCode", ""),
            "property_type": property_record.get("@type", ""),
            "listing_status": offer.get("availability", ""),
            "list_price": offer.get("price", ""),
            "bedrooms": property_record.get("numberOfBedrooms", ""),
            "bathrooms": property_record.get("numberOfBathroomsTotal", ""),
            "living_area_sqft": floor_size or "",
            "description": property_record.get("description", ""),
            "name": property_record.get("name", ""),
        }
    else:
        heading = soup.find("h1") or soup.find("title")
        title = heading.get_text(" ", strip=True) if heading else ""
        address_tag = soup.find(attrs={"itemprop": "streetAddress"})
        price_tag = soup.find(attrs={"itemprop": "price"})
        price = ""
        if price_tag:
            price = price_tag.get("content") or price_tag.get_text(" ", strip=True)
        raw = {
            "address": address_tag.get_text(" ", strip=True) if address_tag else title,
            "list_price": price,
            "description": title,
        }

    if "source_reference" not in raw and source_reference:
        raw["source_reference"] = source_reference
    return raw


def parse_listing_html(html: str, source_reference: str = "") -> dict[str, Any]:
    raw = parse_listing_html_raw(html, source_reference)
    normalized = normalize_record(
        raw,
        source_type="html",
        source_name="Pasted listing HTML",
        source_reference=source_reference,
    )
    return normalized


def save_records(records: list[dict[str, Any]], output_path: Path) -> tuple[int, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    incoming = pd.DataFrame(records, columns=PROPERTY_COLUMNS)
    if output_path.exists() and output_path.stat().st_size:
        existing = pd.read_csv(output_path, dtype=object).reindex(columns=PROPERTY_COLUMNS)
        known = set(existing["record_fingerprint"].dropna().astype(str))
    else:
        existing = pd.DataFrame(columns=PROPERTY_COLUMNS)
        known = set()

    unique_rows = []
    seen = set(known)
    duplicates = 0
    for record in incoming.to_dict(orient="records"):
        fingerprint = str(record["record_fingerprint"])
        if fingerprint in seen:
            duplicates += 1
            continue
        seen.add(fingerprint)
        unique_rows.append(record)

    if unique_rows:
        combined = pd.concat([existing, pd.DataFrame(unique_rows)], ignore_index=True)
        temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        combined.to_csv(temp_path, index=False)
        temp_path.replace(output_path)
    return len(unique_rows), duplicates


def load_external_records(output_path: Path) -> pd.DataFrame:
    if not output_path.exists() or not output_path.stat().st_size:
        return pd.DataFrame(columns=PROPERTY_COLUMNS)
    return pd.read_csv(output_path).reindex(columns=PROPERTY_COLUMNS)