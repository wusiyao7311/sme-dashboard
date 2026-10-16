"""Tests for app.importer module."""
from __future__ import annotations

import io
from datetime import date, timedelta

import openpyxl
import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.importer import (
    ImportResult,
    import_customers,
    import_orders,
    import_products,
    parse_number,
    read_table,
)
from app.models import Base, Customer, Invoice, Order, OrderItem, Product


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    """In-memory SQLite engine with schema created."""
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def session(engine) -> Session:
    """A fresh session bound to the in-memory engine."""
    with Session(engine) as s:
        yield s


# ---------------------------------------------------------------------------
# Helpers to build input bytes
# ---------------------------------------------------------------------------

def _csv_bytes(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


def _xlsx_bytes(rows: list[list]) -> bytes:
    """Create an .xlsx file in memory from a list of rows (first row = header)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# parse_number tests
# ---------------------------------------------------------------------------

class TestParseNumber:
    def test_european_decimal_with_thousands(self):
        assert parse_number("1.234,56") == pytest.approx(1234.56)

    def test_european_decimal_no_thousands(self):
        assert parse_number("1234,56") == pytest.approx(1234.56)

    def test_us_decimal_with_thousands(self):
        assert parse_number("1,234.56") == pytest.approx(1234.56)

    def test_us_decimal_no_thousands(self):
        assert parse_number("1234.56") == pytest.approx(1234.56)

    def test_european_two_digit_decimal(self):
        assert parse_number("12,5") == pytest.approx(12.5)

    def test_european_thousands_only(self):
        assert parse_number("1.234") == pytest.approx(1234.0)

    def test_currency_suffix_eur(self):
        assert parse_number("19,99 EUR") == pytest.approx(19.99)

    def test_currency_prefix_euro_symbol(self):
        assert parse_number("€ 5") == pytest.approx(5.0)

    def test_invalid_string_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid number"):
            parse_number("abc")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="Empty value"):
            parse_number("")

    def test_nan_string_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid number"):
            parse_number("nan")


# ---------------------------------------------------------------------------
# read_table tests
# ---------------------------------------------------------------------------

class TestReadTable:
    def test_semicolon_csv(self):
        data = _csv_bytes("a;b;c\n1;2;3\n")
        df = read_table(data, "file.csv")
        assert list(df.columns) == ["a", "b", "c"]
        assert df.iloc[0].tolist() == ["1", "2", "3"]

    def test_comma_csv(self):
        data = _csv_bytes("a,b,c\n1,2,3\n")
        df = read_table(data, "file.csv")
        assert list(df.columns) == ["a", "b", "c"]
        assert df.iloc[0].tolist() == ["1", "2", "3"]

    def test_tab_csv(self):
        data = _csv_bytes("a\tb\tc\n1\t2\t3\n")
        df = read_table(data, "file.csv")
        assert list(df.columns) == ["a", "b", "c"]
        assert df.iloc[0].tolist() == ["1", "2", "3"]

    def test_cp1252_encoded_csv_with_umlauts(self):
        # cp1252 encoding of "Käse"
        text = "name\nK\u00e4se\n"
        data = text.encode("cp1252")
        df = read_table(data, "file.csv")
        assert df.iloc[0]["name"] == "K\u00e4se"

    def test_utf8_with_bom(self):
        text = "\ufeffa,b\n1,2\n"
        data = text.encode("utf-8")
        df = read_table(data, "file.csv")
        assert list(df.columns) == ["a", "b"]
        assert df.iloc[0].tolist() == ["1", "2"]

    def test_xlsx_basic(self):
        rows = [
            ["sku", "name", "price"],
            ["SKU1", "Widget", "9.99"],
        ]
        data = _xlsx_bytes(rows)
        df = read_table(data, "file.xlsx")
        assert list(df.columns) == ["sku", "name", "price"]
        assert df.iloc[0].tolist() == ["SKU1", "Widget", "9.99"]

    def test_xlsx_numeric_cell_stored_as_number(self):
        """Numeric cells in xlsx are read as numbers; read_table converts to str."""
        rows = [
            ["sku", "name", "qty"],
            ["SKU1", "Widget", 5],
        ]
        data = _xlsx_bytes(rows)
        df = read_table(data, "file.xlsx")
        # After normalization, values are strings
        assert df.iloc[0]["qty"] == "5"

    def test_xlsx_date_cell(self):
        """A real date cell in xlsx is read and converted to string."""
        rows = [
            ["order_date"],
            [date(2025, 3, 15)],
        ]
        data = _xlsx_bytes(rows)
        df = read_table(data, "file.xlsx")
        # openpyxl returns datetime objects; after str() conversion
        assert "2025-03-15" in df.iloc[0]["order_date"]

    def test_column_names_lowercased_and_stripped(self):
        data = _csv_bytes("  SKU ,  Name \nABC,Widget\n")
        df = read_table(data, "file.csv")
        assert list(df.columns) == ["sku", "name"]

    def test_empty_rows_dropped(self):
        data = _csv_bytes("a,b\n1,2\n\n3,4\n")
        df = read_table(data, "file.csv")
        assert len(df) == 2

    def test_pdf_raises_value_error(self):
        data = b"%PDF-1.4 fake pdf content"
        with pytest.raises(ValueError, match="Unsupported file type"):
            read_table(data, "file.pdf")

    def test_header_only_csv_raises_value_error(self):
        data = _csv_bytes("a,b,c\n")
        with pytest.raises(ValueError, match="The table is empty"):
            read_table(data, "file.csv")


# ---------------------------------------------------------------------------
# import_products tests
# ---------------------------------------------------------------------------

class TestImportProducts:
    def test_create_new_product(self, session: Session):
        df = pd.DataFrame({
            "sku": ["SKU001"],
            "name": ["Widget"],
            "price": ["9.99"],
            "category": ["Tools"],
            "stock_qty": ["100"],
            "low_stock_threshold": ["10"],
        })
        result = import_products(session, df)
        assert result.created == 1
        assert result.updated == 0
        assert result.ok

        product = session.scalar(select(Product).where(Product.sku == "SKU001"))
        assert product is not None
        assert product.name == "Widget"
        assert product.price == pytest.approx(9.99)
        assert product.category == "Tools"
        assert product.stock_qty == 100
        assert product.low_stock_threshold == 10

    def test_update_existing_product_by_sku(self, session: Session):
        # Create first
        df1 = pd.DataFrame({
            "sku": ["SKU001"],
            "name": ["Widget"],
            "price": ["9.99"],
        })
        import_products(session, df1)

        # Update
        df2 = pd.DataFrame({
            "sku": ["SKU001"],
            "name": ["Widget Pro"],
            "price": ["19.99"],
        })
        result = import_products(session, df2)
        assert result.created == 0
        assert result.updated == 1

        product = session.scalar(select(Product).where(Product.sku == "SKU001"))
        assert product.name == "Widget Pro"
        assert product.price == pytest.approx(19.99)

    def test_defaults_for_missing_optional_columns(self, session: Session):
        df = pd.DataFrame({
            "sku": ["SKU001"],
            "name": ["Widget"],
            "price": ["5.00"],
        })
        result = import_products(session, df)
        assert result.ok

        product = session.scalar(select(Product).where(Product.sku == "SKU001"))
        assert product.category == "Allgemein"
        assert product.stock_qty == 0
        assert product.low_stock_threshold == 10

    def test_missing_required_column_raises_value_error(self, session: Session):
        df = pd.DataFrame({
            "sku": ["SKU001"],
            "name": ["Widget"],
            # missing "price"
        })
        with pytest.raises(ValueError, match="Missing required columns.*price"):
            import_products(session, df)

    def test_invalid_rows_reported_with_spreadsheet_row_numbers(self, session: Session):
        df = pd.DataFrame({
            "sku": ["SKU001", "", "SKU003"],
            "name": ["Widget", "NoSku", "Gadget"],
            "price": ["9.99", "3", "abc"],
        })
        result = import_products(session, df)
        assert result.created == 1  # only SKU001 is valid
        assert len(result.errors) == 2
        # Row 3 (index 1) has missing sku
        assert any("Row 3" in e for e in result.errors)
        # Row 4 (index 2) has invalid price
        assert any("Row 4" in e for e in result.errors)

    def test_negative_price_rejected(self, session: Session):
        df = pd.DataFrame({
            "sku": ["SKU001"],
            "name": ["Widget"],
            "price": ["-5.00"],
        })
        result = import_products(session, df)
        assert result.created == 0
        assert any("negative price" in e for e in result.errors)

    def test_nan_price_rejected(self, session: Session):
        df = pd.DataFrame({
            "sku": ["SKU001"],
            "name": ["Widget"],
            "price": ["nan"],
        })
        result = import_products(session, df)
        assert result.created == 0
        assert any("invalid price" in e for e in result.errors)

    def test_invalid_stock_qty_rejected(self, session: Session):
        df = pd.DataFrame({
            "sku": ["SKU001"],
            "name": ["Widget"],
            "price": ["5.00"],
            "stock_qty": ["abc"],
        })
        result = import_products(session, df)
        assert result.created == 0
        assert any("invalid stock_qty" in e for e in result.errors)

    def test_low_stock_threshold_zero_is_kept(self, session: Session):
        df = pd.DataFrame({
            "sku": ["SKU001"],
            "name": ["Widget"],
            "price": ["5.00"],
            "low_stock_threshold": ["0"],
        })
        result = import_products(session, df)
        assert result.ok

        product = session.scalar(select(Product).where(Product.sku == "SKU001"))
        assert product.low_stock_threshold == 0


# ---------------------------------------------------------------------------
# import_customers tests
# ---------------------------------------------------------------------------

class TestImportCustomers:
    def test_email_lowercased_and_upsert_case_insensitive(self, session: Session):
        df1 = pd.DataFrame({
            "name": ["Alice"],
            "email": ["Alice@Example.com"],
            "city": ["Berlin"],
        })
        result1 = import_customers(session, df1)
        assert result1.created == 1

        # Same email, different case
        df2 = pd.DataFrame({
            "name": ["Alice Smith"],
            "email": ["alice@example.com"],
            "city": ["Munich"],
        })
        result2 = import_customers(session, df2)
        assert result2.updated == 1

        customer = session.scalar(select(Customer).where(Customer.email == "alice@example.com"))
        assert customer is not None
        assert customer.name == "Alice Smith"
        assert customer.city == "Munich"

    def test_invalid_email_reported(self, session: Session):
        df = pd.DataFrame({
            "name": ["Bob"],
            "email": ["not-an-email"],
        })
        result = import_customers(session, df)
        assert result.created == 0
        assert any("invalid email" in e for e in result.errors)


# ---------------------------------------------------------------------------
# import_orders tests
# ---------------------------------------------------------------------------

class TestImportOrders:
    def _setup_products_and_customer(self, session: Session):
        """Create a product and a customer for order tests."""
        session.add(Product(sku="SKU001", name="Widget", price=10.0, category="Tools",
                            stock_qty=100, low_stock_threshold=10))
        session.add(Customer(name="Alice", email="alice@example.com", city="Berlin",
                             created_at=pd.Timestamp.now()))
        session.commit()

    def test_two_lines_same_order_ref_become_one_order_with_correct_total(self, session: Session):
        self._setup_products_and_customer(session)
        today = date.today()
        df = pd.DataFrame({
            "order_ref": ["ORD-001", "ORD-001"],
            "order_date": [today.isoformat(), today.isoformat()],
            "customer_email": ["alice@example.com", "alice@example.com"],
            "sku": ["SKU001", "SKU001"],
            "qty": ["2", "3"],
        })
        result = import_orders(session, df)
        assert result.created == 1
        assert result.ok

        order = session.scalar(select(Order))
        assert order is not None
        assert order.total == pytest.approx(50.0)  # 10 * 2 + 10 * 3
        assert len(order.items) == 2

        invoice = session.scalar(select(Invoice))
        assert invoice is not None
        assert invoice.amount == pytest.approx(50.0)

    def test_invoice_status_open_for_recent_date(self, session: Session):
        self._setup_products_and_customer(session)
        today = date.today()
        df = pd.DataFrame({
            "order_ref": ["ORD-001"],
            "order_date": [today.isoformat()],
            "customer_email": ["alice@example.com"],
            "sku": ["SKU001"],
            "qty": ["1"],
        })
        result = import_orders(session, df)
        assert result.ok

        invoice = session.scalar(select(Invoice))
        assert invoice.status == "open"

    def test_invoice_status_paid_for_old_date(self, session: Session):
        self._setup_products_and_customer(session)
        old_date = date.today() - timedelta(days=100)
        df = pd.DataFrame({
            "order_ref": ["ORD-001"],
            "order_date": [old_date.isoformat()],
            "customer_email": ["alice@example.com"],
            "sku": ["SKU001"],
            "qty": ["1"],
        })
        result = import_orders(session, df)
        assert result.ok

        invoice = session.scalar(select(Invoice))
        assert invoice.status == "paid"

    def test_unknown_sku_rejects_whole_order(self, session: Session):
        self._setup_products_and_customer(session)
        today = date.today()
        df = pd.DataFrame({
            "order_ref": ["ORD-001", "ORD-002"],
            "order_date": [today.isoformat(), today.isoformat()],
            "customer_email": ["alice@example.com", "alice@example.com"],
            "sku": ["UNKNOWN", "SKU001"],
            "qty": ["1", "1"],
        })
        result = import_orders(session, df)
        assert result.created == 1  # Only ORD-002
        assert any("unknown sku" in e for e in result.errors)

        orders = session.scalars(select(Order)).all()
        assert len(orders) == 1
        assert orders[0].total == pytest.approx(10.0)

    def test_unknown_customer_rejected(self, session: Session):
        self._setup_products_and_customer(session)
        today = date.today()
        df = pd.DataFrame({
            "order_ref": ["ORD-001"],
            "order_date": [today.isoformat()],
            "customer_email": ["unknown@example.com"],
            "sku": ["SKU001"],
            "qty": ["1"],
        })
        result = import_orders(session, df)
        assert result.created == 0
        assert any("unknown customer" in e for e in result.errors)

    def test_mixed_customers_in_one_order_ref_rejected(self, session: Session):
        self._setup_products_and_customer(session)
        session.add(Customer(name="Bob", email="bob@example.com", city="Hamburg",
                             created_at=pd.Timestamp.now()))
        session.commit()
        today = date.today()
        df = pd.DataFrame({
            "order_ref": ["ORD-001", "ORD-001"],
            "order_date": [today.isoformat(), today.isoformat()],
            "customer_email": ["alice@example.com", "bob@example.com"],
            "sku": ["SKU001", "SKU001"],
            "qty": ["1", "1"],
        })
        result = import_orders(session, df)
        assert result.created == 0
        assert any("one customer" in e for e in result.errors)

    def test_dd_mm_yyyy_dates_accepted(self, session: Session):
        self._setup_products_and_customer(session)
        df = pd.DataFrame({
            "order_ref": ["ORD-001"],
            "order_date": ["15.03.2025"],
            "customer_email": ["alice@example.com"],
            "sku": ["SKU001"],
            "qty": ["1"],
        })
        result = import_orders(session, df)
        assert result.ok

        order = session.scalar(select(Order))
        assert order.order_date == date(2025, 3, 15)

    def test_qty_zero_rejected(self, session: Session):
        self._setup_products_and_customer(session)
        today = date.today()
        df = pd.DataFrame({
            "order_ref": ["ORD-001"],
            "order_date": [today.isoformat()],
            "customer_email": ["alice@example.com"],
            "sku": ["SKU001"],
            "qty": ["0"],
        })
        result = import_orders(session, df)
        assert result.created == 0
        assert any("invalid qty" in e for e in result.errors)
