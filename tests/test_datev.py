import re
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Customer, Invoice, Order
from app.datev import DatevInvoice, build_datev_csv, load_invoices_for_export


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _split_csv(raw: bytes) -> list[str]:
    text = raw.decode("cp1252")
    lines = text.split("\r\n")
    # Remove trailing empty string from final \r\n
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _split_fields(line: str) -> list[str]:
    return line.split(";")


def test_header_line_has_26_fields_and_starts_with_extf_700_21():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 1, 15),
            amount=100.0,
            customer_id=1,
            customer_name="Test",
        )
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    lines = _split_csv(raw)
    header_fields = _split_fields(lines[0])
    assert len(header_fields) == 26
    assert header_fields[0] == '"EXTF"'
    assert header_fields[1] == "700"
    assert header_fields[2] == "21"
    assert header_fields[3] == '"Buchungsstapel"'


def test_second_line_has_14_column_headings():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 1, 15),
            amount=100.0,
            customer_id=1,
            customer_name="Test",
        )
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    lines = _split_csv(raw)
    column_fields = _split_fields(lines[1])
    assert len(column_fields) == 14


def test_each_data_row_has_exactly_14_fields():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 1, 15),
            amount=100.0,
            customer_id=1,
            customer_name="Test",
        ),
        DatevInvoice(
            invoice_id=2,
            issue_date=date(2023, 2, 15),
            amount=200.0,
            customer_id=2,
            customer_name="Test2",
        ),
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    lines = _split_csv(raw)
    for data_line in lines[2:]:
        fields = _split_fields(data_line)
        assert len(fields) == 14


def test_decimal_comma_and_two_decimals():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 1, 15),
            amount=1234.5,
            customer_id=1,
            customer_name="Test",
        )
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    lines = _split_csv(raw)
    data_fields = _split_fields(lines[2])
    assert data_fields[0] == "1234,50"


def test_konto_is_10000_plus_customer_id():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 1, 15),
            amount=100.0,
            customer_id=42,
            customer_name="Test",
        )
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    lines = _split_csv(raw)
    data_fields = _split_fields(lines[2])
    assert data_fields[6] == "10042"


def test_belegdatum_is_ddmm():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 3, 7),
            amount=100.0,
            customer_id=1,
            customer_name="Test",
        )
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    lines = _split_csv(raw)
    data_fields = _split_fields(lines[2])
    assert data_fields[9] == "0703"


def test_belegfeld_1_like_re_0007():
    invoices = [
        DatevInvoice(
            invoice_id=7,
            issue_date=date(2023, 1, 15),
            amount=100.0,
            customer_id=1,
            customer_name="Test",
        )
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    lines = _split_csv(raw)
    data_fields = _split_fields(lines[2])
    assert data_fields[10] == '"RE-0007"'


def test_text_fields_are_double_quoted_with_inner_quotes_doubled():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 1, 15),
            amount=100.0,
            customer_id=1,
            customer_name='He "llo',
        )
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    lines = _split_csv(raw)
    data_fields = _split_fields(lines[2])
    assert data_fields[1] == '"S"'
    assert data_fields[2] == '"EUR"'
    assert data_fields[13] == '"He ""llo"'


def test_line_breaks_in_name_are_removed():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 1, 15),
            amount=100.0,
            customer_id=1,
            customer_name="Line1\nLine2",
        )
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    lines = _split_csv(raw)
    data_fields = _split_fields(lines[2])
    assert data_fields[13] == '"Line1 Line2"'


def test_umlauts_survive_cp1252_round_trip():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 1, 15),
            amount=100.0,
            customer_id=1,
            customer_name="Müller",
        )
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    decoded = raw.decode("cp1252")
    assert "Müller" in decoded


def test_characters_outside_cp1252_become_question_mark():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 1, 15),
            amount=100.0,
            customer_id=1,
            customer_name="中文",
        )
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    decoded = raw.decode("cp1252")
    assert "??" in decoded and "\u4e2d" not in decoded


def test_lines_end_with_crlf():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 1, 15),
            amount=100.0,
            customer_id=1,
            customer_name="Test",
        )
    ]
    raw = build_datev_csv(
        invoices,
        date_from=date(2023, 1, 1),
        date_to=date(2023, 12, 31),
        created=datetime(2023, 1, 1, 12, 0, 0),
    )
    assert raw.endswith(b"\r\n")
    assert b"\n" not in raw.replace(b"\r\n", b"")


def test_value_error_for_empty_list():
    with pytest.raises(ValueError, match="invoices list must not be empty"):
        build_datev_csv(
            [],
            date_from=date(2023, 1, 1),
            date_to=date(2023, 12, 31),
            created=datetime(2023, 1, 1, 12, 0, 0),
        )


def test_value_error_for_consultant_no_zero():
    invoices = [
        DatevInvoice(
            invoice_id=1,
            issue_date=date(2023, 1, 15),
            amount=100.0,
            customer_id=1,
            customer_name="Test",
        )
    ]
    with pytest.raises(ValueError, match="consultant_no and client_no must be >= 1"):
        build_datev_csv(
            invoices,
            date_from=date(2023, 1, 1),
            date_to=date(2023, 12, 31),
            consultant_no=0,
            created=datetime(2023, 1, 1, 12, 0, 0),
        )


def test_load_invoices_for_export_filters_by_date_inclusive_and_orders_by_date_then_id(db_session):
    customer1 = Customer(id=1, name="Cust1", email="c1@example.com", city="City1", created_at=datetime(2023, 1, 1))
    customer2 = Customer(id=2, name="Cust2", email="c2@example.com", city="City2", created_at=datetime(2023, 1, 1))
    db_session.add_all([customer1, customer2])
    db_session.flush()

    order1 = Order(id=1, customer_id=1, order_date=date(2023, 1, 10), total=100.0, status="completed")
    order2 = Order(id=2, customer_id=2, order_date=date(2023, 1, 10), total=200.0, status="completed")
    order3 = Order(id=3, customer_id=1, order_date=date(2023, 1, 20), total=300.0, status="completed")
    db_session.add_all([order1, order2, order3])
    db_session.flush()

    inv1 = Invoice(id=1, order_id=1, issue_date=date(2023, 1, 10), due_date=date(2023, 2, 10), amount=100.0, status="open")
    inv2 = Invoice(id=2, order_id=2, issue_date=date(2023, 1, 10), due_date=date(2023, 2, 10), amount=200.0, status="open")
    inv3 = Invoice(id=3, order_id=3, issue_date=date(2023, 1, 20), due_date=date(2023, 2, 20), amount=300.0, status="open")
    inv_outside = Invoice(id=4, order_id=1, issue_date=date(2022, 12, 31), due_date=date(2023, 1, 30), amount=50.0, status="open")
    db_session.add_all([inv1, inv2, inv3, inv_outside])
    db_session.commit()

    result = load_invoices_for_export(db_session, date_from=date(2023, 1, 10), date_to=date(2023, 1, 20))
    assert len(result) == 3
    assert result[0].invoice_id == 1
    assert result[1].invoice_id == 2
    assert result[2].invoice_id == 3


def test_load_invoices_for_export_include_paid_false_drops_paid_invoices(db_session):
    customer1 = Customer(id=1, name="Cust1", email="c1@example.com", city="City1", created_at=datetime(2023, 1, 1))
    db_session.add(customer1)
    db_session.flush()

    order1 = Order(id=1, customer_id=1, order_date=date(2023, 1, 10), total=100.0, status="completed")
    order2 = Order(id=2, customer_id=1, order_date=date(2023, 1, 10), total=200.0, status="completed")
    db_session.add_all([order1, order2])
    db_session.flush()

    inv_paid = Invoice(id=1, order_id=1, issue_date=date(2023, 1, 10), due_date=date(2023, 2, 10), amount=100.0, status="paid")
    inv_open = Invoice(id=2, order_id=2, issue_date=date(2023, 1, 10), due_date=date(2023, 2, 10), amount=200.0, status="open")
    db_session.add_all([inv_paid, inv_open])
    db_session.commit()

    result = load_invoices_for_export(db_session, date_from=date(2023, 1, 1), date_to=date(2023, 12, 31), include_paid=False)
    assert len(result) == 1
    assert result[0].invoice_id == 2
