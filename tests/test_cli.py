from datetime import date

import pytest
from sqlalchemy.orm import Session

from app import bootstrap
from app.models import Setting
from scripts import run_automations


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'demo.db'}")
    monkeypatch.setattr("app.mailer.OUTBOX", tmp_path / "outbox")
    assert bootstrap.ensure_demo_data() is True
    return tmp_path


def test_ensure_demo_data_seeds_once(seeded_db):
    assert bootstrap.ensure_demo_data() is False


def test_daily_job_sends_low_stock_and_reminders_to_outbox(seeded_db):
    code = run_automations.main(["daily", "--today", date.today().isoformat()])
    assert code == 0
    assert len(list((seeded_db / "outbox").glob("*.eml"))) > 1


def test_weekly_job_skipped_when_schedule_is_daily(seeded_db):
    with Session(run_automations.get_engine()) as s:
        s.merge(Setting(key="summary_schedule", value="daily"))
        s.commit()
    assert run_automations.main(["weekly"]) == 0
    assert not (seeded_db / "outbox").exists()


def test_failing_job_gives_exit_code_1(seeded_db, monkeypatch):
    def boom(session, today):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(run_automations, "run_summary", boom)
    assert run_automations.main(["summary"]) == 1
