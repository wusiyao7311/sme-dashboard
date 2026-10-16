from __future__ import annotations

import datetime
from typing import Dict, Tuple

import pandas as pd


def compute_kpis(orders: pd.DataFrame, start: datetime.date, end: datetime.date) -> dict:
    """Compute key performance indicators for completed orders within [start, end]."""
    completed = orders[orders["status"] == "completed"].copy()
    if completed.empty:
        return {
            "revenue": 0.0,
            "order_count": 0,
            "avg_order_value": 0.0,
            "new_customers": 0,
            "returning_customers": 0,
        }

    # Determine first completed order date per customer across all time
    first_order_dates = completed.groupby("customer_id")["order_date"].min()

    # Filter to range inclusive
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    in_range = completed[
        (completed["order_date"] >= start_ts) & (completed["order_date"] <= end_ts)
    ]

    revenue = float(in_range["total"].sum())
    order_count = int(len(in_range))
    avg_order_value = revenue / order_count if order_count > 0 else 0.0

    # New customers: first completed order ever is within [start, end]
    new_customers = int(
        first_order_dates[
            (first_order_dates >= start_ts) & (first_order_dates <= end_ts)
        ].shape[0]
    )

    # Returning customers: have an order in range, but first completed order was before start
    customers_in_range = set(in_range["customer_id"].unique())
    returning_customers = 0
    for cust in customers_in_range:
        first = first_order_dates.loc[cust]
        if first < start_ts:
            returning_customers += 1

    return {
        "revenue": revenue,
        "order_count": order_count,
        "avg_order_value": avg_order_value,
        "new_customers": new_customers,
        "returning_customers": returning_customers,
    }


def previous_period(start: datetime.date, end: datetime.date) -> Tuple[datetime.date, datetime.date]:
    """Return the equally long range directly before start."""
    duration = end - start
    prev_end = start - datetime.timedelta(days=1)
    prev_start = prev_end - duration
    return prev_start, prev_end


def revenue_over_time(
    orders: pd.DataFrame,
    start: datetime.date,
    end: datetime.date,
    freq: str,
) -> pd.DataFrame:
    """Return revenue per period within [start, end] for completed orders."""
    if freq not in ("D", "W", "M"):
        raise ValueError("freq must be 'D', 'W', or 'M'")

    completed = orders[orders["status"] == "completed"].copy()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    # Build full period index
    if freq == "D":
        period_index = pd.date_range(start=start_ts, end=end_ts, freq="D")
    elif freq == "W":
        # Weeks start Monday; generate all Mondays in range
        # Start from the Monday on or before start
        start_monday = start_ts - pd.Timedelta(days=start_ts.dayofweek)
        period_index = pd.date_range(start=start_monday, end=end_ts, freq="W-MON")
        # Filter to periods that overlap [start, end]
        period_index = period_index[
            (period_index <= end_ts) & (period_index + pd.Timedelta(days=6) >= start_ts)
        ]
    else:  # freq == "M"
        # First of each month in range
        period_index = pd.date_range(start=start_ts.replace(day=1), end=end_ts, freq="MS")

    # Filter completed orders to range
    in_range = completed[
        (completed["order_date"] >= start_ts) & (completed["order_date"] <= end_ts)
    ]

    if in_range.empty:
        return pd.DataFrame({"period": period_index, "revenue": 0.0})

    # Assign each order to its period
    if freq == "D":
        in_range = in_range.copy()
        in_range["period"] = in_range["order_date"].dt.normalize()
    elif freq == "W":
        in_range = in_range.copy()
        # Week start Monday
        in_range["period"] = in_range["order_date"].dt.to_period("W").dt.start_time
    else:
        in_range = in_range.copy()
        in_range["period"] = in_range["order_date"].dt.to_period("M").dt.start_time

    # Aggregate revenue by period
    revenue_by_period = in_range.groupby("period")["total"].sum()

    # Reindex to full period index, fill missing with 0.0
    result = pd.DataFrame({"period": period_index})
    result["revenue"] = result["period"].map(revenue_by_period).fillna(0.0).astype(float)

    return result


def top_products(
    orders: pd.DataFrame,
    order_items: pd.DataFrame,
    products: pd.DataFrame,
    start: datetime.date,
    end: datetime.date,
    n: int = 5,
) -> pd.DataFrame:
    """Return top n products by revenue from completed orders in [start, end]."""
    completed = orders[orders["status"] == "completed"].copy()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    in_range = completed[
        (completed["order_date"] >= start_ts) & (completed["order_date"] <= end_ts)
    ]

    if in_range.empty:
        return pd.DataFrame(columns=["name", "units", "revenue"])

    # Join order_items with completed orders in range
    merged = order_items.merge(
        in_range[["id"]], left_on="order_id", right_on="id", how="inner"
    )

    if merged.empty:
        return pd.DataFrame(columns=["name", "units", "revenue"])

    # Join with products for name
    merged = merged.merge(products[["id", "name"]], left_on="product_id", right_on="id", how="inner")

    if merged.empty:
        return pd.DataFrame(columns=["name", "units", "revenue"])

    # Aggregate
    merged["line_revenue"] = merged["qty"] * merged["unit_price"]
    agg = merged.groupby("name").agg(
        units=("qty", "sum"),
        revenue=("line_revenue", "sum"),
    ).reset_index()

    agg = agg.sort_values("revenue", ascending=False).head(n)
    return agg[["name", "units", "revenue"]]


def top_customers(
    orders: pd.DataFrame,
    customers: pd.DataFrame,
    start: datetime.date,
    end: datetime.date,
    n: int = 5,
) -> pd.DataFrame:
    """Return top n customers by revenue from completed orders in [start, end]."""
    completed = orders[orders["status"] == "completed"].copy()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    in_range = completed[
        (completed["order_date"] >= start_ts) & (completed["order_date"] <= end_ts)
    ]

    if in_range.empty:
        return pd.DataFrame(columns=["name", "orders", "revenue"])

    # Aggregate per customer
    agg = in_range.groupby("customer_id").agg(
        orders=("id", "count"),
        revenue=("total", "sum"),
    ).reset_index()

    # Join with customers for name
    agg = agg.merge(customers[["id", "name"]], left_on="customer_id", right_on="id", how="inner")

    if agg.empty:
        return pd.DataFrame(columns=["name", "orders", "revenue"])

    agg = agg.sort_values("revenue", ascending=False).head(n)
    return agg[["name", "orders", "revenue"]]
