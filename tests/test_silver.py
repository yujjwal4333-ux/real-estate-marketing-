from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from market_tool.bronze import write_bronze_batch
from market_tool.ingest import ImportValidationError
from market_tool.silver import SILVER_COLUMNS, summarize_quality, transform_bronze_batch


class SilverTests(unittest.TestCase):
    def test_canonical_date_field_takes_precedence_over_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bronze_path = write_bronze_batch(
                [{
                    "address": "10 Main St",
                    "city": "Ames",
                    "state": "IA",
                    "list_price": "250000",
                    "listing_date": "2026-02-01",
                    "date_listed": "2026-02-03",
                }],
                root / "bronze",
                source_type="manual",
                source_name="Manual entry",
                ingested_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
            )
            silver_path, _ = transform_bronze_batch(bronze_path, root / "silver")
            with silver_path.open(encoding="utf-8", newline="") as silver_file:
                row = next(csv.DictReader(silver_file))
            self.assertEqual(row["listing_date"], "2026-02-01")

    def test_transforms_bronze_to_canonical_silver_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bronze_path = write_bronze_batch(
                [{
                    "Street Address": "10 Main St",
                    "City": "Ames",
                    "State": "IA",
                    "ZIP Code": "50010-1234",
                    "Status": "Sold",
                    "Sale Price": "250000",
                    "Date Sold": "03/15/2026",
                    "Date Listed": "2026-02-01",
                    "Square Feet": "1600",
                }],
                root / "bronze",
                source_type="csv",
                source_name="sales.csv",
                source_reference="county export",
                ingested_at=datetime(2026, 9, 30, 12, tzinfo=timezone.utc),
            )

            silver_path, quality = transform_bronze_batch(bronze_path, root / "silver")

            with silver_path.open(encoding="utf-8", newline="") as silver_file:
                reader = csv.DictReader(silver_file)
                row = next(reader)
                self.assertEqual(reader.fieldnames, SILVER_COLUMNS)
            self.assertEqual(row["sale_date"], "2026-03-15")
            self.assertEqual(row["listing_date"], "2026-02-01")
            self.assertEqual(row["geography_key"], "postal:ia:50010")
            self.assertEqual(float(row["sale_price"]), 250000)
            self.assertEqual(row["source_name"], "sales.csv")
            self.assertEqual(row["captured_at"], "2026-09-30T12:00:00+00:00")
            self.assertEqual(quality["total_records"], 1)
            self.assertEqual(quality["with_sale_date"], 1)
            self.assertEqual(quality["missing_geography"], 0)

    def test_invalid_date_rejects_entire_batch_without_silver_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bronze_path = write_bronze_batch(
                [{
                    "address": "10 Main St",
                    "city": "Ames",
                    "state": "IA",
                    "list_price": "250000",
                    "listing_date": "not a date",
                }],
                root / "bronze",
                source_type="manual",
                source_name="Manual entry",
                ingested_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
            )
            silver_dir = root / "silver"

            with self.assertRaisesRegex(ImportValidationError, "Listing Date must be a valid date"):
                transform_bronze_batch(bronze_path, silver_dir)

            self.assertFalse(silver_dir.exists())

    def test_quality_summary_counts_missing_fields_and_duplicates(self):
        duplicate = {
            "record_fingerprint": "same",
            "listing_date": "",
            "sale_date": "2026-03-15",
            "geography_key": "",
            "listing_status": "Sold",
            "sale_price": None,
        }

        quality = summarize_quality([duplicate, duplicate])

        self.assertEqual(quality, {
            "total_records": 2,
            "with_listing_date": 0,
            "with_sale_date": 2,
            "missing_geography": 2,
            "closed_without_sale_price": 2,
            "duplicate_records": 1,
        })


if __name__ == "__main__":
    unittest.main()