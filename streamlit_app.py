from __future__ import annotations

from datetime import date

import streamlit as st
import pandas as pd
import plotly.express as px

from app.db import get_engine
from app.data import load_table, load_orders, load_invoices
from app.i18n import t
from app.kpis import (
    compute_kpis,
    previous_period,
    revenue_over_time,
    top_products,
    top_customers,
)


@st.cache_data(ttl=60)
def load_data() -> dict:
    engine = get_engine()
    orders = load_orders(engine)
    invoices = load_invoices(engine)
    products = load_table(engine, "products")
    customers = load_table(engine, "customers")
    order_items = load_table(engine, "order_items")
    return {
        "orders": orders,
        "invoices": invoices,
        "products": products,
        "customers": customers,
        "order_items": order_items,
    }


def render_sidebar() -> tuple[str, date, date, str]:
    lang = st.sidebar.radio(
        t("de", "language"),
        ["de", "en"],
        index=0,
        format_func=lambda x: "Deutsch" if x == "de" else "English",
    )
    data = load_data()
    orders = data["orders"]
    if orders.empty:
        st.error(t(lang, "no_db"))
        st.stop()
    latest = orders["order_date"].max()
    default_start = latest - pd.Timedelta(days=90)
    picked = st.sidebar.date_input(
        t(lang, "date_range"),
        value=(default_start.date(), latest.date()),
        min_value=orders["order_date"].min().date(),
        max_value=latest.date(),
    )
    if len(picked) != 2:  # user has only clicked the first date so far
        st.stop()
    start, end = picked
    gran_keys = {"D": "day", "W": "week", "M": "month"}
    freq = st.sidebar.selectbox(
        t(lang, "granularity"), list(gran_keys), index=1, format_func=lambda k: t(lang, gran_keys[k])
    )
    return lang, start, end, freq


def render_kpis(
    lang: str,
    orders: pd.DataFrame,
    start: date,
    end: date,
) -> None:
    kpis = compute_kpis(orders, start, end)
    prev_start, prev_end = previous_period(start, end)
    prev = compute_kpis(orders, prev_start, prev_end)
    cols = [*st.columns(3), *st.columns(2)]  # two rows so values never truncate
    def fmt(v: float, decimals: int = 0) -> str:
        text = f"{v:,.{decimals}f}"
        if lang == "de":  # 12,345.60 -> 12.345,60
            text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
        return f"{text} EUR"

    for col, key, label in zip(
        cols,
        ["revenue", "avg_order_value", "order_count", "new_customers", "returning_customers"],
        [
            t(lang, "revenue"),
            t(lang, "avg_order_value"),
            t(lang, "orders"),
            t(lang, "new_customers"),
            t(lang, "returning_customers"),
        ],
    ):
        with col:
            val = kpis[key]
            prev_val = prev[key]
            delta = None
            if prev_val != 0:
                delta = (val - prev_val) / prev_val * 100
            if key in ("revenue", "avg_order_value"):
                st.metric(label, fmt(val, 2 if key == "avg_order_value" else 0), delta=f"{delta:.1f}%" if delta is not None else None)
            else:
                st.metric(label, int(val), delta=f"{delta:.1f}%" if delta is not None else None)


def render_chart(
    lang: str,
    orders: pd.DataFrame,
    start: date,
    end: date,
    freq: str,
) -> None:
    df = revenue_over_time(orders, start, end, freq)
    if df.empty:
        st.info(t(lang, "no_data"))
        return
    fig = px.line(
        df, x="period", y="revenue", title=t(lang, "revenue_over_time"),
        labels={"period": t(lang, "date"), "revenue": t(lang, "revenue") + " (EUR)"},
    )
    st.plotly_chart(fig)


def render_tables(
    lang: str,
    orders: pd.DataFrame,
    order_items: pd.DataFrame,
    products: pd.DataFrame,
    customers: pd.DataFrame,
    invoices: pd.DataFrame,
    start: date,
    end: date,
) -> None:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader(t(lang, "top_products"))
        tp = top_products(orders, order_items, products, start, end, n=5)
        if tp.empty:
            st.info(t(lang, "no_data"))
        else:
            tp = tp.rename(columns={"name": t(lang, "name"), "units": t(lang, "units"), "revenue": t(lang, "revenue")})
            st.dataframe(tp, hide_index=True, width="stretch")
    with col2:
        st.subheader(t(lang, "top_customers"))
        tc = top_customers(orders, customers, start, end, n=5)
        if tc.empty:
            st.info(t(lang, "no_data"))
        else:
            tc = tc.rename(columns={"name": t(lang, "name"), "orders": t(lang, "orders"), "revenue": t(lang, "revenue")})
            st.dataframe(tc, hide_index=True, width="stretch")
    st.subheader(t(lang, "open_invoices"))
    mask = invoices["status"].isin(["open", "overdue"])
    inv = invoices[mask].copy()
    if inv.empty:
        st.info(t(lang, "no_data"))
    else:
        inv = inv.sort_values(by=["status", "due_date"], ascending=[False, True])  # overdue first
        inv["status"] = inv["status"].map(lambda s: t(lang, s))
        inv["due_date"] = inv["due_date"].dt.date
        inv = inv[["id", "due_date", "amount", "status"]].rename(
            columns={
                "id": t(lang, "invoice"),
                "due_date": t(lang, "due_date"),
                "amount": t(lang, "amount"),
                "status": t(lang, "status"),
            }
        )
        st.dataframe(inv, hide_index=True, width="stretch")
        st.caption(f"{len(inv)} {t(lang, 'open_invoices')}")


def main() -> None:
    st.set_page_config(page_title="Business Dashboard", layout="wide")
    lang, start, end, freq = render_sidebar()
    data = load_data()
    orders = data["orders"]
    st.title(t(lang, "title"))
    render_kpis(lang, orders, start, end)
    render_chart(lang, orders, start, end, freq)
    render_tables(
        lang,
        orders,
        data["order_items"],
        data["products"],
        data["customers"],
        data["invoices"],
        start,
        end,
    )


if __name__ == "__main__":
    main()
