import datetime
import pytest
import pandas as pd
from app.kpis import (
    compute_kpis,
    previous_period,
    revenue_over_time,
    top_products,
    top_customers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orders(rows):
    """Build an orders DataFrame from a list of tuples.
    Each tuple: (id, customer_id, order_date, total, status)
    """
    df = pd.DataFrame(
        rows,
        columns=["id", "customer_id", "order_date", "total", "status"],
    )
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


# ---------------------------------------------------------------------------
# compute_kpis
# ---------------------------------------------------------------------------

def test_compute_kpis_basic_revenue_and_count():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-01", 100.0, "completed"),
        (2, "c2", "2024-01-05", 200.0, "completed"),
    ])
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 31)

    # Act
    result = compute_kpis(orders, start, end)

    # Assert
    assert result["revenue"] == 300.0
    assert result["order_count"] == 2
    assert result["avg_order_value"] == 150.0


def test_compute_kpis_new_vs_returning_customers():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2023-12-01", 50.0, "completed"),   # c1 first order before range
        (2, "c1", "2024-01-10", 100.0, "completed"),  # c1 returning in range
        (3, "c2", "2024-01-15", 75.0, "completed"),   # c2 new in range
    ])
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 31)

    # Act
    result = compute_kpis(orders, start, end)

    # Assert
    assert result["new_customers"] == 1
    assert result["returning_customers"] == 1


def test_compute_kpis_cancelled_orders_ignored():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-01", 100.0, "completed"),
        (2, "c1", "2024-01-02", 200.0, "cancelled"),
        (3, "c2", "2024-01-03", 300.0, "cancelled"),
    ])
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 31)

    # Act
    result = compute_kpis(orders, start, end)

    # Assert
    assert result["revenue"] == 100.0
    assert result["order_count"] == 1
    assert result["new_customers"] == 1
    assert result["returning_customers"] == 0


def test_compute_kpis_empty_range_gives_zeros():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-01", 100.0, "completed"),
    ])
    start = datetime.date(2024, 2, 1)
    end = datetime.date(2024, 2, 28)

    # Act
    result = compute_kpis(orders, start, end)

    # Assert
    assert result["revenue"] == 0.0
    assert result["order_count"] == 0
    assert result["avg_order_value"] == 0.0
    assert result["new_customers"] == 0
    assert result["returning_customers"] == 0


def test_compute_kpis_range_inclusive_both_ends():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-01", 10.0, "completed"),
        (2, "c1", "2024-01-10", 20.0, "completed"),
        (3, "c1", "2024-01-11", 30.0, "completed"),  # just outside end
    ])
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 10)

    # Act
    result = compute_kpis(orders, start, end)

    # Assert
    assert result["order_count"] == 2
    assert result["revenue"] == 30.0


# ---------------------------------------------------------------------------
# previous_period
# ---------------------------------------------------------------------------

def test_previous_period_march_to_february():
    # Arrange
    start = datetime.date(2024, 3, 1)
    end = datetime.date(2024, 3, 10)

    # Act
    prev_start, prev_end = previous_period(start, end)

    # Assert
    assert prev_start == datetime.date(2024, 2, 20)
    assert prev_end == datetime.date(2024, 2, 29)


# ---------------------------------------------------------------------------
# revenue_over_time
# ---------------------------------------------------------------------------

def test_revenue_over_time_daily():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-01", 100.0, "completed"),
        (2, "c1", "2024-01-02", 50.0, "completed"),
        (3, "c1", "2024-01-03", 25.0, "completed"),
    ])
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 3)

    # Act
    result = revenue_over_time(orders, start, end, freq="D")

    # Assert
    assert len(result) == 3
    assert result["revenue"].tolist() == [100.0, 50.0, 25.0]


def test_revenue_over_time_weekly_periods_are_mondays():
    # Arrange
    # 2024-01-01 is Monday; 2024-01-08 is next Monday
    orders = _make_orders([
        (1, "c1", "2024-01-01", 100.0, "completed"),
        (2, "c1", "2024-01-03", 50.0, "completed"),
        (3, "c1", "2024-01-08", 75.0, "completed"),
    ])
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 10)

    # Act
    result = revenue_over_time(orders, start, end, freq="W")

    # Assert
    assert len(result) == 2
    assert result["period"].iloc[0] == pd.Timestamp("2024-01-01")
    assert result["period"].iloc[1] == pd.Timestamp("2024-01-08")
    assert result["revenue"].iloc[0] == 150.0
    assert result["revenue"].iloc[1] == 75.0


def test_revenue_over_time_monthly_partial_first_month_appears():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-15", 100.0, "completed"),
        (2, "c1", "2024-02-10", 200.0, "completed"),
    ])
    start = datetime.date(2024, 1, 15)
    end = datetime.date(2024, 2, 28)

    # Act
    result = revenue_over_time(orders, start, end, freq="M")

    # Assert
    assert len(result) == 2
    assert result["period"].iloc[0] == pd.Timestamp("2024-01-01")
    assert result["period"].iloc[1] == pd.Timestamp("2024-02-01")
    assert result["revenue"].iloc[0] == 100.0
    assert result["revenue"].iloc[1] == 200.0


def test_revenue_over_time_zero_filled_gaps():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-01", 100.0, "completed"),
        (2, "c1", "2024-01-03", 50.0, "completed"),
    ])
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 5)

    # Act
    result = revenue_over_time(orders, start, end, freq="D")

    # Assert
    assert len(result) == 5
    assert result["revenue"].tolist() == [100.0, 0.0, 50.0, 0.0, 0.0]


def test_revenue_over_time_valueerror_on_bad_freq():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-01", 100.0, "completed"),
    ])
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 31)

    # Act / Assert
    with pytest.raises(ValueError, match="freq must be 'D', 'W', or 'M'"):
        revenue_over_time(orders, start, end, freq="Q")


# ---------------------------------------------------------------------------
# top_products
# ---------------------------------------------------------------------------

def test_top_products_basic():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-01", 100.0, "completed"),
        (2, "c2", "2024-01-02", 50.0, "completed"),
    ])
    order_items = pd.DataFrame([
        {"order_id": 1, "product_id": 10, "qty": 2, "unit_price": 30.0},
        {"order_id": 1, "product_id": 11, "qty": 1, "unit_price": 40.0},
        {"order_id": 2, "product_id": 10, "qty": 1, "unit_price": 30.0},
    ])
    products = pd.DataFrame([
        {"id": 10, "name": "Widget"},
        {"id": 11, "name": "Gadget"},
    ])
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 31)

    # Act
    result = top_products(orders, order_items, products, start, end, n=5)

    # Assert
    assert len(result) == 2
    # Widget: 2*30 + 1*30 = 90, Gadget: 1*40 = 40
    assert result.iloc[0]["name"] == "Widget"
    assert result.iloc[0]["units"] == 3
    assert result.iloc[0]["revenue"] == 90.0
    assert result.iloc[1]["name"] == "Gadget"
    assert result.iloc[1]["units"] == 1
    assert result.iloc[1]["revenue"] == 40.0


def test_top_products_empty_range():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-01", 100.0, "completed"),
    ])
    order_items = pd.DataFrame([
        {"order_id": 1, "product_id": 10, "qty": 1, "unit_price": 10.0},
    ])
    products = pd.DataFrame([
        {"id": 10, "name": "Widget"},
    ])
    start = datetime.date(2024, 2, 1)
    end = datetime.date(2024, 2, 28)

    # Act
    result = top_products(orders, order_items, products, start, end, n=5)

    # Assert
    assert result.empty
    assert list(result.columns) == ["name", "units", "revenue"]


# ---------------------------------------------------------------------------
# top_customers
# ---------------------------------------------------------------------------

def test_top_customers_basic():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-01", 100.0, "completed"),
        (2, "c1", "2024-01-02", 50.0, "completed"),
        (3, "c2", "2024-01-03", 200.0, "completed"),
    ])
    customers = pd.DataFrame([
        {"id": "c1", "name": "Alice"},
        {"id": "c2", "name": "Bob"},
    ])
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 1, 31)

    # Act
    result = top_customers(orders, customers, start, end, n=5)

    # Assert
    assert len(result) == 2
    assert result.iloc[0]["name"] == "Bob"
    assert result.iloc[0]["orders"] == 1
    assert result.iloc[0]["revenue"] == 200.0
    assert result.iloc[1]["name"] == "Alice"
    assert result.iloc[1]["orders"] == 2
    assert result.iloc[1]["revenue"] == 150.0


def test_top_customers_empty_range():
    # Arrange
    orders = _make_orders([
        (1, "c1", "2024-01-01", 100.0, "completed"),
    ])
    customers = pd.DataFrame([
        {"id": "c1", "name": "Alice"},
    ])
    start = datetime.date(2024, 2, 1)
    end = datetime.date(2024, 2, 28)

    # Act
    result = top_customers(orders, customers, start, end, n=5)

    # Assert
    assert result.empty
    assert list(result.columns) == ["name", "orders", "revenue"]
