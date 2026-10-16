"""German/English UI strings. Use t(lang, key)."""
STRINGS = {
    "de": {
        "title": "Geschäfts-Dashboard", "language": "Sprache", "date_range": "Zeitraum",
        "granularity": "Auflösung", "day": "Tag", "week": "Woche", "month": "Monat",
        "revenue": "Umsatz", "orders": "Bestellungen", "avg_order_value": "Ø Bestellwert",
        "new_customers": "Neukunden", "returning_customers": "Bestandskunden",
        "revenue_over_time": "Umsatzverlauf", "top_products": "Top-Produkte",
        "top_customers": "Top-Kunden", "open_invoices": "Offene & überfällige Rechnungen",
        "vs_previous": "ggü. Vorperiode", "name": "Name", "units": "Stück",
        "invoice": "Rechnung", "due_date": "Fällig am", "amount": "Betrag", "status": "Status",
        "open": "offen", "overdue": "überfällig", "no_data": "Keine Daten im Zeitraum",
        "no_db": "Keine Datenbank gefunden. Bitte zuerst `python -m scripts.seed` ausführen.",
    },
    "en": {
        "title": "Business Dashboard", "language": "Language", "date_range": "Date range",
        "granularity": "Granularity", "day": "Day", "week": "Week", "month": "Month",
        "revenue": "Revenue", "orders": "Orders", "avg_order_value": "Avg. order value",
        "new_customers": "New customers", "returning_customers": "Returning customers",
        "revenue_over_time": "Revenue over time", "top_products": "Top products",
        "top_customers": "Top customers", "open_invoices": "Open & overdue invoices",
        "vs_previous": "vs. previous period", "name": "Name", "units": "Units",
        "invoice": "Invoice", "due_date": "Due date", "amount": "Amount", "status": "Status",
        "open": "open", "overdue": "overdue", "no_data": "No data in range",
        "no_db": "No database found. Run `python -m scripts.seed` first.",
    },
}


def t(lang: str, key: str) -> str:
    return STRINGS[lang][key]
