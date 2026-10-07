from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from flask import Flask, jsonify, redirect, render_template, request

from .bronze import write_bronze_batch
from .gold import build_dashboard_summary
from .ingest import (
    PROPERTY_COLUMNS,
    ImportValidationError,
    load_external_records,
    normalize_record,
    parse_listing_html,
    parse_listing_html_raw,
    raw_records_from_upload,
    records_from_upload,
    save_records,
)
from .silver import transform_bronze_batch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "local-development-key"),
        DATA_DIR=Path(os.environ.get("REAL_ESTATE_DATA_DIR", PROJECT_ROOT / "dataset")),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    output_path = lambda: Path(app.config["DATA_DIR"]) / "external_properties.csv"

    def persist_medallion(raw_records: list[dict], *, source_type: str, source_name: str, source_reference: str = "") -> tuple[Path, Path, dict[str, int]]:
        bronze_dir = Path(app.config["DATA_DIR"]) / "bronze"
        silver_dir = Path(app.config["DATA_DIR"]) / "silver"
        bronze_path = write_bronze_batch(
            raw_records,
            bronze_dir,
            source_type=source_type,
            source_name=source_name,
            source_reference=source_reference,
        )
        silver_path, quality = transform_bronze_batch(bronze_path, silver_dir)
        return bronze_path, silver_path, quality

    @app.get("/")
    def index():
        records = load_external_records(output_path())
        summary = build_dashboard_summary(Path(app.config["DATA_DIR"]))
        source_counts = records["source_type"].fillna("unknown").value_counts() if not records.empty else pd.Series(dtype=int)
        source_chart_html = ""
        if not source_counts.empty:
            chart = go.Figure(go.Bar(
                x=source_counts.index.tolist(),
                y=source_counts.values.tolist(),
                marker_color=["#176b53", "#d47b4e", "#527b91", "#a59b64"],
                hovertemplate="%{x}: %{y} records<extra></extra>",
            ))
            chart.update_layout(
                template="plotly_white",
                height=220,
                margin={"l": 8, "r": 8, "t": 8, "b": 8},
                showlegend=False,
                yaxis={"title": "Records", "gridcolor": "#e8e7df", "rangemode": "tozero"},
                xaxis={"title": "Source type"},
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            source_chart_html = chart.to_html(full_html=False, include_plotlyjs="cdn")

        latest = records.sort_values("captured_at", ascending=False).head(20) if not records.empty else records
        rows = latest.where(pd.notna(latest), "").to_dict(orient="records")
        return render_template(
            "index.html",
            total_records=len(records),
            source_count=records["source_type"].nunique() if not records.empty else 0,
            source_chart_html=source_chart_html,
            rows=rows,
            columns=PROPERTY_COLUMNS,
            market_summary=summary["market_summary"],
            forecast=summary["forecast"],
            opportunities=summary["opportunities"].to_dict(orient="records"),
            market_chart_html=summary["chart_html"],
            data_note=summary["data_note"],
            has_market_data=summary["has_market_data"],
            has_opportunity_data=summary["has_opportunity_data"],
        )

    @app.get("/dashboard")
    def dashboard():
        return redirect("/#analysis")

    @app.post("/api/import")
    def import_records():
        try:
            source_type = request.form.get("source_type", "")
            source_name = ""
            source_reference = ""
            raw_records: list[dict] = []

            if "file" in request.files and request.files["file"].filename:
                upload = request.files["file"]
                content = upload.read()
                raw_records = raw_records_from_upload(upload.filename, content)
                source_name = upload.filename
                source_reference = ""
                records = [normalize_record(
                    raw,
                    source_type=Path(upload.filename).suffix.lower().lstrip("."),
                    source_name=upload.filename,
                    source_reference="",
                ) for raw in raw_records]
            elif source_type == "html":
                raw = parse_listing_html_raw(
                    request.form.get("html", ""),
                    request.form.get("source_reference", ""),
                )
                raw_records = [raw]
                source_name = "Pasted listing HTML"
                source_reference = raw.get("source_reference", "")
                records = [normalize_record(
                    raw,
                    source_type="html",
                    source_name="Pasted listing HTML",
                    source_reference=source_reference,
                )]
            elif source_type == "manual":
                raw = request.form.to_dict()
                raw.pop("source_type", None)
                raw_records = [raw]
                source_name = "Manual entry"
                source_reference = raw.get("source_reference", "")
                records = [normalize_record(
                    raw,
                    source_type="manual",
                    source_name="Manual entry",
                    source_reference=source_reference,
                )]
            else:
                raise ImportValidationError("Choose a CSV/JSON file, enter a property, or paste listing HTML.")

            persist_medallion(raw_records, source_type=source_type or (Path(source_name).suffix.lower().lstrip(".") if source_name else "manual"), source_name=source_name or "Manual entry", source_reference=source_reference)
            added, duplicates = save_records(records, output_path())
            return jsonify(
                success=True,
                added=added,
                duplicates=duplicates,
                total_submitted=len(records),
                message=f"Saved {added} record{'s' if added != 1 else ''}; skipped {duplicates} duplicate{'s' if duplicates != 1 else ''}.",
            )
        except ImportValidationError as error:
            return jsonify(success=False, error=str(error)), 400
        except OSError:
            app.logger.exception("Could not write external property records")
            return jsonify(success=False, error="Could not save the dataset. Check folder permissions and available disk space."), 500

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify(success=False, error="Upload exceeds the 10 MB limit."), 413

    return app