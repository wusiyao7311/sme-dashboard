# SME Business Dashboard

**Stop building reports by hand.** One dashboard for your orders, invoices and customers, with automated summaries and reminders (automations coming in week 3).

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional, defaults to SQLite demo.db
python -m scripts.seed          # generates 12 months of fake demo data
streamlit run streamlit_app.py  # open http://localhost:8501
pytest                          # KPI tests
```

## Status
Week 1 scaffold: schema, seed script, KPI functions with tests, first dashboard (KPI cards, revenue chart, top tables, open invoices, DE/EN).
