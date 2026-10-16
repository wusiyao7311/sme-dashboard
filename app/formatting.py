"""Locale-aware number formatting shared by the dashboard and the emails."""


def format_eur(value: float, lang: str, decimals: int = 2) -> str:
    """12345.6 -> '12.345,60 EUR' (de) or '12,345.60 EUR' (en)."""
    text = f"{value:,.{decimals}f}"
    if lang == "de":
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return f"{text} EUR"
