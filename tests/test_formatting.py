import pytest

from app.formatting import format_eur


@pytest.mark.parametrize(
    "value, lang, decimals, expected",
    [
        (12345.6, "de", 2, "12.345,60 EUR"),
        (12345.6, "en", 2, "12,345.60 EUR"),
        (6072.534, "de", 2, "6.072,53 EUR"),
        (97772.45, "de", 0, "97.772 EUR"),
        (0, "de", 2, "0,00 EUR"),
        (-1234.5, "de", 2, "-1.234,50 EUR"),
        (1234567.891, "de", 2, "1.234.567,89 EUR"),
    ],
)
def test_format_eur(value, lang, decimals, expected):
    assert format_eur(value, lang, decimals) == expected
