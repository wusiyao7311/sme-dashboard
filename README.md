# SME Business Dashboard

**Stop building reports by hand.** One dashboard for your orders, invoices and customers, with automated summaries and reminders.

👉 **[Live demo](https://sme-dashboard-cl9flxpzsuqyssqtymdxrc.streamlit.app/)** (fake data, no login)

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional, defaults to SQLite demo.db
python -m scripts.seed          # generates 12 months of fake demo data
streamlit run streamlit_app.py  # open http://localhost:8501
pytest                          # KPI tests
```

## Data import and DATEV export
- **Import** CSV or Excel (products, customers, orders) on the *Data* page. Examples in `sample_data/`. Re-importing orders creates duplicates (no order reference is stored).
- **DATEV export**: Buchungsstapel CSV (EXTF 700) for open and paid invoices, debtor account = 10000 + customer id, revenue account 8400 (SKR03). Have your tax advisor check the account numbers before importing.

## Automations on a schedule
`python -m scripts.run_automations daily|weekly|summary|low-stock|reminders` runs the jobs; `.github/workflows/automations.yml` runs them via GitHub Actions cron (daily 07:00 UTC, weekly summary Mondays 06:00 UTC). Add the repository secrets `DATABASE_URL` (PostgreSQL), `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`. Without `SMTP_HOST`, emails are written to `./outbox`.

## Deploy the live demo (Streamlit Community Cloud)
1. Push this repo to GitHub (public).
2. On share.streamlit.io choose *New app*, pick the repo, branch `main`, main file `streamlit_app.py`, Python 3.11.
3. No secrets needed: on first start the app creates a SQLite file with fake demo data. It is reset whenever the app restarts.

## GDPR notes
The demo contains only fake data. For real customer data use an EU-hosted PostgreSQL (e.g. Neon or Supabase in Frankfurt) and an EU email provider, and sign a data processing agreement (AVV) with each provider.

## Features
- Dashboard: KPI cards with change vs. previous period, revenue chart (day/week/month), top products and customers, open and overdue invoices
- Automations: weekly or daily summary email, low-stock alert, payment reminders, settings page
- CSV/Excel import, DATEV export, German and English UI
- Tests: `pytest` (92 tests)

## Stack
Python 3.9+, Streamlit, SQLAlchemy (SQLite demo, PostgreSQL production), pandas, Plotly, GitHub Actions.

## License
MIT
