from __future__ import annotations

import io
from datetime import date, datetime

import pandas as pd
import streamlit as st

from app.bootstrap import ensure_demo_data
from app.db import get_engine
from app.importer import (
    ImportResult,
    import_customers,
    import_orders,
    import_products,
    read_table,
)
from app.datev import build_datev_csv, load_invoices_for_export
from sqlalchemy.orm import Session

st.set_page_config(page_title="Data", layout="wide")
st.cache_resource(ensure_demo_data)()

STRINGS = {
    "de": {
        "title": "Daten",
        "tab_import": "Import",
        "tab_export": "DATEV-Export",
        "select_type": "Was importieren?",
        "products": "Produkte",
        "customers": "Kunden",
        "orders": "Bestellungen",
        "upload_file": "Datei hochladen (CSV oder XLSX)",
        "preview": "Vorschau (erste 10 Zeilen)",
        "btn_import": "Importieren",
        "btn_export": "Export erstellen",
        "success_import": "Import erfolgreich: {created} erstellt, {updated} aktualisiert.",
        "warning_errors": "{count} Fehler aufgetreten.",
        "error_expander": "Fehlerdetails",
        "more_errors": "… und {n} weitere.",
        "caption_required": "Erforderliche Spalten: {cols}",
        "caption_optional": "Optionale Spalten: {cols}",
        "download_template": "Vorlage herunterladen",
        "download_export": "DATEV-Datei herunterladen",
        "date_from": "Von",
        "date_to": "Bis",
        "consultant_no": "Beraternummer",
        "client_no": "Kundennummer",
        "revenue_account": "Erlöskonto",
        "include_paid": "Bezahlte Rechnungen einbeziehen",
        "info_no_invoices": "Keine Rechnungen im gewählten Zeitraum gefunden.",
        "success_export": "Export erstellt: {count} Rechnungen.",
        "caption_datev": "Prüfen Sie die Kontonummern (SKR03) mit Ihrem Steuerberater, bevor Sie in DATEV importieren.",
        "error_invalid_date_range": "Das Startdatum muss vor dem Enddatum liegen.",
        "error_read_file": "Datei konnte nicht gelesen werden: {msg}",
        "error_import": "Import fehlgeschlagen: {msg}",
        "error_export": "Export fehlgeschlagen: {msg}",
    },
    "en": {
        "title": "Data",
        "tab_import": "Import",
        "tab_export": "DATEV Export",
        "select_type": "What to import?",
        "products": "Products",
        "customers": "Customers",
        "orders": "Orders",
        "upload_file": "Upload file (CSV or XLSX)",
        "preview": "Preview (first 10 rows)",
        "btn_import": "Import",
        "btn_export": "Create export",
        "success_import": "Import successful: {created} created, {updated} updated.",
        "warning_errors": "{count} errors occurred.",
        "error_expander": "Error details",
        "more_errors": "… and {n} more.",
        "caption_required": "Required columns: {cols}",
        "caption_optional": "Optional columns: {cols}",
        "download_template": "Download template",
        "download_export": "Download DATEV file",
        "date_from": "From",
        "date_to": "To",
        "consultant_no": "Consultant number",
        "client_no": "Client number",
        "revenue_account": "Revenue account",
        "include_paid": "Include paid invoices",
        "info_no_invoices": "No invoices found in the selected period.",
        "success_export": "Export created: {count} invoices.",
        "caption_datev": "Review the account numbers (SKR03) with your tax advisor before importing into DATEV.",
        "error_invalid_date_range": "Start date must be before end date.",
        "error_read_file": "Could not read file: {msg}",
        "error_import": "Import failed: {msg}",
        "error_export": "Export failed: {msg}",
    },
}

REQUIRED_COLUMNS = {
    "products": ["sku", "name", "price"],
    "customers": ["name", "email"],
    "orders": ["order_ref", "order_date", "customer_email", "sku", "qty"],
}

OPTIONAL_COLUMNS = {
    "products": ["category", "stock_qty", "low_stock_threshold"],
    "customers": ["city"],
    "orders": [],
}

IMPORT_FUNCTIONS = {
    "products": import_products,
    "customers": import_customers,
    "orders": import_orders,
}


def get_strings(lang: str) -> dict:
    return STRINGS.get(lang, STRINGS["de"])


def get_template_csv(key: str) -> bytes:
    required = REQUIRED_COLUMNS[key]
    optional = OPTIONAL_COLUMNS[key]
    header = ";".join(required + optional)
    return (header + "\n").encode("utf-8")


def render_import_tab(t: dict, lang: str) -> None:
    options = [t["products"], t["customers"], t["orders"]]
    keys = ["products", "customers", "orders"]
    selected_label = st.selectbox(t["select_type"], options, index=0)
    selected_key = keys[options.index(selected_label)]

    st.caption(t["caption_required"].format(cols=", ".join(REQUIRED_COLUMNS[selected_key])))
    if OPTIONAL_COLUMNS[selected_key]:
        st.caption(t["caption_optional"].format(cols=", ".join(OPTIONAL_COLUMNS[selected_key])))

    st.download_button(
        t["download_template"],
        data=get_template_csv(selected_key),
        file_name=f"template_{selected_key}.csv",
        mime="text/csv",
    )

    uploaded = st.file_uploader(t["upload_file"], type=["csv", "xlsx"])
    if uploaded is None:
        return

    try:
        df = read_table(uploaded.getvalue(), uploaded.name)
    except ValueError as e:
        st.error(t["error_read_file"].format(msg=str(e)))
        return

    st.subheader(t["preview"])
    st.dataframe(df.head(10), width="stretch")

    if st.button(t["btn_import"], key="btn_import"):
        import_func = IMPORT_FUNCTIONS[selected_key]
        try:
            with Session(get_engine()) as session:
                result: ImportResult = import_func(session, df)
        except ValueError as e:
            st.error(t["error_import"].format(msg=str(e)))
            return

        st.success(t["success_import"].format(created=result.created, updated=result.updated))
        if result.errors:
            st.warning(t["warning_errors"].format(count=len(result.errors)))
            with st.expander(t["error_expander"]):
                display_errors = result.errors[:50]
                for err in display_errors:
                    st.write(err)
                remaining = len(result.errors) - 50
                if remaining > 0:
                    st.write(t["more_errors"].format(n=remaining))


def render_export_tab(t: dict, lang: str) -> None:
    today = date.today()
    default_from = date(today.year, 1, 1)
    default_to = today

    date_from = st.date_input(t["date_from"], value=default_from)
    date_to = st.date_input(t["date_to"], value=default_to)

    if date_from > date_to:
        st.error(t["error_invalid_date_range"])
        st.stop()

    consultant_no = st.number_input(t["consultant_no"], value=1001, min_value=1, step=1)
    client_no = st.number_input(t["client_no"], value=1, min_value=1, step=1)
    revenue_account = st.number_input(t["revenue_account"], value=8400, min_value=1, step=1)
    include_paid = st.checkbox(t["include_paid"], value=True)

    params = (date_from, date_to, consultant_no, client_no, revenue_account, include_paid)
    if st.button(t["btn_export"], key="btn_export"):
        try:
            with Session(get_engine()) as session:
                invoices = load_invoices_for_export(
                    session,
                    date_from,
                    date_to,
                    include_paid=include_paid,
                )
        except ValueError as e:
            st.error(t["error_export"].format(msg=str(e)))
            return

        if not invoices:
            st.info(t["info_no_invoices"])
            return

        try:
            csv_bytes = build_datev_csv(
                invoices,
                date_from,
                date_to,
                consultant_no=consultant_no,
                client_no=client_no,
                revenue_account=revenue_account,
            )
        except ValueError as e:
            st.error(t["error_export"].format(msg=str(e)))
            return

        st.session_state["datev_export"] = (params, csv_bytes)
        st.success(t["success_export"].format(count=len(invoices)))

    saved = st.session_state.get("datev_export")
    if saved and saved[0] == params:  # hide a stale file once any input changed
        filename = f"EXTF_Buchungsstapel_{date_from.isoformat()}_{date_to.isoformat()}.csv"
        st.download_button(
            t["download_export"],
            data=saved[1],
            file_name=filename,
            mime="text/csv",
        )

    st.caption(t["caption_datev"])


def main() -> None:
    lang = st.session_state.get("lang", "de")
    t = get_strings(lang)

    st.title(t["title"])

    tab_import, tab_export = st.tabs([t["tab_import"], t["tab_export"]])

    with tab_import:
        render_import_tab(t, lang)

    with tab_export:
        render_export_tab(t, lang)


main()
