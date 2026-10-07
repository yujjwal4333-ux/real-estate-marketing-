from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from market_tool.bronze import write_bronze_batch


class BronzeTests(unittest.TestCase):
    def test_writes_raw_rows_with_batch_and_source_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_records = [
                {"Street Address": "10 Main St", "Asking Price": "250000"},
                {"Street Address": "12 Main St", "Asking Price": "275000"},
            ]

            output_path = write_bronze_batch(
                raw_records,
                Path(directory),
                source_type="csv",
                source_name="homes.csv",
                source_reference="local import",
                ingested_at=datetime(2026, 9, 30, 12, tzinfo=timezone.utc),
            )

            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(output_path.parent.name, "ingestion_date=2026-09-30")
            self.assertEqual([row["raw_record"] for row in rows], raw_records)
            self.assertEqual([row["row_number"] for row in rows], [1, 2])
            self.assertEqual({row["batch_id"] for row in rows}, {output_path.stem})
            self.assertEqual({row["source_type"] for row in rows}, {"csv"})
            self.assertEqual({row["source_name"] for row in rows}, {"homes.csv"})
            self.assertEqual({row["source_reference"] for row in rows}, {"local import"})

    def test_each_batch_gets_a_separate_file(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = {
                "source_type": "manual",
                "source_name": "Manual entry",
                "ingested_at": datetime(2026, 9, 30, tzinfo=timezone.utc),
            }
            first = write_bronze_batch([{"address": "10 Main St"}], Path(directory), **arguments)
            second = write_bronze_batch([{"address": "12 Main St"}], Path(directory), **arguments)

            self.assertNotEqual(first, second)
            self.assertEqual(len(list(first.parent.glob("*.jsonl"))), 2)

    def test_rejects_empty_or_non_mapping_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = {
                "bronze_dir": Path(directory),
                "source_type": "csv",
                "source_name": "homes.csv",
            }
            with self.assertRaisesRegex(ValueError, "at least one record"):
                write_bronze_batch([], **arguments)
            with self.assertRaisesRegex(ValueError, "must be a mapping"):
                write_bronze_batch(["not a record"], **arguments)

    def test_rejects_naive_ingestion_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "must include a timezone"):
                write_bronze_batch(
                    [{"address": "10 Main St"}],
                    Path(directory),
                    source_type="manual",
                    source_name="Manual entry",
                    ingested_at=datetime(2026, 9, 30),
                )

    def test_failed_write_cleans_up_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            cyclic_record = {}
            cyclic_record["self"] = cyclic_record

            with self.assertRaisesRegex(ValueError, "Circular reference"):
                write_bronze_batch(
                    [cyclic_record],
                    Path(directory),
                    source_type="manual",
                    source_name="Manual entry",
                )

            batch_dir = Path(directory) / "properties"
            self.assertEqual(list(batch_dir.rglob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()