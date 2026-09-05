"""Daily/weekly study planner linked to Revision Desk spaced-revision state."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    PlannerFixedRule,
    RevisionDeskState,
    StudyPlannerBlock,
    StudyPlannerRevisionLink,
    Subject,
)

# The frontend fetches /api/day and /api/week concurrently on every refresh, and both
# call ensure_week_blocks(). Without protection, two requests for a not-yet-generated
# week can each see zero existing rows and both insert a full week of blocks, duplicating
# everything. An in-process lock alone isn't enough here: on Vercel's serverless model,
# concurrent requests can land on entirely separate processes/instances that share no
# memory. The real cross-process guard is the `uq_planner_block_owner_date_slot` unique
# DB constraint (see app/models.py + the migration in app/db.py) combined with
# ensure_week_blocks_safe() below, which tolerates losing that race instead of
# duplicating rows.

REVISION_INTERVALS = [2, 4, 7, 14, 30]

UCAT_WEEKDAY_FOCUS = {
    0: "UCAT: Verbal Reasoning",
    1: "UCAT: Decision Making",
    2: "UCAT: Quantitative Reasoning",
    3: "UCAT: Abstract Reasoning",
    4: "UCAT: Situational Judgement",
    5: "UCAT: Mixed Practice Set",
    6: "UCAT: Light Review",
}


@dataclass
class RevisionDueCard:
    subject_id: str
    subject_name: str
    chapter_id: str
    chapter_name: str
    due_date: str


def week_start_monday(on_date: date) -> date:
    return on_date - timedelta(days=on_date.weekday())


def normalize_subject_name(name: str) -> str:
    return "".join(ch.lower() for ch in (name or "") if ch.isalnum())


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _iso_add_days(day_iso: str, days: int) -> str:
    d = date.fromisoformat(day_iso)
    return (d + timedelta(days=days)).isoformat()


def load_revision_desk_state(db: Session, user_id: int) -> dict:
    row = db.scalar(select(RevisionDeskState).where(RevisionDeskState.owner_id == user_id))
    if not row or not row.state:
        return {"subjects": []}
    try:
        state = json.loads(row.state)
    except Exception:
        return {"subjects": []}
    if not isinstance(state, dict):
        return {"subjects": []}
    if not isinstance(state.get("subjects"), list):
        state["subjects"] = []
    return state


def save_revision_desk_state(db: Session, user_id: int, state: dict) -> None:
    row = db.scalar(select(RevisionDeskState).where(RevisionDeskState.owner_id == user_id))
    payload = json.dumps(state)
    if row:
        row.state = payload
        row.updated_at = datetime.utcnow()
        return
    db.add(
        RevisionDeskState(
            owner_id=user_id,
            state=payload,
            updated_at=datetime.utcnow(),
        )
    )


def get_due_cards_for_day(state: dict, on_date: date) -> list[RevisionDueCard]:
    day_iso = on_date.isoformat()
    cards: list[RevisionDueCard] = []
    for subj in state.get("subjects", []):
        if subj.get("disabled"):
            continue
        sid = str(subj.get("id") or "")
        sname = str(subj.get("name") or "")
        for chapter in subj.get("chapters", []):
            if chapter.get("disabled"):
                continue
            due_date = str(chapter.get("dueDate") or "").strip()
            if not due_date:
                continue
            if due_date <= day_iso:
                cards.append(
                    RevisionDueCard(
                        subject_id=sid,
                        subject_name=sname,
                        chapter_id=str(chapter.get("id") or ""),
                        chapter_name=str(chapter.get("name") or ""),
                        due_date=due_date,
                    )
                )
    cards.sort(key=lambda c: (c.due_date, c.subject_name.lower(), c.chapter_name.lower()))
    return cards


def get_subjects_for_planner(db: Session) -> list[Subject]:
    return list(db.scalars(select(Subject).order_by(Subject.sort_order, Subject.name)))


def _active_revision_desk_subject_names(db: Session, user_id: int) -> list[str]:
    state = load_revision_desk_state(db, user_id)
    return [
        s.get("name", "")
        for s in state.get("subjects", [])
        if s.get("name") and not s.get("disabled")
    ]


def _subject_tracked_in_revision_desk(subject_name: str, rd_names: list[str]) -> bool:
    """Loosely match a curriculum Subject's name against Revision Desk's own
    (independently-typed) subject names, e.g. "English Lang & Lit" <->
    "English A Language and Literature HL"."""
    g = normalize_subject_name(subject_name)
    first_word = subject_name.strip().split()[0].lower() if subject_name.strip() else ""
    for rd_name in rd_names:
        r = normalize_subject_name(rd_name)
        if g and r and (g in r or r in g):
            return True
        if len(first_word) > 2 and first_word in rd_name.lower():
            return True
    return False


def _find_subject_by_keyword(subjects: list[Subject], keyword: str) -> Optional[Subject]:
    key = keyword.lower()
    for s in subjects:
        if key in (s.name or "").lower():
            return s
    return None


def get_fixed_rules_for_user(db: Session, user_id: int) -> list[PlannerFixedRule]:
    return list(
        db.scalars(
            select(PlannerFixedRule)
            .where(PlannerFixedRule.owner_id == user_id)
            .where(PlannerFixedRule.active.is_(True))
            .order_by(PlannerFixedRule.id)
        )
    )


def _apply_fixed_rules_for_week(db: Session, user_id: int, week_start: date) -> None:
    """Materialize any active recurring fixed rules (e.g. "every Tuesday") into
    real blocks for the given week, skipping days that already have that rule's instance."""
    rules = get_fixed_rules_for_user(db, user_id)
    if not rules:
        return

    week_end = week_start + timedelta(days=6)
    db.flush()
    existing = list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == user_id)
            .where(StudyPlannerBlock.on_date >= week_start)
            .where(StudyPlannerBlock.on_date <= week_end)
        )
    )
    by_day: dict[date, list[StudyPlannerBlock]] = defaultdict(list)
    for b in existing:
        by_day[b.on_date].append(b)
    have_rule_instance = {(b.on_date, b.source_rule_id) for b in existing if b.source_rule_id}

    for day_offset in range(7):
        on_date = week_start + timedelta(days=day_offset)
        weekday = on_date.weekday()
        for rule in rules:
            if rule.weekday is not None and rule.weekday != weekday:
                continue
            if (on_date, rule.id) in have_rule_instance:
                continue

            day_blocks = by_day.get(on_date, [])
            if any(b.block_kind == "placeholder" for b in day_blocks):
                db.execute(
                    delete(StudyPlannerBlock)
                    .where(StudyPlannerBlock.owner_id == user_id)
                    .where(StudyPlannerBlock.on_date == on_date)
                    .where(StudyPlannerBlock.block_kind == "placeholder")
                )
                day_blocks = [b for b in day_blocks if b.block_kind != "placeholder"]

            next_slot = max((b.slot_index for b in day_blocks), default=-1) + 1
            new_block = StudyPlannerBlock(
                owner_id=user_id,
                on_date=on_date,
                slot_index=next_slot,
                block_kind="rule_fixed",
                subject_id=rule.subject_id,
                task_name=rule.task_name or (rule.subject.name if rule.subject else "Fixed block"),
                duration_minutes=rule.duration_minutes,
                start_time=rule.start_time,
                is_fixed=True,
                is_optional=rule.is_optional,
                source_rule_id=rule.id,
            )
            db.add(new_block)
            db.flush()
            by_day.setdefault(on_date, []).append(new_block)
            have_rule_instance.add((on_date, rule.id))


def _rotation_subjects(subjects: list[Subject], fixed_ids: set[int]) -> list[Subject]:
    candidates = [
        s
        for s in subjects
        if s.id not in fixed_ids and (s.level or "").lower() not in {"core", "test"}
    ]
    if len(candidates) < 5:
        candidates = [s for s in subjects if s.id not in fixed_ids]
    return candidates[:5]


def _slot_weight(subject: Subject) -> float:
    w = 1.0
    if (subject.level or "").upper() == "HL":
        w += 0.35
    lname = (subject.name or "").lower()
    if "biology" in lname or "english" in lname:
        w += 0.25
    return w


def _weighted_slot_targets(subjects: list[Subject], total_slots: int) -> dict[int, int]:
    if not subjects or total_slots <= 0:
        return {}
    weights = {_s.id: _slot_weight(_s) for _s in subjects}
    total_weight = sum(weights.values())
    raw = {_id: (weights[_id] / total_weight) * total_slots for _id in weights}
    targets = {_id: int(raw[_id]) for _id in raw}
    remainder = total_slots - sum(targets.values())
    if remainder > 0:
        frac = sorted(raw.keys(), key=lambda _id: (raw[_id] - targets[_id]), reverse=True)
        for idx in range(remainder):
            targets[frac[idx % len(frac)]] += 1
    for _id in list(targets.keys()):
        if targets[_id] <= 0:
            targets[_id] = 1
    while sum(targets.values()) > total_slots:
        biggest = max(targets, key=lambda k: targets[k])
        if targets[biggest] <= 1:
            break
        targets[biggest] -= 1
    return targets


def _pick_subject_for_day(remaining: dict[int, int], used_today: set[int]) -> Optional[int]:
    available = [sid for sid, count in remaining.items() if count > 0]
    if not available:
        return None
    non_repeating = [sid for sid in available if sid not in used_today]
    pool = non_repeating if non_repeating else available
    pool.sort(key=lambda sid: (remaining[sid], -sid), reverse=True)
    return pool[0]


def _allocate_rotation_for_week(rotation_subjects: list[Subject]) -> dict[int, list[int]]:
    # Mon-Fri: 3 each, Sat: 1, Sun: 1 optional = 17 rotation slots.
    slots_per_day = {0: 3, 1: 3, 2: 3, 3: 3, 4: 3, 5: 1, 6: 1}
    total_slots = sum(slots_per_day.values())
    remaining = _weighted_slot_targets(rotation_subjects, total_slots)
    allocation: dict[int, list[int]] = {d: [] for d in range(7)}
    for day_idx in range(7):
        used: set[int] = set()
        for _ in range(slots_per_day[day_idx]):
            sid = _pick_subject_for_day(remaining, used)
            if sid is None and rotation_subjects:
                sid = rotation_subjects[0].id
            if sid is None:
                continue
            allocation[day_idx].append(sid)
            used.add(sid)
            if sid in remaining and remaining[sid] > 0:
                remaining[sid] -= 1
    return allocation


def _default_task_name(kind: str, on_date: date, subject_name: str = "") -> str:
    if kind == "fixed_arabic":
        return "Arabic: reading + vocab practice"
    if kind == "fixed_ucat":
        return UCAT_WEEKDAY_FOCUS.get(on_date.weekday(), "UCAT practice")
    if kind == "catchup":
        return "Catch-up: finish overdue study blocks"
    if kind == "ia_ee":
        if subject_name:
            return f"{subject_name}: portfolio / IA-EE progress"
        return "IA/EE: portfolio or writing progress"
    if kind == "optional_review":
        return "Optional review: light recap"
    if subject_name:
        return f"{subject_name}: focused practice"
    return "Focused study block"


def ensure_week_blocks(db: Session, user_id: int, anchor_date: date) -> None:
    week_start = week_start_monday(anchor_date)
    week_end = week_start + timedelta(days=6)

    existing = list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == user_id)
            .where(StudyPlannerBlock.on_date >= week_start)
            .where(StudyPlannerBlock.on_date <= week_end)
        )
    )
    by_day: dict[date, list[StudyPlannerBlock]] = defaultdict(list)
    for b in existing:
        by_day[b.on_date].append(b)

    subjects = get_subjects_for_planner(db)
    active_names = _active_revision_desk_subject_names(db, user_id)
    if active_names:
        # only plan around subjects the student is actually tracking in Revision Desk
        scoped = [s for s in subjects if _subject_tracked_in_revision_desk(s.name, active_names)]
        if scoped:
            subjects = scoped

    arabic = _find_subject_by_keyword(subjects, "arabic")
    ucat = _find_subject_by_keyword(subjects, "ucat")
    fixed_ids = {s.id for s in [arabic, ucat] if s is not None}
    rotation_subjects = _rotation_subjects(subjects, fixed_ids)
    rotation_allocation = _allocate_rotation_for_week(rotation_subjects)

    visual_arts = _find_subject_by_keyword(subjects, "visual")
    ee = _find_subject_by_keyword(subjects, "extended essay")
    ia_ee_subject = visual_arts or ee

    for day_offset in range(7):
        on_date = week_start + timedelta(days=day_offset)
        if by_day.get(on_date):
            continue

        slot = 0

        if arabic:
            db.add(
                StudyPlannerBlock(
                    owner_id=user_id,
                    on_date=on_date,
                    slot_index=slot,
                    block_kind="fixed_arabic",
                    subject_id=arabic.id,
                    task_name=_default_task_name("fixed_arabic", on_date, arabic.name),
                    duration_minutes=30,
                    is_fixed=True,
                    is_optional=False,
                )
            )
            slot += 1

        if ucat:
            db.add(
                StudyPlannerBlock(
                    owner_id=user_id,
                    on_date=on_date,
                    slot_index=slot,
                    block_kind="fixed_ucat",
                    subject_id=ucat.id,
                    task_name=_default_task_name("fixed_ucat", on_date, ucat.name),
                    duration_minutes=30,
                    is_fixed=True,
                    is_optional=False,
                )
            )
            slot += 1

        rotation_ids = list(rotation_allocation.get(on_date.weekday(), []))

        if on_date.weekday() == 5:
            db.add(
                StudyPlannerBlock(
                    owner_id=user_id,
                    on_date=on_date,
                    slot_index=slot,
                    block_kind="catchup",
                    subject_id=None,
                    task_name=_default_task_name("catchup", on_date),
                    duration_minutes=50,
                    is_fixed=False,
                    is_optional=False,
                )
            )
            slot += 1

            db.add(
                StudyPlannerBlock(
                    owner_id=user_id,
                    on_date=on_date,
                    slot_index=slot,
                    block_kind="ia_ee",
                    subject_id=ia_ee_subject.id if ia_ee_subject else None,
                    task_name=_default_task_name(
                        "ia_ee", on_date, ia_ee_subject.name if ia_ee_subject else ""
                    ),
                    duration_minutes=50,
                    is_fixed=False,
                    is_optional=False,
                )
            )
            slot += 1

            if rotation_ids:
                sid = rotation_ids[0]
                s = next((x for x in subjects if x.id == sid), None)
                db.add(
                    StudyPlannerBlock(
                        owner_id=user_id,
                        on_date=on_date,
                        slot_index=slot,
                        block_kind="rotating",
                        subject_id=sid,
                        task_name=_default_task_name("rotating", on_date, s.name if s else ""),
                        duration_minutes=50,
                        is_fixed=False,
                        is_optional=False,
                    )
                )
                slot += 1

        elif on_date.weekday() == 6:
            sid = rotation_ids[0] if rotation_ids else None
            s = next((x for x in subjects if x.id == sid), None) if sid else None
            db.add(
                StudyPlannerBlock(
                    owner_id=user_id,
                    on_date=on_date,
                    slot_index=slot,
                    block_kind="optional_review",
                    subject_id=sid,
                    task_name=_default_task_name("optional_review", on_date, s.name if s else ""),
                    duration_minutes=50,
                    is_fixed=False,
                    is_optional=True,
                )
            )
            slot += 1

        else:
            for sid in rotation_ids[:3]:
                s = next((x for x in subjects if x.id == sid), None)
                db.add(
                    StudyPlannerBlock(
                        owner_id=user_id,
                        on_date=on_date,
                        slot_index=slot,
                        block_kind="rotating",
                        subject_id=sid,
                        task_name=_default_task_name("rotating", on_date, s.name if s else ""),
                        duration_minutes=50,
                        is_fixed=False,
                        is_optional=False,
                    )
                )
                slot += 1

    _apply_fixed_rules_for_week(db, user_id, week_start)


def ensure_week_blocks_safe(db: Session, user_id: int, anchor_date: date) -> None:
    """ensure_week_blocks(), tolerant of a concurrent request generating the exact
    same week's blocks at the same time (e.g. the frontend's simultaneous
    /api/day + /api/week fetches landing on two separate serverless instances that
    share no memory).

    Runs the generation in a SAVEPOINT and relies on the uq_planner_block_owner_date_slot
    DB constraint to turn what would have been a duplicate-row race into a harmless,
    swallowed IntegrityError -- whichever request commits first "wins" and the loser
    just discards its attempt and reads the winner's rows on the next query.

    Also tolerates OperationalError: local SQLite only allows one writer active
    against the *whole* database file at a time (not just per-row, unlike Postgres),
    so heavy concurrent writers -- even ones touching unrelated weeks -- can hit
    "database is locked" even with busy_timeout set. Postgres (prod) doesn't have
    this failure mode. A few short retries give other in-flight transactions a
    chance to finish committing before we give up -- without retrying, concurrent
    requests can all fail and leave a week ungenerated until the next unrelated
    refresh.
    """
    delays = (0.05, 0.1, 0.2)
    for attempt in range(len(delays) + 1):
        try:
            with db.begin_nested():
                ensure_week_blocks(db, user_id, anchor_date)
            return
        except (IntegrityError, OperationalError):
            if attempt == len(delays):
                return
            time.sleep(delays[attempt])


def map_due_card_subject_to_id(card: RevisionDueCard, subjects: list[Subject]) -> Optional[int]:
    if not subjects:
        return None
    target = normalize_subject_name(card.subject_name)
    subject_lookup = {normalize_subject_name(s.name): s.id for s in subjects}
    if target in subject_lookup:
        return subject_lookup[target]

    for s in subjects:
        a = normalize_subject_name(s.name)
        if target and (target in a or a in target):
            return s.id
    return None


def add_due_link_to_block(
    db: Session,
    block: StudyPlannerBlock,
    due_card: RevisionDueCard,
) -> bool:
    if not due_card.chapter_id:
        return False
    existing = db.scalar(
        select(StudyPlannerRevisionLink)
        .where(StudyPlannerRevisionLink.block_id == block.id)
        .where(StudyPlannerRevisionLink.revision_subject_id == due_card.subject_id)
        .where(StudyPlannerRevisionLink.revision_chapter_id == due_card.chapter_id)
    )
    if existing:
        return False
    db.add(
        StudyPlannerRevisionLink(
            block_id=block.id,
            revision_subject_id=due_card.subject_id,
            revision_chapter_id=due_card.chapter_id,
            revision_subject_name=due_card.subject_name,
            revision_chapter_name=due_card.chapter_name,
            due_date=due_card.due_date,
        )
    )
    return True


def _apply_ok_review_to_revision_chapter(chapter: dict, reviewed_on: str) -> None:
    box = _safe_int(chapter.get("box"), 0)
    if box < 0:
        box = 0
    if box >= len(REVISION_INTERVALS):
        box = len(REVISION_INTERVALS) - 1

    chapter["lastReviewed"] = reviewed_on
    chapter["lastProficiency"] = "ok"
    chapter["dueDate"] = _iso_add_days(reviewed_on, REVISION_INTERVALS[box])
    chapter["box"] = box

    history = chapter.get("revisionHistory")
    if not isinstance(history, list):
        history = []
        chapter["revisionHistory"] = history
    history.append(
        {
            "reviewedAt": reviewed_on,
            "minutes": 0,
            "proficiency": "ok",
            "box": box,
            "dueDate": chapter["dueDate"],
            "testScore": chapter.get("lastTestScore"),
            "maxMarks": chapter.get("maxMarks"),
            "ibScoreType": chapter.get("ibScoreType") or "",
        }
    )


def _find_revision_subject(state: dict, link: StudyPlannerRevisionLink) -> Optional[dict]:
    subjects = state.get("subjects", [])
    for subj in subjects:
        if str(subj.get("id") or "") == link.revision_subject_id:
            return subj

    target = normalize_subject_name(link.revision_subject_name)
    for subj in subjects:
        sname = normalize_subject_name(str(subj.get("name") or ""))
        if target and (target == sname or target in sname or sname in target):
            return subj
    return None


def _find_revision_chapter(subj: dict, link: StudyPlannerRevisionLink) -> Optional[dict]:
    chapters = subj.get("chapters", [])
    for c in chapters:
        if str(c.get("id") or "") == link.revision_chapter_id:
            return c

    target = (link.revision_chapter_name or "").strip().lower()
    for c in chapters:
        if (str(c.get("name") or "").strip().lower()) == target:
            return c
    return None


def push_block_links_to_revision_state(db: Session, user_id: int, block: StudyPlannerBlock) -> int:
    if not block.revision_links:
        return 0
    state = load_revision_desk_state(db, user_id)
    reviewed_on = block.on_date.isoformat()
    applied = 0

    for link in block.revision_links:
        subj = _find_revision_subject(state, link)
        if not subj:
            continue
        chapter = _find_revision_chapter(subj, link)
        if not chapter:
            continue
        _apply_ok_review_to_revision_chapter(chapter, reviewed_on)
        applied += 1

    if applied > 0:
        save_revision_desk_state(db, user_id, state)
    return applied


def resolve_carry_over_origin_date(
    db: Session,
    block: StudyPlannerBlock,
    blocks_by_id: Optional[dict[int, StudyPlannerBlock]] = None,
    max_hops: int = 60,
) -> Optional[date]:
    """Walk a block's carried_from_id chain back to the earliest ancestor and
    return that ancestor's on_date -- the day the task was originally scheduled,
    before any carry-overs. Returns None if this block was never carried forward.
    `blocks_by_id` (already-loaded blocks, e.g. for the current week) avoids extra
    queries when the whole chain is within that set."""
    if not block.carried_from_id:
        return None
    lookup = blocks_by_id or {}
    current_id: Optional[int] = block.carried_from_id
    origin_date: Optional[date] = None
    hops = 0
    while current_id and hops < max_hops:
        parent = lookup.get(current_id) or db.get(StudyPlannerBlock, current_id)
        if not parent:
            break
        origin_date = parent.on_date
        current_id = parent.carried_from_id
        hops += 1
    return origin_date


def get_week_blocks(
    db: Session,
    user_id: int,
    week_start: date,
) -> list[StudyPlannerBlock]:
    week_end = week_start + timedelta(days=6)
    return list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == user_id)
            .where(StudyPlannerBlock.on_date >= week_start)
            .where(StudyPlannerBlock.on_date <= week_end)
            .options(selectinload(StudyPlannerBlock.revision_links))
            .order_by(StudyPlannerBlock.on_date, StudyPlannerBlock.slot_index, StudyPlannerBlock.id)
        )
    )


def planner_streak_days(db: Session, user_id: int, today: date) -> int:
    start = today - timedelta(days=90)
    blocks = list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == user_id)
            .where(StudyPlannerBlock.on_date >= start)
            .where(StudyPlannerBlock.on_date <= today)
        )
    )
    by_day: dict[date, list[StudyPlannerBlock]] = defaultdict(list)
    for b in blocks:
        by_day[b.on_date].append(b)

    streak = 0
    cursor = today
    while True:
        day_blocks = [b for b in by_day.get(cursor, []) if not b.is_optional]
        if not day_blocks:
            break
        if not all(b.completed for b in day_blocks):
            break
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def weekly_subject_minutes(blocks: list[StudyPlannerBlock]) -> dict[int, int]:
    totals: dict[int, int] = defaultdict(int)
    for b in blocks:
        if b.subject_id:
            totals[b.subject_id] += max(0, int(b.duration_minutes or 0))
    return dict(totals)
