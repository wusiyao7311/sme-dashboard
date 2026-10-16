from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data import load_orders
from app.formatting import format_eur
from app.kpis import compute_kpis, previous_period
from app.mailer import send_email
from app.models import Customer, Invoice, Order, Product, Setting

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, str] = {
    "summary_email_recipients": "owner@example.com",
    "summary_schedule": "weekly",
    "default_low_stock_threshold": "10",
    "language": "de",
    "reminder_interval_days": "7",
}


def get_settings(session: Session) -> dict[str, str]:
    """Return all settings as a dict, applying defaults for missing keys."""
    rows = session.execute(select(Setting)).scalars().all()
    settings = {row.key: row.value for row in rows}
    for key, value in DEFAULT_SETTINGS.items():
        settings.setdefault(key, value)
    return settings


def find_low_stock(session: Session) -> list[Product]:
    """Return products below their low stock threshold, ordered by stock_qty."""
    stmt = (
        select(Product)
        .where(Product.stock_qty < Product.low_stock_threshold)
        .order_by(Product.stock_qty.asc())
    )
    return list(session.execute(stmt).scalars().all())


def find_invoices_to_remind(
    session: Session, today: date, interval_days: int
) -> list[tuple[Invoice, Customer]]:
    """Return overdue unpaid invoices needing a reminder, joined to customer."""
    cutoff = datetime.combine(today - timedelta(days=interval_days), time(23, 59, 59))
    stmt = (
        select(Invoice, Customer)
        .join(Order, Invoice.order_id == Order.id)
        .join(Customer, Order.customer_id == Customer.id)
        .where(
            Invoice.status != "paid",
            Invoice.due_date < today,
            (Invoice.reminder_sent_at.is_(None)) | (Invoice.reminder_sent_at < cutoff),
        )
        .order_by(Invoice.due_date.asc())
    )
    return [(inv, cust) for inv, cust in session.execute(stmt).all()]


def build_low_stock_email(products: list[Product], lang: str) -> tuple[str, str]:
    """Build subject and body for low stock alert email."""
    if lang == "de":
        subject = "Warnung: Lagerbestand niedrig"
        header = "Folgende Produkte sind unter dem Mindestbestand:"
    else:
        subject = "Alert: Low stock levels"
        header = "The following products are below minimum stock:"
    lines = [
        f"{p.name} (SKU {p.sku}): {p.stock_qty}/{p.low_stock_threshold}"
        for p in products
    ]
    body = f"{header}\n" + "\n".join(lines)
    return subject, body


def build_reminder_email(
    invoice: Invoice, customer: Customer, today: date, lang: str
) -> tuple[str, str]:
    """Build a polite payment reminder email for an overdue invoice."""
    days_overdue = (today - invoice.due_date).days
    amount_str = format_eur(invoice.amount, lang)
    if lang == "de":
        subject = f"Zahlungserinnerung: Rechnung #{invoice.id}"
        body = (
            f"Sehr geehrte/r {customer.name},\n\n"
            f"unsere Aufzeichnungen zeigen, dass Rechnung #{invoice.id} "
            f"über {amount_str} am {invoice.due_date.isoformat()} fällig war "
            f"und nun {days_overdue} Tage überfällig ist.\n\n"
            f"Wir bitten Sie, die Zahlung baldmöglichst zu veranlassen.\n\n"
            f"Mit freundlichen Grüßen"
        )
    else:
        subject = f"Payment Reminder: Invoice #{invoice.id}"
        body = (
            f"Dear {customer.name},\n\n"
            f"our records show that invoice #{invoice.id} for {amount_str} "
            f"was due on {invoice.due_date.isoformat()} and is now "
            f"{days_overdue} days overdue.\n\n"
            f"Please arrange payment at your earliest convenience.\n\n"
            f"Kind regards"
        )
    return subject, body


def _format_change(current: float, previous: float) -> str:
    """Format percentage change, omitting if previous is zero."""
    if previous == 0:
        return ""
    pct = ((current - previous) / previous) * 100
    return f" ({pct:+.1f}%)"


def build_summary_email(
    session: Session, today: date, lang: str, days: int = 7
) -> tuple[str, str]:
    """Build weekly KPI summary email with period-over-period comparison."""
    end_date = today
    start_date = today - timedelta(days=days - 1)
    orders_df = load_orders(session.get_bind())
    current = compute_kpis(orders_df, start_date, end_date)
    prev_start, prev_end = previous_period(start_date, end_date)
    previous = compute_kpis(orders_df, prev_start, prev_end)

    overdue_count = session.execute(
        select(func.count(Invoice.id)).where(Invoice.status != "paid", Invoice.due_date < today)
    ).scalar_one()
    low_stock_count = len(find_low_stock(session))

    if lang == "de":
        subject = "Wöchentliche KPI-Zusammenfassung"
        lines = [
            f"Umsatz: {format_eur(current['revenue'], lang)}{_format_change(current['revenue'], previous['revenue'])}",
            f"Bestellungen: {current['order_count']}{_format_change(current['order_count'], previous['order_count'])}",
            f"Durchschnittlicher Bestellwert: {format_eur(current['avg_order_value'], lang)}{_format_change(current['avg_order_value'], previous['avg_order_value'])}",
            f"Neue Kunden: {current['new_customers']}{_format_change(current['new_customers'], previous['new_customers'])}",
            f"Überfällige Rechnungen: {overdue_count}",
            f"Produkte mit niedrigem Bestand: {low_stock_count}",
        ]
    else:
        subject = "Weekly KPI Summary"
        lines = [
            f"Revenue: {format_eur(current['revenue'], lang)}{_format_change(current['revenue'], previous['revenue'])}",
            f"Orders: {current['order_count']}{_format_change(current['order_count'], previous['order_count'])}",
            f"Average Order Value: {format_eur(current['avg_order_value'], lang)}{_format_change(current['avg_order_value'], previous['avg_order_value'])}",
            f"New Customers: {current['new_customers']}{_format_change(current['new_customers'], previous['new_customers'])}",
            f"Overdue Invoices: {overdue_count}",
            f"Low Stock Products: {low_stock_count}",
        ]
    body = "\n".join(lines)
    return subject, body


def _parse_recipients(raw: str) -> list[str]:
    """Parse comma-separated recipient string into a clean list."""
    return [r.strip() for r in raw.split(",") if r.strip()]


def run_low_stock_alert(session: Session, today: date) -> int:
    """Send low stock alert email to all recipients if any products are low."""
    products = find_low_stock(session)
    if not products:
        return 0
    settings = get_settings(session)
    lang = settings.get("language", "de")
    subject, body = build_low_stock_email(products, lang)
    recipients = _parse_recipients(settings.get("summary_email_recipients", ""))
    for recipient in recipients:
        send_email(recipient, subject, body)
    return len(products)


def run_payment_reminders(session: Session, today: date) -> int:
    """Send payment reminders for overdue invoices; mark them as overdue."""
    settings = get_settings(session)
    lang = settings.get("language", "de")
    interval_days = int(settings.get("reminder_interval_days", "7"))
    invoices = find_invoices_to_remind(session, today, interval_days)
    sent_count = 0
    reminder_time = datetime.combine(today, time(9, 0))
    for invoice, customer in invoices:
        try:
            subject, body = build_reminder_email(invoice, customer, today, lang)
            send_email(customer.email, subject, body)
            invoice.reminder_sent_at = reminder_time
            invoice.status = "overdue"
            sent_count += 1
        except Exception:
            logger.exception("Reminder for invoice %s failed", invoice.id)
    session.commit()
    return sent_count


def run_summary(session: Session, today: date) -> int:
    """Send weekly summary email to all recipients; return count sent."""
    settings = get_settings(session)
    lang = settings.get("language", "de")
    subject, body = build_summary_email(session, today, lang)
    recipients = _parse_recipients(settings.get("summary_email_recipients", ""))
    sent_count = 0
    for recipient in recipients:
        send_email(recipient, subject, body)
        sent_count += 1
    return sent_count
