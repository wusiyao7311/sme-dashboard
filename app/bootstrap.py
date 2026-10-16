"""Create demo data on first start, so a fresh deploy (empty SQLite file) works without any login or setup."""
from sqlalchemy import inspect, text

from app.db import get_engine


def ensure_demo_data() -> bool:
    """Seed the database if it has no products. Returns True when it seeded."""
    engine = get_engine()
    if inspect(engine).has_table("products"):
        with engine.connect() as conn:
            if conn.execute(text("SELECT COUNT(*) FROM products")).scalar_one() > 0:
                return False
    from scripts.seed import main as seed

    seed()
    return True
