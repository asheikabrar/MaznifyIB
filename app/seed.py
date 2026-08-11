"""Seed initial data: the student's 6 subjects and her weekly availability.

Run: python -m app.seed
"""
from __future__ import annotations

from datetime import time

from sqlalchemy import select

from app.curriculum import CURRICULA
from app.db import Base, SessionLocal, engine
from app.models import AvailabilityRule, Subject, Topic

# sort_order controls the grid layout on Today / Plan (cards flow left→right).
# With lg:grid-cols-6, first 6 are row 1; remainder is row 2.
SUBJECTS = [
    # Row 1 — academic subjects (Math first per request)
    ("Math AA",              "SL",   "#6366f1", "📐",  10),
    ("Biology",              "HL",   "#10b981", "🧬",  20),
    ("Chemistry",            "SL",   "#06b6d4", "⚗️",  30),
    ("English Lang & Lit",   "HL",   "#f59e0b", "📖",  40),
    ("Visual Arts",          "SL",   "#f472b6", "🎨",  45),
    ("Business Management",  "HL",   "#ec4899", "💼",  50),
    ("Arabic ab initio",     "SL",   "#84cc16", "🕌",  60),
    # Row 2 — IB core components (CAS second-row per request)
    ("Extended Essay",       "Core", "#8b5cf6", "📜", 110),
    ("Theory of Knowledge",  "Core", "#0ea5e9", "🧠", 120),
    ("CAS",                  "Core", "#22c55e", "🤝", 130),
    # Row 3 — Admissions test
    ("UCAT",                 "Test", "#f43f5e", "🩺", 200),
]

# Mon=0..Sun=6. Mon–Fri 5–7am + 17:30–19:30; Sat–Sun 5–7am.
AVAILABILITY = [
    *[(wd, time(5, 0), time(7, 0)) for wd in range(0, 5)],
    *[(wd, time(17, 30), time(19, 30)) for wd in range(0, 5)],
    (5, time(5, 0), time(7, 0)),
    (6, time(5, 0), time(7, 0)),
]


def run() -> None:
    """Idempotent seed: ensures shared subjects exist and refreshes their
    level/icon/sort_order. Per-user topics and availability are provisioned
    when a user is created (see app.auth.provision_user_workspace).
    """
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        existing = {s.name: s for s in db.scalars(select(Subject)).all()}
        added_subjects = 0
        for name, level, color, icon, sort_order in SUBJECTS:
            if name in existing:
                s = existing[name]
                if not (s.icon or "").strip():
                    s.icon = icon
                s.level = level
                s.sort_order = sort_order
                continue
            db.add(
                Subject(
                    name=name, level=level, color=color, icon=icon, sort_order=sort_order
                )
            )
            added_subjects += 1
        db.commit()
        print(
            f"Seed complete. Added {added_subjects} new subject(s); "
            f"existing rows refreshed."
        )


if __name__ == "__main__":
    run()
