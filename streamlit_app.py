"""Entry point: sets up the sidebar navigation. Each page lives in its own file."""
import streamlit as st

pages = [
    st.Page("dashboard.py", title="Dashboard", icon="📊", default=True),
    st.Page("pages/data.py", title="Daten / Data", icon="📥", url_path="data"),
    st.Page("pages/settings.py", title="Einstellungen / Settings", icon="⚙️", url_path="settings"),
]
st.navigation(pages).run()
