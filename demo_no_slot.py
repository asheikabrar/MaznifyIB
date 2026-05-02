"""Demo helper — sets up data so the planner shows a 'no slots today' warning.

Run:
  .\.venv\Scripts\python.exe demo_no_slot.py setup    # block today + seed reviews
  .\.venv\Scripts\python.exe demo_no_slot.py teardown # remove demo data
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta

from app.db import SessionLocal
from app.models import AvailabilityException, Subject, Topic
from app import planner, scheduler

DEMO_NOTE = "DEMO no-slot day"
DEMO_SUBJECTS = ("Biology", "Chemistry", "Math AA")


def setup() -> None:
    with SessionLocal() as db:
        today = date.today()

        # 1) Wipe existing demo blocks for today
        db.query(AvailabilityException).filter_by(
            on_date=today, note=DEMO_NOTE
        ).delete()

        # 2) Block the whole day
        db.add(
            AvailabilityException(
                on_date=today, is_blocked=True, note=DEMO_NOTE
            )
        )
        db.flush()

        # 3) Seed first not-yet-studied top-level topic from each subject as due today
        seeded: list[tuple[str, str, str]] = []
        for sname in DEMO_SUBJECTS:
            s = db.query(Subject).filter_by(name=sname).first()
            if not s:
                continue
            for t in sorted(s.topics, key=lambda x: (x.code or "", x.title)):
                if t.parent_id is None and not t.completed_on and not t.state:
                    scheduler.seed_completed_topic(
                        t,
                        datetime.combine(today - timedelta(days=10), time(12, 0)),
                        "shaky",
                    )
                    # force due = today so they show up immediately
                    t.due = datetime.combine(today, time(0, 0))
                    seeded.append((s.name, t.code or "", t.title))
                    break

        db.commit()

        print("=== Demo set up ===")
        print(f"Date:           {today.strftime('%a %d %b %Y')}")
        print(f"Blocked: whole day  (note: '{DEMO_NOTE}')")
        print()
        print("Seeded topics now due TODAY:")
        for sname, code, ti in seeded:
            print(f"  - {sname}: {code} {ti}".rstrip())

        plan = planner.build_plan(db, today)
        print()
        print(f"Slots:       {len(plan.slots)}")
        print(f"Plan items:  {len(plan.items)}")
        print(f"Unscheduled: {len(plan.unscheduled)}")
        print()
        print("Planner warnings (these render in the dashboard 'Heads up' card):")
        for w in plan.warnings:
            print(f"  WARNING: {w}")
        print()
        print("Open in browser:")
        print("  http://127.0.0.1:8000/         (Today page)")
        print("  http://127.0.0.1:8000/dashboard")
        print()
        print("Run teardown to revert:  python demo_no_slot.py teardown")


def teardown() -> None:
    with SessionLocal() as db:
        today = date.today()
        n = db.query(AvailabilityException).filter_by(
            on_date=today, note=DEMO_NOTE
        ).delete()

        # Reset the seeded topics back to "not studied"
        cleared = 0
        for sname in DEMO_SUBJECTS:
            s = db.query(Subject).filter_by(name=sname).first()
            if not s:
                continue
            for t in s.topics:
                if t.due and t.due.date() == today and t.reps == 1 and t.initial_recall == "shaky":
                    t.state = 0
                    t.step = 0
                    t.stability = 0.0
                    t.difficulty = 0.0
                    t.reps = 0
                    t.lapses = 0
                    t.last_review = None
                    t.due = None
                    t.completed_on = None
                    t.initial_recall = None
                    cleared += 1
        db.commit()
        print(f"Removed {n} demo override(s); cleared {cleared} seeded topic(s).")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "setup"
    if cmd == "setup":
        setup()
    elif cmd == "teardown":
        teardown()
    else:
        print("Usage: python demo_no_slot.py [setup|teardown]")
        sys.exit(1)
