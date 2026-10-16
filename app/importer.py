from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Invoice, Order, OrderItem, Product


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";, \t")
        return dialect.delimiter
    except csv.Error:
        return ";"


def read_table(data: bytes, filename: str) -> pd.DataFrame:
    """Read CSV or XLSX bytes into a DataFrame with string cells."""
    lower_name = filename.lower()
    if lower_name.endswith(".csv"):
        text = _decode_csv(data)
        delimiter = _detect_delimiter(text[:2048])
        df = pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            dtype=str,
            keep_default_na=False,
            na_filter=False,
        )
    elif lower_name.endswith(".xlsx"):
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.values)
        wb.close()
        if len(rows) < 2:
            raise ValueError("The table is empty")
        df = pd.DataFrame(rows[1:], columns=[str(c) for c in rows[0]], dtype=object)
    else:
        raise ValueError("Unsupported file type")

    df = _normalize_dataframe(df)
    if df.empty:
        raise ValueError("The table is empty")
    return df


def _decode_csv(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.apply(lambda col: col.apply(lambda v: str(v).strip() if v is not None else ""))
    df = df[~(df == "").all(axis=1)]
    return df


def parse_number(value: str) -> float:
    """Parse a numeric string with European or US formatting."""
    cleaned = value.replace("EUR", "").replace("€", "").replace(" ", "")
    if not cleaned:
        raise ValueError("Empty value")
    has_comma = "," in cleaned
    has_dot = "." in cleaned
    if has_comma and has_dot:
        last_comma = cleaned.rfind(",")
        last_dot = cleaned.rfind(".")
        if last_comma > last_dot:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif has_comma:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif has_dot:
        parts = cleaned.split(".")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            pass
        else:
            cleaned = cleaned.replace(".", "")
    try:
        number = float(cleaned)
    except ValueError:
        raise ValueError(f"Invalid number: {value}")
    if not math.isfinite(number):
        raise ValueError(f"Invalid number: {value}")
    return number


def _require_columns(df: pd.DataFrame, required: list[str]) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")


def _parse_int(value: str) -> int | None:
    """'5' and Excel's '5.0' -> 5; anything else -> None."""
    try:
        number = float(str(value).strip())
    except (ValueError, TypeError):
        return None
    return int(number) if math.isfinite(number) and number == int(number) else None


def _optional_int(row: pd.Series, column: str, default: int) -> int | None:
    """Blank or missing -> default; invalid or negative -> None."""
    raw = str(row.get(column, "")).strip()
    if not raw:
        return default
    value = _parse_int(raw)
    return value if value is not None and value >= 0 else None


def import_products(session: Session, df: pd.DataFrame) -> ImportResult:
    """Import or update products from a DataFrame, upserting by SKU."""
    _require_columns(df, ["sku", "name", "price"])
    result = ImportResult()
    for idx, row in df.iterrows():
        row_num = idx + 2
        sku = str(row.get("sku", "")).strip()
        name = str(row.get("name", "")).strip()
        if not sku or not name:
            result.errors.append(f"Row {row_num}: missing sku or name")
            continue
        try:
            price = parse_number(str(row.get("price", "")))
        except ValueError:
            result.errors.append(f"Row {row_num}: invalid price")
            continue
        if price < 0:
            result.errors.append(f"Row {row_num}: negative price")
            continue
        category = str(row.get("category", "Allgemein")).strip() or "Allgemein"
        stock_qty = _optional_int(row, "stock_qty", 0)
        threshold = _optional_int(row, "low_stock_threshold", 10)
        if stock_qty is None or threshold is None:
            result.errors.append(f"Row {row_num}: invalid stock_qty or low_stock_threshold")
            continue
        product = session.scalar(select(Product).where(Product.sku == sku))
        if product is None:
            session.add(Product(sku=sku, name=name, price=price, category=category,
                                stock_qty=stock_qty, low_stock_threshold=threshold))
            result.created += 1
        else:
            product.name = name
            product.price = price
            product.category = category
            product.stock_qty = stock_qty
            product.low_stock_threshold = threshold
            result.updated += 1
    session.commit()
    return result


def import_customers(session: Session, df: pd.DataFrame) -> ImportResult:
    """Import or update customers from a DataFrame, upserting by email."""
    _require_columns(df, ["name", "email"])
    result = ImportResult()
    now = datetime.now()
    for idx, row in df.iterrows():
        row_num = idx + 2
        name = str(row.get("name", "")).strip()
        email = str(row.get("email", "")).strip().lower()
        if not name or not email or "@" not in email:
            result.errors.append(f"Row {row_num}: missing name or invalid email")
            continue
        city = str(row.get("city", "")).strip()
        customer = session.scalar(select(Customer).where(Customer.email == email))
        if customer is None:
            session.add(Customer(name=name, email=email, city=city, created_at=now))
            result.created += 1
        else:
            customer.name = name
            customer.city = city
            result.updated += 1
    session.commit()
    return result


def _parse_order_date(value: str) -> date | None:
    text = str(value).strip()
    if len(text) > 10 and text[10] in " T":  # Excel dates arrive as '2026-03-05 00:00:00'
        text = text[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _invoice_status(due_date: date) -> str:
    today = date.today()
    if due_date < today - timedelta(days=30):
        return "paid"
    if due_date < today:
        return "overdue"
    return "open"


def import_orders(session: Session, df: pd.DataFrame) -> ImportResult:
    """Import order lines grouped by order_ref; creates orders and invoices.

    Note: order_ref is not persisted, so re-importing the same data creates
    duplicate orders.
    """
    _require_columns(df, ["order_ref", "order_date", "customer_email", "sku", "qty"])
    result = ImportResult()
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for idx, row in df.iterrows():
        ref = str(row.get("order_ref", "")).strip()
        if not ref:
            continue
        groups.setdefault(ref, []).append((idx + 2, row.to_dict()))

    for ref, entries in groups.items():
        order = _build_order(session, ref, entries, result)
        if order is not None:
            result.created += 1
    session.commit()
    return result


def _build_order(
    session: Session,
    ref: str,
    entries: list[tuple[int, dict[str, Any]]],
    result: ImportResult,
) -> Order | None:
    row_nums = [row_num for row_num, _ in entries]
    items: list[tuple[Product, int]] = []
    emails = {str(row.get("customer_email", "")).strip().lower() for _, row in entries}
    dates = {_parse_order_date(str(row.get("order_date", ""))) for _, row in entries}
    if len(emails) != 1 or len(dates) != 1 or None in dates:
        result.errors.append(f"Rows {row_nums}: order {ref} needs one valid order_date and one customer")
        return None
    customer_email, order_date = emails.pop(), dates.pop()
    for _, row in entries:
        qty = _parse_int(str(row.get("qty", "")))
        if qty is None or qty <= 0:
            result.errors.append(f"Rows {row_nums}: invalid qty")
            return None
        sku = str(row.get("sku", "")).strip()
        product = session.scalar(select(Product).where(Product.sku == sku))
        if product is None:
            result.errors.append(f"Rows {row_nums}: unknown sku {sku}")
            return None
        items.append((product, qty))

    customer = session.scalar(select(Customer).where(Customer.email == customer_email))
    if customer is None:
        result.errors.append(f"Rows {row_nums}: unknown customer {customer_email}")
        return None

    total = round(sum(p.price * q for p, q in items), 2)
    order = Order(customer_id=customer.id, order_date=order_date, total=total, status="completed")
    session.add(order)
    session.flush()
    for product, qty in items:
        session.add(OrderItem(order_id=order.id, product_id=product.id, qty=qty, unit_price=product.price))
    due_date = order_date + timedelta(days=14)
    session.add(Invoice(order_id=order.id, issue_date=order_date, due_date=due_date,
                        amount=total, status=_invoice_status(due_date)))
    return order
