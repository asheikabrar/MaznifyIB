"""Minimal username/password auth using stdlib (no extra deps).

- Passwords stored as `pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`.
- Session is a signed cookie holding the user id (itsdangerous-style HMAC).
- Login required for everything except /login and static assets.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Optional

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User

PBKDF2_ITER = 200_000
SESSION_COOKIE = "studymate_session"
_settings = get_settings()


def _secret() -> bytes:
    """Use APP_SECRET if set; else derive a stable secret from the DB URL.

    Good enough for a single-user / family deploy. For production set APP_SECRET.
    """
    s = os.environ.get("APP_SECRET") or _settings.database_url + "::studymate"
    return s.encode("utf-8")


# ---------- password hashing ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITER)
    return f"pbkdf2_sha256${PBKDF2_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
    )
    return hmac.compare_digest(dk.hex(), hash_hex)


# ---------- session cookie ----------

def _sign(value: str) -> str:
    sig = hmac.new(_secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}.{sig}"


def _unsign(token: str) -> Optional[str]:
    if not token or "." not in token:
        return None
    value, sig = token.rsplit(".", 1)
    expected = hmac.new(_secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    return value


def make_session_token(user_id: int) -> str:
    return _sign(str(user_id))


def read_session_user_id(request: Request) -> Optional[int]:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    val = _unsign(raw)
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def get_current_user(request: Request, db: Session) -> Optional[User]:
    uid = read_session_user_id(request)
    if not uid:
        return None
    return db.get(User, uid)


# ---------- bootstrap ----------

def ensure_admin_user(db: Session) -> User:
    """Make sure an admin/admin user exists (default credentials)."""
    user = db.scalar(select(User).where(User.username == "admin"))
    if user:
        return user
    user = User(
        username="admin",
        display_name="Administrator",
        email="",
        password_hash=hash_password("admin"),
        is_admin=True,
    )
    db.add(user)
    db.commit()
    provision_user_workspace(db, user)
    return user


def provision_user_workspace(db: Session, user: User) -> int:
    """Create or top up per-user starter data: default curriculum + availability.

    Idempotent and safe to re-run:
      - For each (subject, curriculum entry), inserts a top-level Topic if the
        user doesn't already have one with that (code, title) under that subject.
      - Per-user notes, sub-units, and FSRS state are preserved across re-runs.
      - Default availability is only added when the user has none.

    Returns the number of new topics added.
    """
    from app.curriculum import CURRICULA  # local import to avoid cycles
    from app.models import (
        AvailabilityRule,
        Subject,
        Topic,
    )
    from datetime import time as dtime

    # Build a {subject_name: subject} lookup
    subjects = {s.name: s for s in db.scalars(select(Subject)).all()}

    # Existing curriculum keys this user already has, per subject.
    existing_keys: dict[int, set[tuple[str, str]]] = {}
    for t in db.scalars(
        select(Topic).where(Topic.owner_id == user.id, Topic.parent_id.is_(None))
    ).all():
        existing_keys.setdefault(t.subject_id, set()).add(
            ((t.code or "").strip(), (t.title or "").strip().lower())
        )

    added = 0
    for subj_name, entries in CURRICULA.items():
        subj = subjects.get(subj_name)
        if not subj:
            continue
        existing = existing_keys.get(subj.id, set())
        for code, title, weight in entries:
            key = ((code or "").strip(), (title or "").strip().lower())
            if key in existing:
                continue
            db.add(
                Topic(
                    owner_id=user.id,
                    subject_id=subj.id,
                    code=code,
                    title=title,
                    ib_weight=weight,
                )
            )
            existing.add(key)
            added += 1

    # Default availability if the user has none.
    has_avail = db.scalar(
        select(AvailabilityRule.id).where(AvailabilityRule.owner_id == user.id).limit(1)
    )
    if not has_avail:
        defaults = [
            *[(wd, dtime(5, 0), dtime(7, 0)) for wd in range(0, 5)],
            *[(wd, dtime(17, 30), dtime(19, 30)) for wd in range(0, 5)],
            (5, dtime(5, 0), dtime(7, 0)),
            (6, dtime(5, 0), dtime(7, 0)),
        ]
        for wd, st, et in defaults:
            db.add(
                AvailabilityRule(
                    owner_id=user.id, weekday=wd, start_time=st, end_time=et
                )
            )

    db.commit()
    return added


def provision_all_users(db: Session) -> None:
    """Make sure every existing user has the default curriculum loaded.

    Useful after upgrades that introduce per-user topics, or whenever the
    seeded curriculum changes (new entries get pushed to all users).
    """
    for u in db.scalars(select(User)).all():
        provision_user_workspace(db, u)
