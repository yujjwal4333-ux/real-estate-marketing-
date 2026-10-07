from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from market_tool import create_app
from market_tool.ingest import ImportValidationError, normalize_record, records_from_upload


class IngestTests(unittest.TestCase):
    def test_workspace_combines_intake_and_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({"TESTING": True, "DATA_DIR": Path(directory)})
            client = app.test_client()

            response = client.get("/")
            dashboard_redirect = client.get("/dashboard")

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Data intake", response.data)
            self.assertIn(b"Market signals", response.data)
            self.assertIn(b"Investment opportunities", response.data)
            self.assertEqual(dashboard_redirect.status_code, 302)
            self.assertEqual(dashboard_redirect.headers["Location"], "/#analysis")

    def test_csv_aliases_and_raw_source_are_preserved(self):
        content = (
            b"Street Address,City,State,Asking Price,Beds,Square Feet\n"
            b"10 Main St,Ames,IA,250000,3,1600\n"
        )
        records = records_from_upload("homes.csv", content)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["address"], "10 Main St")
        self.assertEqual(records[0]["list_price"], 250000)
        self.assertEqual(json.loads(records[0]["raw_data_json"])["Beds"], "3")

    def test_invalid_record_is_rejected(self):
        with self.assertRaisesRegex(ImportValidationError, "list price or a completed sale price"):
            normalize_record(
                {"address": "10 Main St"},
                source_type="manual",
                source_name="Manual entry",
            )

    def test_manual_entry_and_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({"TESTING": True, "DATA_DIR": Path(directory)})
            client = app.test_client()
            form = {
                "source_type": "manual",
                "address": "14 Pine Road",
                "city": "Ames",
                "list_price": "310000",
            }
            first = client.post("/api/import", data=form)
            second = client.post("/api/import", data=form)

            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json["added"], 1)
            self.assertEqual(second.json["duplicates"], 1)
            saved = pd.read_csv(Path(directory) / "external_properties.csv")
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved.loc[0, "source_type"], "manual")

    def test_json_and_html_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({"TESTING": True, "DATA_DIR": Path(directory)})
            client = app.test_client()
            json_bytes = json.dumps({"properties": [{
                "street_address": "20 Oak Street",
                "city": "Ames",
                "asking_price": 275000,
            }]}).encode()
            json_response = client.post(
                "/api/import",
                data={"file": (io.BytesIO(json_bytes), "homes.json")},
                content_type="multipart/form-data",
            )
            html_response = client.post("/api/import", data={
                "source_type": "html",
                "html": '<h1>30 Cedar Lane</h1><span itemprop="price" content="290000"></span>',
            })

            self.assertEqual(json_response.status_code, 200)
            self.assertEqual(html_response.status_code, 200)
            saved = pd.read_csv(Path(directory) / "external_properties.csv")
            self.assertEqual(set(saved["source_type"]), {"json", "html"})

    def test_import_creates_bronze_and_silver_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({"TESTING": True, "DATA_DIR": Path(directory)})
            client = app.test_client()

            response = client.post(
                "/api/import",
                data={
                    "source_type": "manual",
                    "address": "44 Willow Drive",
                    "city": "Ames",
                    "state": "IA",
                    "postal_code": "50010",
                    "listing_status": "Sold",
                    "sale_price": "330000",
                    "bedrooms": "3",
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertTrue((Path(directory) / "bronze" / "properties").exists())
            self.assertTrue((Path(directory) / "silver" / "properties").exists())
            bronze_files = list((Path(directory) / "bronze" / "properties").rglob("*.jsonl"))
            silver_files = list((Path(directory) / "silver" / "properties").rglob("*.csv"))
            self.assertTrue(bronze_files)
            self.assertTrue(silver_files)
            saved = pd.read_csv(Path(directory) / "external_properties.csv")
            self.assertEqual(saved.loc[0, "address"], "44 Willow Drive")


if __name__ == "__main__":
    unittest.main()