from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Customer, Invoice, Order


@dataclass(frozen=True)
class DatevInvoice:
    invoice_id: int
    issue_date: date
    amount: float
    customer_id: int
    customer_name: str


def _fmt_num(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _fmt_date_compact(d: date) -> str:
    return d.strftime("%Y%m%d")


def _fmt_belegdatum(d: date) -> str:
    return d.strftime("%d%m")


def _fmt_created(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S") + f"{dt.microsecond // 1000:03d}"


def _sanitize_text(text: str, max_len: int) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\-_./]", "", text)
    return cleaned[:max_len]


def _quote(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _build_header(
    created: datetime,
    consultant_no: int,
    client_no: int,
    fiscal_year_start: date,
    date_from: date,
    date_to: date,
    label: str,
) -> str:
    fields = [
        _quote("EXTF"),
        "700",
        "21",
        _quote("Buchungsstapel"),
        "12",
        _fmt_created(created),
        "",
        _quote("RE"),
        _quote(""),
        _quote(""),
        str(consultant_no),
        str(client_no),
        _fmt_date_compact(fiscal_year_start),
        "4",
        _fmt_date_compact(date_from),
        _fmt_date_compact(date_to),
        _quote(label),
        _quote(""),
        "1",
        "0",
        "0",
        _quote("EUR"),
        "",
        "",
        "",
        "",
    ]
    return ";".join(fields)


def _build_column_headings() -> str:
    headings = [
        "Umsatz (ohne Soll/Haben-Kz)",
        "Soll/Haben-Kennzeichen",
        "WKZ Umsatz",
        "Kurs",
        "Basis-Umsatz",
        "WKZ Basis-Umsatz",
        "Konto",
        "Gegenkonto (ohne BU-Schlüssel)",
        "BU-Schlüssel",
        "Belegdatum",
        "Belegfeld 1",
        "Belegfeld 2",
        "Skonto",
        "Buchungstext",
    ]
    return ";".join(headings)


def _build_data_row(inv: DatevInvoice, revenue_account: int) -> str:
    amount_str = _fmt_num(inv.amount)
    konto = str(10000 + inv.customer_id)
    gegenkonto = str(revenue_account)
    belegdatum = _fmt_belegdatum(inv.issue_date)
    belegfeld1 = _sanitize_text(f"RE-{inv.invoice_id:04d}", 36)
    buchungstext = " ".join(inv.customer_name.split())[:60]  # no line breaks inside a record
    fields = [
        amount_str,
        _quote("S"),
        _quote("EUR"),
        "",
        "",
        "",
        konto,
        gegenkonto,
        "",
        belegdatum,
        _quote(belegfeld1),
        "",
        "",
        _quote(buchungstext),
    ]
    return ";".join(fields)


def build_datev_csv(
    invoices: list[DatevInvoice],
    date_from: date,
    date_to: date,
    consultant_no: int = 1001,
    client_no: int = 1,
    revenue_account: int = 8400,
    created: Optional[datetime] = None,
    label: str = "Rechnungen",
) -> bytes:
    if not invoices:
        raise ValueError("invoices list must not be empty")
    if consultant_no < 1 or client_no < 1:
        raise ValueError("consultant_no and client_no must be >= 1")
    if created is None:
        created = datetime.now()
    fiscal_year_start = date(date_from.year, 1, 1)
    header_line = _build_header(
        created, consultant_no, client_no, fiscal_year_start, date_from, date_to, label
    )
    column_line = _build_column_headings()
    data_lines = [_build_data_row(inv, revenue_account) for inv in invoices]
    all_lines = [header_line, column_line] + data_lines
    text = "\r\n".join(all_lines) + "\r\n"
    return text.encode("cp1252", errors="replace")


def load_invoices_for_export(
    session: Session,
    date_from: date,
    date_to: date,
    include_paid: bool = True,
) -> list[DatevInvoice]:
    query = (
        session.query(Invoice, Order, Customer)
        .join(Order, Invoice.order_id == Order.id)
        .join(Customer, Order.customer_id == Customer.id)
        .filter(Invoice.issue_date >= date_from)
        .filter(Invoice.issue_date <= date_to)
        .order_by(Invoice.issue_date, Invoice.id)
    )
    if not include_paid:
        query = query.filter(Invoice.status != "paid")
    result: list[DatevInvoice] = []
    for inv, order, customer in query.all():
        result.append(
            DatevInvoice(
                invoice_id=inv.id,
                issue_date=inv.issue_date,
                amount=inv.amount,
                customer_id=customer.id,
                customer_name=customer.name,
            )
        )
    return result
