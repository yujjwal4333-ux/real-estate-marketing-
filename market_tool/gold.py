from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .ingest import load_external_records


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _coerce_numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def _pick_column(frame: pd.DataFrame, *names: str) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def _area_sqft(frame: pd.DataFrame, *, preferred: str | None = None) -> pd.Series:
    column = _pick_column(frame, *(preferred,) if preferred else ())
    if column is None:
        column = _pick_column(frame, "gr_liv_area", "living_area_sqft", "total_bsmt_sf", "lot_area_sqft")
    if column is None:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _price_value(frame: pd.DataFrame, *, preferred: str | None = None) -> pd.Series:
    column = _pick_column(frame, *(preferred,) if preferred else ())
    if column is None:
        column = _pick_column(frame, "sale_price", "list_price", "price", "asking_price")
    if column is None:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _neighborhood_value(frame: pd.DataFrame) -> pd.Series:
    column = _pick_column(frame, "neighborhood", "neighbourhood", "area")
    if column is None:
        return pd.Series("global", index=frame.index, dtype=object)
    return frame[column].fillna("global")


def summarize_market_trends(frame: pd.DataFrame) -> dict[str, object]:
    """Return quarterly median sale prices and price-per-square-foot for the selected market data."""
    if frame is None or frame.empty:
        return {
            "period_count": 0,
            "periods": [],
            "chart_labels": [],
            "chart_values": [],
            "notes": ["No sale records available."],
        }

    sales = frame.copy()
    sales["sale_price"] = _price_value(sales, preferred="sale_price")
    sales["living_area_sqft"] = _area_sqft(sales)
    sales["mo_sold"] = pd.to_numeric(sales.get("mo_sold", pd.Series(index=sales.index, dtype=float)), errors="coerce")
    sales["yr_sold"] = pd.to_numeric(sales.get("yr_sold", pd.Series(index=sales.index, dtype=float)), errors="coerce")
    sales = sales[(sales["sale_price"].notna()) & (sales["yr_sold"].notna()) & (sales["mo_sold"].notna())].copy()
    if sales.empty:
        return {
            "period_count": 0,
            "periods": [],
            "chart_labels": [],
            "chart_values": [],
            "notes": ["No sale records available."],
        }

    sales["year_month"] = (
        sales["yr_sold"].astype(int).astype(str)
        + "-"
        + sales["mo_sold"].fillna(1).astype(int).astype(str).str.zfill(2)
        + "-01"
    )
    sales["quarter"] = pd.PeriodIndex(pd.to_datetime(sales["year_month"]), freq="Q")
    sales["price_per_sqft"] = np.where(
        sales["living_area_sqft"].fillna(0).gt(0),
        sales["sale_price"] / sales["living_area_sqft"],
        np.nan,
    )

    quarterly = sales.groupby("quarter").agg(
        median_price=("sale_price", "median"),
        median_price_per_sqft=("price_per_sqft", "median"),
        transaction_count=("sale_price", "size"),
    ).sort_index()

    summary: dict[str, object] = {
        "period_count": int(len(quarterly)),
        "periods": [],
        "chart_labels": [],
        "chart_values": [],
        "notes": [],
    }

    for period in quarterly.index:
        label = f"q{period.quarter}_{period.year}"
        summary["periods"].append(label)  # type: ignore[attr-defined]
        summary["chart_labels"].append(label)  # type: ignore[attr-defined]
        summary["chart_values"].append(float(quarterly.loc[period, "median_price"]))  # type: ignore[attr-defined]
        summary[f"median_price_{label}"] = float(quarterly.loc[period, "median_price"])  # type: ignore[index]
        summary[f"median_price_per_sqft_{label}"] = float(quarterly.loc[period, "median_price_per_sqft"])  # type: ignore[index]

    if summary["period_count"] <= 2:
        summary["notes"].append("Market signal is based on a limited observation window.")
    return summary


def forecast_market_prices(frame: pd.DataFrame) -> dict[str, object]:
    """Estimate next-quarter median sale price using the recent trend in observed quarters."""
    chart = summarize_market_trends(frame)
    periods = chart.get("periods", [])
    if not periods:
        return {
            "next_quarter_median_price": None,
            "baseline_label": "insufficient_data",
            "current_median_price": None,
            "chart_labels": [],
            "chart_values": [],
        }

    values = [float(chart[f"median_price_{label}"]) for label in periods]
    if len(values) < 2:
        next_value = float(values[-1]) if values else None
        baseline = "recent_level"
    else:
        x = np.arange(len(values))
        slope = np.polyfit(x, values, 1)[0]
        next_value = float(values[-1] + slope)
        baseline = "recent_trend"

    return {
        "next_quarter_median_price": next_value,
        "baseline_label": baseline,
        "current_median_price": float(values[-1]) if values else None,
        "chart_labels": chart.get("chart_labels", []),
        "chart_values": chart.get("chart_values", []),
    }


def identify_investment_opportunities(listings: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """Rank properties for sale using recent local comparable sales."""
    if listings is None or listings.empty:
        return pd.DataFrame(columns=["address", "neighborhood", "list_price", "price_per_sqft", "comp_median_price_per_sqft", "discount_pct", "score"])

    if market is None or market.empty:
        return pd.DataFrame(columns=["address", "neighborhood", "list_price", "price_per_sqft", "comp_median_price_per_sqft", "discount_pct", "score"])

    market_frame = market.copy()
    market_frame["sale_price"] = _price_value(market_frame, preferred="sale_price")
    market_frame["living_area_sqft"] = _area_sqft(market_frame)
    market_frame["neighborhood"] = _neighborhood_value(market_frame)
    market_frame["price_per_sqft"] = np.where(
        market_frame["living_area_sqft"].fillna(0).gt(0),
        market_frame["sale_price"] / market_frame["living_area_sqft"],
        np.nan,
    )

    listings_frame = listings.copy()
    listings_frame["list_price"] = _price_value(listings_frame, preferred="list_price")
    listings_frame["living_area_sqft"] = _area_sqft(listings_frame)
    listings_frame["neighborhood"] = _neighborhood_value(listings_frame)
    listings_frame["price_per_sqft"] = np.where(
        listings_frame["living_area_sqft"].fillna(0).gt(0),
        listings_frame["list_price"] / listings_frame["living_area_sqft"],
        np.nan,
    )

    rows: list[dict[str, object]] = []
    for _, listing in listings_frame.iterrows():
        if pd.isna(listing.get("list_price")) or pd.isna(listing.get("living_area_sqft")):
            continue
        neighborhood = str(listing.get("neighborhood", "") or listing.get("city", "") or "global").strip()
        if not neighborhood or neighborhood.lower() == "nan":
            neighborhood = "global"
        comparable_prices = market_frame.loc[
            market_frame["neighborhood"].fillna("global").str.casefold() == neighborhood.casefold(),
            "price_per_sqft",
        ] if neighborhood else market_frame["price_per_sqft"]
        if comparable_prices.empty:
            comparable_prices = market_frame["price_per_sqft"].dropna()
        comp_median = float(comparable_prices.median()) if not comparable_prices.empty else float(listing["price_per_sqft"])
        discount_pct = ((comp_median - float(listing["price_per_sqft"])) / comp_median * 100) if comp_median else 0.0
        score = float(discount_pct)
        rows.append(
            {
                "address": listing.get("address", "Unknown address"),
                "neighborhood": neighborhood or "global",
                "list_price": float(listing["list_price"]),
                "price_per_sqft": float(listing["price_per_sqft"]),
                "comp_median_price_per_sqft": comp_median,
                "discount_pct": discount_pct,
                "score": score,
            }
        )

    result = pd.DataFrame(rows, columns=["address", "neighborhood", "list_price", "price_per_sqft", "comp_median_price_per_sqft", "discount_pct", "score"])
    if result.empty:
        return result
    result = result.sort_values(["discount_pct", "score"], ascending=[False, False]).reset_index(drop=True)
    return result


def build_dashboard_summary(data_dir: Path | str | None = None) -> dict[str, object]:
    data_root = Path(data_dir) if data_dir is not None else PROJECT_ROOT / "dataset"
    ames_path = data_root / "cleaned_train.csv"
    external_path = data_root / "external_properties.csv"

    ames = pd.read_csv(ames_path) if ames_path.exists() else pd.DataFrame()
    external = load_external_records(external_path) if external_path.exists() else pd.DataFrame()

    market_summary = summarize_market_trends(ames)
    forecast = forecast_market_prices(ames)
    opportunities = identify_investment_opportunities(external, ames)

    chart = go.Figure(go.Line(
        x=market_summary.get("chart_labels", []),
        y=market_summary.get("chart_values", []),
        mode="lines+markers",
        line={"color": "#176b53", "width": 3},
        marker={"size": 7, "color": "#d47b4e"},
    ))
    chart.update_layout(
        template="plotly_white",
        height=260,
        margin={"l": 18, "r": 18, "t": 8, "b": 38},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"title": "Quarter"},
        yaxis={"title": "Median sale price"},
    )

    return {
        "market_summary": market_summary,
        "forecast": forecast,
        "opportunities": opportunities,
        "chart_html": chart.to_html(full_html=False, include_plotlyjs="cdn"),
        "data_note": "Ames data is historical and suitable for prototype market analysis. Live market signals require dated local sales data.",
        "has_market_data": bool(not ames.empty),
        "has_opportunity_data": bool(not opportunities.empty),
    }
