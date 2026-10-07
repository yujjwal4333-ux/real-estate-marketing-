from __future__ import annotations

import pandas as pd

from market_tool.gold import forecast_market_prices, identify_investment_opportunities, summarize_market_trends


def test_summarize_market_trends_aggregates_by_quarter():
    frame = pd.DataFrame([
        {"sale_price": 200000, "living_area_sqft": 1000, "yr_sold": 2024, "mo_sold": 1, "neighborhood": "North"},
        {"sale_price": 300000, "living_area_sqft": 1500, "yr_sold": 2024, "mo_sold": 2, "neighborhood": "North"},
        {"sale_price": 400000, "living_area_sqft": 2000, "yr_sold": 2024, "mo_sold": 4, "neighborhood": "North"},
    ])

    summary = summarize_market_trends(frame)

    assert summary["period_count"] == 2
    assert summary["median_price_q1_2024"] == 250000
    assert summary["median_price_per_sqft_q1_2024"] == 200


def test_forecast_market_prices_uses_recent_trend():
    frame = pd.DataFrame([
        {"sale_price": 200000, "yr_sold": 2023, "mo_sold": 1},
        {"sale_price": 250000, "yr_sold": 2023, "mo_sold": 4},
        {"sale_price": 310000, "yr_sold": 2024, "mo_sold": 2},
    ])

    forecast = forecast_market_prices(frame)

    assert forecast["next_quarter_median_price"] > 300000
    assert forecast["baseline_label"] == "recent_trend"


def test_identify_investment_opportunities_ranks_deals_with_discount():
    market = pd.DataFrame([
        {"neighborhood": "North", "sale_price": 300000, "living_area_sqft": 1500, "listing_status": "Sold"},
        {"neighborhood": "North", "sale_price": 320000, "living_area_sqft": 1500, "listing_status": "Sold"},
        {"neighborhood": "North", "sale_price": 340000, "living_area_sqft": 1500, "listing_status": "Sold"},
    ])
    listings = pd.DataFrame([
        {"address": "14 Pine Rd", "neighborhood": "North", "list_price": 250000, "living_area_sqft": 1500, "listing_status": "For sale"},
        {"address": "25 Oak Ave", "neighborhood": "North", "list_price": 400000, "living_area_sqft": 1500, "listing_status": "For sale"},
    ])

    opportunities = identify_investment_opportunities(listings, market)

    assert list(opportunities["address"]) == ["14 Pine Rd", "25 Oak Ave"]
    assert opportunities.iloc[0]["discount_pct"] > opportunities.iloc[1]["discount_pct"]
