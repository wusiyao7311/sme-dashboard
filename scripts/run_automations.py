from __future__ import annotations

import argparse
import logging
from datetime import date
from typing import Callable

from app.automations import get_settings, run_summary, run_low_stock_alert, run_payment_reminders
from app.db import get_engine
from sqlalchemy.orm import Session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run automation jobs.")
    parser.add_argument(
        "job",
        choices=["summary", "low-stock", "reminders", "daily", "weekly"],
        help="Job to run.",
    )
    parser.add_argument(
        "--today",
        type=lambda s: date.fromisoformat(s),
        default=date.today(),
        help="Override today's date (YYYY-MM-DD).",
    )
    return parser.parse_args(argv)


def run_job(
    session: Session,
    today: date,
    job_name: str,
    func: Callable[[Session, date], int],
    failures: list[str],
) -> None:
    try:
        count = func(session, today)
        logger.info("%s returned %d", job_name, count)
    except Exception:
        logger.exception("Job %s failed", job_name)
        session.rollback()  # keep the session usable for the next job
        failures.append(job_name)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    today = args.today
    failures: list[str] = []

    with Session(get_engine()) as session:
        settings = get_settings(session)

        if args.job == "summary":
            run_job(session, today, "summary", run_summary, failures)

        elif args.job == "low-stock":
            run_job(session, today, "low-stock", run_low_stock_alert, failures)

        elif args.job == "reminders":
            run_job(session, today, "reminders", run_payment_reminders, failures)

        elif args.job == "daily":
            run_job(session, today, "low-stock", run_low_stock_alert, failures)
            run_job(session, today, "reminders", run_payment_reminders, failures)
            if settings["summary_schedule"] == "daily":
                run_job(session, today, "summary", run_summary, failures)

        elif args.job == "weekly":
            if settings["summary_schedule"] == "weekly":
                run_job(session, today, "summary", run_summary, failures)
            else:
                logger.info("Weekly summary skipped (summary_schedule is not 'weekly')")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
