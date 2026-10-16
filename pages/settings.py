from __future__ import annotations

import re
from datetime import date

import streamlit as st
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Setting
from app.automations import (
    get_settings,
    run_summary,
    run_low_stock_alert,
    run_payment_reminders,
)
from app.i18n import t

st.set_page_config(page_title="Settings", layout="wide")

STRINGS = {
    "de": {
        "title": "Einstellungen",
        "recipients": "Empfänger (kommagetrennt)",
        "recipients_help": "E-Mail-Adressen, getrennt durch Kommas.",
        "schedule": "Zusammenfassung-Planung",
        "daily": "Täglich",
        "weekly": "Wöchentlich",
        "low_stock_threshold": "Standard-Schwelle für niedrigen Bestand",
        "reminder_interval": "Intervall für Zahlungserinnerungen (Tage)",
        "save": "Speichern",
        "saved": "Einstellungen gespeichert.",
        "invalid_email": "Ungültige E-Mail-Adresse: {email}",
        "actions": "Aktionen ausführen",
        "send_summary": "Zusammenfassung senden",
        "send_low_stock": "Warnung bei niedrigem Bestand senden",
        "send_reminders": "Zahlungserinnerungen senden",
        "sent_n_emails": "{n} E-Mails gesendet.",
        "low_stock_done": "Warnung gesendet ({n} Produkte).",
        "outbox_note": "Ohne SMTP-Konfiguration werden E-Mails in den Ordner ./outbox geschrieben.",
    },
    "en": {
        "title": "Settings",
        "recipients": "Recipients (comma separated)",
        "recipients_help": "Email addresses separated by commas.",
        "schedule": "Summary schedule",
        "daily": "Daily",
        "weekly": "Weekly",
        "low_stock_threshold": "Default low stock threshold",
        "reminder_interval": "Payment reminder interval (days)",
        "save": "Save",
        "saved": "Settings saved.",
        "invalid_email": "Invalid email address: {email}",
        "actions": "Run actions",
        "send_summary": "Send summary",
        "send_low_stock": "Send low stock alert",
        "send_reminders": "Send payment reminders",
        "sent_n_emails": "{n} emails sent.",
        "low_stock_done": "Alert sent ({n} products).",
        "outbox_note": "Without SMTP configuration emails are written to the ./outbox folder.",
    },
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_strings(lang: str) -> dict[str, str]:
    return STRINGS.get(lang, STRINGS["de"])


def load_settings() -> dict[str, str]:
    engine = get_engine()
    with Session(engine) as session:
        return get_settings(session)


def save_settings(values: dict[str, str]) -> None:
    engine = get_engine()
    with Session(engine) as session:
        for key, value in values.items():
            session.merge(Setting(key=key, value=str(value)))
        session.commit()


def validate_recipients(raw: str) -> bool:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return bool(parts) and all(EMAIL_RE.match(p) for p in parts)


def run_action(func, today: date, lang: str, message_key: str = "sent_n_emails") -> None:
    engine = get_engine()
    try:
        with Session(engine) as session:
            count = func(session, today)
        st.success(get_strings(lang)[message_key].format(n=count))
    except Exception as exc:
        st.error(str(exc))


def main() -> None:
    lang = st.session_state.get("lang", "de")
    s = get_strings(lang)
    st.title(s["title"])

    current = load_settings()
    with st.form("settings_form"):
        recipients = st.text_input(
            s["recipients"],
            value=current.get("summary_email_recipients", ""),
            help=s["recipients_help"],
        )
        schedule = st.selectbox(
            s["schedule"],
            options=["daily", "weekly"],
            index=0 if current.get("summary_schedule", "daily") == "daily" else 1,
            format_func=lambda v: s[v],
        )
        threshold = st.number_input(
            s["low_stock_threshold"],
            min_value=0,
            value=int(current.get("default_low_stock_threshold", "5")),
        )
        interval = st.number_input(
            s["reminder_interval"],
            min_value=1,
            value=int(current.get("reminder_interval_days", "7")),
        )
        submitted = st.form_submit_button(s["save"])

    if submitted:
        if not validate_recipients(recipients):
            if not recipients.strip():
                st.error(s["invalid_email"].format(email="-"))
            for part in [p.strip() for p in recipients.split(",") if p.strip()]:
                if not EMAIL_RE.match(part):
                    st.error(s["invalid_email"].format(email=part))
        else:
            save_settings(
                {
                    "summary_email_recipients": recipients,
                    "summary_schedule": schedule,
                    "default_low_stock_threshold": str(threshold),
                    "reminder_interval_days": str(interval),
                }
            )
            st.success(s["saved"])

    st.subheader(s["actions"])
    today = date.today()
    if st.button(s["send_summary"]):
        run_action(run_summary, today, lang)
    if st.button(s["send_low_stock"]):
        run_action(run_low_stock_alert, today, lang, "low_stock_done")
    if st.button(s["send_reminders"]):
        run_action(run_payment_reminders, today, lang)

    st.caption(s["outbox_note"])


main()
