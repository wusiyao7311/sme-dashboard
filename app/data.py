"""Load tables as DataFrames for the dashboard and KPI functions."""
import pandas as pd
from sqlalchemy.engine import Engine


def load_table(engine: Engine, table: str) -> pd.DataFrame:
    return pd.read_sql_table(table, engine)


def load_orders(engine: Engine) -> pd.DataFrame:
    df = load_table(engine, "orders")
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


def load_invoices(engine: Engine) -> pd.DataFrame:
    df = load_table(engine, "invoices")
    for col in ("issue_date", "due_date"):
        df[col] = pd.to_datetime(df[col])
    return df
