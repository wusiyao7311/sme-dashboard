"""Tests for app.automations module."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import List, Tuple

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, Customer, Invoice, Order, Product, Setting
from app.automations import (
    build_reminder_email,
    find_invoices_to_remind,
    find_low_stock,
    get_settings,
    run_low_stock_alert,
    run_payment_reminders,
    run_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    """In-memory SQLite engine with StaticPool so all sessions share the same DB."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine) -> Session:
    """A single Session bound to the in-memory engine."""
    with Session(engine) as s:
        yield s


@pytest.fixture()
def today() -> date:
    """Fixed 'today' for deterministic tests."""
    return date(2026, 10, 16)


@pytest.fixture()
def sent_emails(monkeypatch) -> List[Tuple[str, str, str]]:
    """
    Replace app.automations.send_email with a fake that records calls.
    Returns the list of (to, subject, body) tuples.
    """
    calls: List[Tuple[str, str, str]] = []

    def fake_send_email(to: str, subject: str, body: str) -> None:
        calls.append((to, subject, body))

    monkeypatch.setattr("app.automations.send_email", fake_send_email)
    return calls


# ---------------------------------------------------------------------------
# Helpers to build tiny fixtures by hand
# ---------------------------------------------------------------------------

def _make_product(
    session: Session,
    *,
    name: str = "Widget",
    sku: str = "W-001",
    category: str = "General",
    price: float = 9.99,
    stock_qty: int = 50,
    low_stock_threshold: int = 10,
) -> Product:
    p = Product(
        name=name,
        sku=sku,
        category=category,
        price=price,
        stock_qty=stock_qty,
        low_stock_threshold=low_stock_threshold,
    )
    session.add(p)
    session.flush()
    return p


def _make_customer(
    session: Session,
    *,
    name: str = "Alice",
    email: str = "alice@example.com",
    city: str = "Berlin",
    created_at: datetime | None = None,
) -> Customer:
    if created_at is None:
        created_at = datetime(2026, 1, 1, 9, 0, 0)
    c = Customer(name=name, email=email, city=city, created_at=created_at)
    session.add(c)
    session.flush()
    return c


def _make_order(
    session: Session,
    *,
    customer: Customer,
    order_date: date,
    total: float = 100.0,
    status: str = "completed",
) -> Order:
    o = Order(
        customer_id=customer.id,
        order_date=order_date,
        total=total,
        status=status,
    )
    session.add(o)
    session.flush()
    return o


def _make_invoice(
    session: Session,
    *,
    order: Order,
    issue_date: date,
    due_date: date,
    amount: float = 100.0,
    status: str = "open",
    reminder_sent_at: datetime | None = None,
) -> Invoice:
    inv = Invoice(
        order_id=order.id,
        issue_date=issue_date,
        due_date=due_date,
        amount=amount,
        status=status,
        reminder_sent_at=reminder_sent_at,
    )
    session.add(inv)
    session.flush()
    return inv


def _make_setting(
    session: Session,
    key: str,
    value: str,
) -> Setting:
    s = Setting(key=key, value=value)
    session.add(s)
    session.flush()
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_get_settings_returns_defaults_when_no_rows(session: Session) -> None:
    """
    Arrange: empty settings table.
    Act: call get_settings.
    Assert: all DEFAULT_SETTINGS keys are present with their default values.
    """
    # Arrange
    # (nothing to add)

    # Act
    result = get_settings(session)

    # Assert
    assert result["summary_email_recipients"] == "owner@example.com"
    assert result["summary_schedule"] == "weekly"
    assert result["default_low_stock_threshold"] == "10"
    assert result["language"] == "de"
    assert result["reminder_interval_days"] == "7"


def test_get_settings_db_values_override_defaults(session: Session) -> None:
    """
    Arrange: insert a Setting row that overrides one default.
    Act: call get_settings.
    Assert: the DB value wins; other keys still fall back to defaults.
    """
    # Arrange
    _make_setting(session, "language", "en")

    # Act
    result = get_settings(session)

    # Assert
    assert result["language"] == "en"
    # A key not in DB still uses the default
    assert result["summary_email_recipients"] == "owner@example.com"


def test_find_low_stock_returns_only_below_threshold_ordered_by_stock(
    session: Session,
) -> None:
    """
    Arrange: three products, two below threshold, one above.
    Act: call find_low_stock.
    Assert: only the two low-stock products are returned, ordered ascending by stock_qty.
    """
    # Arrange
    p_high = _make_product(
        session, name="High", sku="H-1", stock_qty=100, low_stock_threshold=10
    )
    p_mid = _make_product(
        session, name="Mid", sku="M-1", stock_qty=5, low_stock_threshold=10
    )
    p_low = _make_product(
        session, name="Low", sku="L-1", stock_qty=1, low_stock_threshold=10
    )

    # Act
    result = find_low_stock(session)

    # Assert
    assert len(result) == 2
    assert result[0].id == p_low.id
    assert result[1].id == p_mid.id
    assert p_high.id not in {p.id for p in result}


def test_find_invoices_to_remind_excludes_paid(
    session: Session, today: date
) -> None:
    """
    Arrange: an overdue invoice with status 'paid'.
    Act: call find_invoices_to_remind.
    Assert: the paid invoice is not returned.
    """
    # Arrange
    cust = _make_customer(session, name="Bob", email="bob@example.com")
    order = _make_order(session, customer=cust, order_date=today - timedelta(days=30))
    _make_invoice(
        session,
        order=order,
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=10),
        amount=50.0,
        status="paid",
    )

    # Act
    result = find_invoices_to_remind(session, today, interval_days=7)

    # Assert
    assert result == []


def test_find_invoices_to_remind_excludes_not_yet_due(
    session: Session, today: date
) -> None:
    """
    Arrange: an open invoice whose due_date is in the future.
    Act: call find_invoices_to_remind.
    Assert: the not-yet-due invoice is not returned.
    """
    # Arrange
    cust = _make_customer(session, name="Carol", email="carol@example.com")
    order = _make_order(session, customer=cust, order_date=today - timedelta(days=5))
    _make_invoice(
        session,
        order=order,
        issue_date=today - timedelta(days=5),
        due_date=today + timedelta(days=10),
        amount=75.0,
        status="open",
    )

    # Act
    result = find_invoices_to_remind(session, today, interval_days=7)

    # Assert
    assert result == []


def test_find_invoices_to_remind_excludes_recently_reminded(
    session: Session, today: date
) -> None:
    """
    Arrange: an overdue invoice that was reminded 3 days ago (within 7-day interval).
    Act: call find_invoices_to_remind with interval_days=7.
    Assert: the recently reminded invoice is not returned.
    """
    # Arrange
    cust = _make_customer(session, name="Dave", email="dave@example.com")
    order = _make_order(session, customer=cust, order_date=today - timedelta(days=30))
    _make_invoice(
        session,
        order=order,
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=10),
        amount=60.0,
        status="open",
        reminder_sent_at=datetime.combine(today - timedelta(days=3), time(9, 0)),
    )

    # Act
    result = find_invoices_to_remind(session, today, interval_days=7)

    # Assert
    assert result == []


def test_find_invoices_to_remind_includes_never_reminded(
    session: Session, today: date
) -> None:
    """
    Arrange: an overdue invoice that has never been reminded.
    Act: call find_invoices_to_remind.
    Assert: the invoice is returned with its customer.
    """
    # Arrange
    cust = _make_customer(session, name="Eve", email="eve@example.com")
    order = _make_order(session, customer=cust, order_date=today - timedelta(days=30))
    inv = _make_invoice(
        session,
        order=order,
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=10),
        amount=80.0,
        status="open",
        reminder_sent_at=None,
    )

    # Act
    result = find_invoices_to_remind(session, today, interval_days=7)

    # Assert
    assert len(result) == 1
    assert result[0][0].id == inv.id
    assert result[0][1].id == cust.id


def test_find_invoices_to_remind_includes_old_reminded(
    session: Session, today: date
) -> None:
    """
    Arrange: an overdue invoice that was reminded 10 days ago (outside 7-day interval).
    Act: call find_invoices_to_remind with interval_days=7.
    Assert: the old-reminded invoice is returned.
    """
    # Arrange
    cust = _make_customer(session, name="Frank", email="frank@example.com")
    order = _make_order(session, customer=cust, order_date=today - timedelta(days=40))
    inv = _make_invoice(
        session,
        order=order,
        issue_date=today - timedelta(days=40),
        due_date=today - timedelta(days=20),
        amount=90.0,
        status="open",
        reminder_sent_at=datetime.combine(today - timedelta(days=10), time(9, 0)),
    )

    # Act
    result = find_invoices_to_remind(session, today, interval_days=7)

    # Assert
    assert len(result) == 1
    assert result[0][0].id == inv.id


def test_run_payment_reminders_sends_one_email_per_eligible_invoice(
    session: Session, today: date, sent_emails: List[Tuple[str, str, str]]
) -> None:
    """
    Arrange: two overdue, never-reminded invoices for two different customers.
    Act: call run_payment_reminders.
    Assert:
      - one email sent to each customer's address,
      - each invoice's reminder_sent_at is set and status is 'overdue',
      - a second run the same day sends 0 emails.
    """
    # Arrange
    cust1 = _make_customer(session, name="Alice", email="alice@example.com")
    cust2 = _make_customer(session, name="Bob", email="bob@example.com")

    order1 = _make_order(session, customer=cust1, order_date=today - timedelta(days=30))
    inv1 = _make_invoice(
        session,
        order=order1,
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=10),
        amount=100.0,
        status="open",
        reminder_sent_at=None,
    )

    order2 = _make_order(session, customer=cust2, order_date=today - timedelta(days=30))
    inv2 = _make_invoice(
        session,
        order=order2,
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=15),
        amount=200.0,
        status="open",
        reminder_sent_at=None,
    )

    # Act – first run
    count1 = run_payment_reminders(session, today)

    # Assert – first run
    assert count1 == 2
    assert len(sent_emails) == 2

    # Verify each email went to the correct customer
    recipients = {email[0] for email in sent_emails}
    assert "alice@example.com" in recipients
    assert "bob@example.com" in recipients

    # Verify invoice state was updated
    session.refresh(inv1)
    session.refresh(inv2)
    assert inv1.reminder_sent_at is not None
    assert inv1.status == "overdue"
    assert inv2.reminder_sent_at is not None
    assert inv2.status == "overdue"

    # Act – second run same day
    count2 = run_payment_reminders(session, today)

    # Assert – second run sends nothing
    assert count2 == 0
    assert len(sent_emails) == 2  # no new emails


def test_run_payment_reminders_continues_on_send_email_error(
    session: Session, today: date, monkeypatch
) -> None:
    """
    Arrange: two eligible invoices; monkeypatch send_email to raise for the first
    customer's email but succeed for the second.
    Act: call run_payment_reminders.
    Assert:
      - the first invoice is NOT marked (reminder_sent_at stays None, status unchanged),
      - the second invoice IS marked,
      - the function returns 1 (only the successful send).
    """
    # Arrange
    cust1 = _make_customer(session, name="Alice", email="alice@example.com")
    cust2 = _make_customer(session, name="Bob", email="bob@example.com")

    order1 = _make_order(session, customer=cust1, order_date=today - timedelta(days=30))
    inv1 = _make_invoice(
        session,
        order=order1,
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=10),
        amount=100.0,
        status="open",
        reminder_sent_at=None,
    )

    order2 = _make_order(session, customer=cust2, order_date=today - timedelta(days=30))
    inv2 = _make_invoice(
        session,
        order=order2,
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=15),
        amount=200.0,
        status="open",
        reminder_sent_at=None,
    )

    # Monkeypatch send_email to raise for alice but succeed for bob
    def flaky_send_email(to: str, subject: str, body: str) -> None:
        if to == "alice@example.com":
            raise RuntimeError("SMTP failure")

    monkeypatch.setattr("app.automations.send_email", flaky_send_email)

    # Act
    count = run_payment_reminders(session, today)

    # Assert
    assert count == 1

    session.refresh(inv1)
    session.refresh(inv2)

    # First invoice should NOT be marked
    assert inv1.reminder_sent_at is None
    assert inv1.status == "open"

    # Second invoice should be marked
    assert inv2.reminder_sent_at is not None
    assert inv2.status == "overdue"


def test_run_low_stock_alert_sends_to_every_comma_separated_recipient(
    session: Session, today: date, sent_emails: List[Tuple[str, str, str]]
) -> None:
    """
    Arrange: one low-stock product; settings with three comma-separated recipients.
    Act: call run_low_stock_alert.
    Assert: one email sent to each of the three recipients.
    """
    # Arrange
    _make_product(
        session, name="LowItem", sku="L-1", stock_qty=2, low_stock_threshold=10
    )
    _make_setting(
        session,
        "summary_email_recipients",
        "a@example.com, b@example.com, c@example.com",
    )

    # Act
    count = run_low_stock_alert(session, today)

    # Assert
    assert count == 1  # number of low-stock products
    assert len(sent_emails) == 3
    recipients = {email[0] for email in sent_emails}
    assert "a@example.com" in recipients
    assert "b@example.com" in recipients
    assert "c@example.com" in recipients


def test_run_low_stock_alert_sends_nothing_when_stock_is_fine(
    session: Session, today: date, sent_emails: List[Tuple[str, str, str]]
) -> None:
    """
    Arrange: all products have stock above threshold.
    Act: call run_low_stock_alert.
    Assert: no emails are sent and the return value is 0.
    """
    # Arrange
    _make_product(
        session, name="FineItem", sku="F-1", stock_qty=50, low_stock_threshold=10
    )

    # Act
    count = run_low_stock_alert(session, today)

    # Assert
    assert count == 0
    assert len(sent_emails) == 0


def test_run_summary_sends_one_email_per_recipient_with_revenue_and_overdue_count(
    session: Session, today: date, sent_emails: List[Tuple[str, str, str]]
) -> None:
    """
    Arrange:
      - one order with a known total (revenue),
      - one overdue invoice,
      - settings with two comma-separated recipients.
    Act: call run_summary.
    Assert:
      - one email per recipient (2 total),
      - the body contains the revenue amount and the overdue count.
    """
    # Arrange
    cust = _make_customer(session, name="Alice", email="alice@example.com")
    order = _make_order(
        session,
        customer=cust,
        order_date=today - timedelta(days=3),
        total=250.0,
        status="completed",
    )
    _make_invoice(
        session,
        order=order,
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=10),
        amount=250.0,
        status="open",
        reminder_sent_at=None,
    )
    _make_setting(
        session,
        "summary_email_recipients",
        "owner1@example.com, owner2@example.com",
    )

    # Act
    count = run_summary(session, today)

    # Assert
    assert count == 2
    assert len(sent_emails) == 2

    # Check that each email body contains the revenue and overdue count
    for to, subject, body in sent_emails:
        # Revenue: 250.00 EUR (de format) or 250.00 EUR (en format)
        # The _eur function for de produces "250,00 EUR" and for en "250.00 EUR"
        # Since default language is "de", expect "250,00 EUR"
        assert "250,00 EUR" in body or "250.00 EUR" in body
        # Overdue count should be 1
        assert "1" in body


def test_build_reminder_email_de_mentions_invoice_id_and_days_overdue(
    session: Session, today: date
) -> None:
    """
    Arrange: an invoice with due_date 10 days before today.
    Act: call build_reminder_email with lang='de'.
    Assert: subject and body mention the invoice id and the days overdue (10).
    """
    # Arrange
    cust = _make_customer(session, name="Alice", email="alice@example.com")
    order = _make_order(session, customer=cust, order_date=today - timedelta(days=30))
    inv = _make_invoice(
        session,
        order=order,
        issue_date=today - timedelta(days=30),
        due_date=today - timedelta(days=10),
        amount=150.0,
        status="open",
    )

    # Act
    subject, body = build_reminder_email(inv, cust, today, lang="de")

    # Assert
    assert str(inv.id) in subject
    assert str(inv.id) in body
    assert "10" in body  # days overdue


def test_build_reminder_email_en_mentions_invoice_id_and_days_overdue(
    session: Session, today: date
) -> None:
    """
    Arrange: an invoice with due_date 5 days before today.
    Act: call build_reminder_email with lang='en'.
    Assert: subject and body mention the invoice id and the days overdue (5).
    """
    # Arrange
    cust = _make_customer(session, name="Bob", email="bob@example.com")
    order = _make_order(session, customer=cust, order_date=today - timedelta(days=20))
    inv = _make_invoice(
        session,
        order=order,
        issue_date=today - timedelta(days=20),
        due_date=today - timedelta(days=5),
        amount=75.0,
        status="open",
    )

    # Act
    subject, body = build_reminder_email(inv, cust, today, lang="en")

    # Assert
    assert str(inv.id) in subject
    assert str(inv.id) in body
    assert "5" in body  # days overdue
