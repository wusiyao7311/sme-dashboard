import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

DEFAULT_URL = "sqlite:///demo.db"


def get_engine(url: str = "") -> Engine:
    return create_engine(url or os.getenv("DATABASE_URL", DEFAULT_URL))
