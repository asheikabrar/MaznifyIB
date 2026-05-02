"""Daily plan generator: pulls due reviews + tasks and packs them into the day's free-time slots."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AvailabilityException,
    AvailabilityRule,
    Deadline,
    StudySession,
    Subject,
    Task,
    Topic,
)

# Subjects whose name contains any of these words get an "energy" boost in the morning.
HARD_SUBJECT_KEYWORDS = ("math", "chem", "physics", "bio")

DEFAULT_REVIEW_MINUTES = 25
MIN_REVIEW_MINUTES = 10


@dataclass
class TimeSlot:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class PlanItem:
    kind: str  # "review" | "task" | "deadline_prep"
    title: str
    subject_name: Optional[str]
    subject_color: str = "#6366f1"
    topic_id: Optional[int] = None
    task_id: Optional[int] = None
    progress_pct: int = 0
    est_minutes: int = DEFAULT_REVIEW_MINUTES
    score: float = 0.0
    slot_index: Optional[int] = None  # which slot it was packed into
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    completed: bool = False
    # If set, the packer will place this item at exactly this time-of-day
    # (within whichever slot contains it), reserving that block before
    # packing other items. Used for tasks with a user-chosen scheduled_for.
    pinned_time: Optional[time] = None


@dataclass
class DailyPlan:
    on_date: date
    slots: list[TimeSlot] = field(default_factory=list)
    items: list[PlanItem] = field(default_factory=list)
    unscheduled: list[PlanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_planned_minutes(self) -> int:
        return sum(i.est_minutes for i in self.items)

    @property
    def total_available_minutes(self) -> int:
        return sum(s.minutes for s in self.slots)


# ---------- availability ----------

def slots_for_date(db: Session, on_date: date, user_id: int | None = None) -> list[TimeSlot]:
    """Compute the actual study time slots for a given date.

    Starts from the weekly AvailabilityRule, then applies AvailabilityException
    rows for that date (block or extra slot). Filtered by ``user_id`` so each
    student gets their own availability.
    """
    weekday = on_date.weekday()  # Mon=0..Sun=6
    rules_q = select(AvailabilityRule).where(AvailabilityRule.weekday == weekday)
    if user_id is not None:
        rules_q = rules_q.where(AvailabilityRule.owner_id == user_id)
    rules = db.scalars(rules_q).all()

    slots: list[TimeSlot] = [
        TimeSlot(
            start=datetime.combine(on_date, r.start_time),
            end=datetime.combine(on_date, r.end_time),
        )
        for r in rules
    ]

    ex_q = select(AvailabilityException).where(AvailabilityException.on_date == on_date)
    if user_id is not None:
        ex_q = ex_q.where(AvailabilityException.owner_id == user_id)
    exceptions = db.scalars(ex_q).all()

    for ex in exceptions:
        if ex.is_blocked:
            if ex.start_time is None or ex.end_time is None:
                # whole day blocked
                slots = []
            else:
                blocked = TimeSlot(
                    start=datetime.combine(on_date, ex.start_time),
                    end=datetime.combine(on_date, ex.end_time),
                )
                slots = _subtract(slots, blocked)
        else:
            # extra availability
            if ex.start_time and ex.end_time:
                slots.append(
                    TimeSlot(
                        start=datetime.combine(on_date, ex.start_time),
                        end=datetime.combine(on_date, ex.end_time),
                    )
                )

    slots.sort(key=lambda s: s.start)
    return slots


def _subtract(slots: list[TimeSlot], blocked: TimeSlot) -> list[TimeSlot]:
    out: list[TimeSlot] = []
    for s in slots:
        if blocked.end <= s.start or blocked.start >= s.end:
            out.append(s)
            continue
        if blocked.start > s.start:
            out.append(TimeSlot(s.start, blocked.start))
        if blocked.end < s.end:
            out.append(TimeSlot(blocked.end, s.end))
    return out


# ---------- candidate items ----------

def _due_topics(db: Session, on_date: date, user_id: int | None = None) -> list[Topic]:
    end_of_day = datetime.combine(on_date, time(23, 59, 59))
    q = select(Topic).where(Topic.due.is_not(None), Topic.due <= end_of_day)
    if user_id is not None:
        q = q.where(Topic.owner_id == user_id)
    return list(db.scalars(q))


def _task_occurs_on(t: Task, on_date: date) -> bool:
    """Does a recurring task occur on the given date?

    Rule format:
      ""              -> not recurring (one-off)
      "DAILY"         -> every day from scheduled_for.date() until recurrence_until
      "WEEKLY:0,2,4"  -> on those weekdays (Mon=0..Sun=6) from scheduled_for.date()
    """
    rule = (t.recurrence_rule or "").strip()
    if not rule or not t.scheduled_for:
        return False
    base_date = t.scheduled_for.date()
    if on_date < base_date:
        return False
    if t.recurrence_until and on_date > t.recurrence_until:
        return False
    if rule == "DAILY":
        return True
    if rule.startswith("WEEKLY:"):
        try:
            wds = {int(x) for x in rule.split(":", 1)[1].split(",") if x.strip() != ""}
        except ValueError:
            return False
        return on_date.weekday() in wds
    return False


def _open_tasks(db: Session, on_date: date, user_id: int | None = None) -> list[Task]:
    """Return open tasks relevant to `on_date`."""
    horizon = on_date + timedelta(days=7)
    base = select(Task).where(
        Task.status == "open",
        (Task.due_date.is_(None)) | (Task.due_date <= horizon),
    )
    if user_id is not None:
        base = base.where(Task.owner_id == user_id)
    candidates = list(db.scalars(base))
    out: list[Task] = []
    for t in candidates:
        if t.recurrence_rule:
            if _task_occurs_on(t, on_date):
                out.append(t)
        else:
            out.append(t)
    rec_q = select(Task).where(Task.status == "open", Task.recurrence_rule != "")
    if user_id is not None:
        rec_q = rec_q.where(Task.owner_id == user_id)
    for t in db.scalars(rec_q).all():
        if t in out:
            continue
        if _task_occurs_on(t, on_date):
            out.append(t)
    return out


def _done_tasks_for_day(db: Session, on_date: date, user_id: int | None = None) -> list[Task]:
    q = select(Task).where(
        Task.status == "done",
        Task.scheduled_for.is_not(None),
    )
    if user_id is not None:
        q = q.where(Task.owner_id == user_id)
    return list(db.scalars(q))


def _upcoming_deadlines(db: Session, on_date: date, user_id: int | None = None) -> list[Deadline]:
    horizon = on_date + timedelta(days=14)
    q = select(Deadline).where(
        Deadline.due_date >= on_date, Deadline.due_date <= horizon
    )
    if user_id is not None:
        q = q.where(Deadline.owner_id == user_id)
    return list(db.scalars(q))


# ---------- scoring ----------

def _topic_score(topic: Topic, on_date: date) -> float:
    """Higher = more urgent."""
    base = float(topic.ib_weight or 1)
    overdue_days = 0.0
    if topic.due:
        overdue_days = max(
            0.0,
            (datetime.combine(on_date, time(23, 59)) - topic.due).total_seconds() / 86400.0,
        )
    # retention risk grows fast once overdue
    return base * (1.0 + overdue_days * 0.5)


def _task_score(task: Task, on_date: date) -> float:
    base = 3.0
    if task.due_date:
        days_left = (task.due_date - on_date).days
        if days_left <= 0:
            base = 10.0
        else:
            base = max(3.0, 10.0 - days_left)
    return base


# ---------- packing ----------

def build_plan(
    db: Session,
    on_date: date | None = None,
    user_id: int | None = None,
) -> DailyPlan:
    on_date = on_date or date.today()
    plan = DailyPlan(on_date=on_date)
    plan.slots = slots_for_date(db, on_date, user_id=user_id)

    candidates: list[PlanItem] = []

    due_topics = _due_topics(db, on_date, user_id=user_id)

    # Dynamically size each review's minutes so the rotation fits available time.
    # Subtract minutes already taken by user-scheduled tasks for that date.
    open_tasks = _open_tasks(db, on_date, user_id=user_id)
    scheduled_task_minutes = 0
    for tk in open_tasks:
        if tk.scheduled_for and tk.scheduled_for.date() == on_date:
            scheduled_task_minutes += tk.est_minutes or 30

    available_for_reviews = max(0, plan.total_available_minutes - scheduled_task_minutes)
    if due_topics:
        target_per_topic = (
            available_for_reviews // len(due_topics) if len(due_topics) else DEFAULT_REVIEW_MINUTES
        )
        review_minutes = max(MIN_REVIEW_MINUTES, min(DEFAULT_REVIEW_MINUTES, target_per_topic))
    else:
        review_minutes = DEFAULT_REVIEW_MINUTES

    # Topic reviews
    for t in due_topics:
        subj: Subject | None = t.subject
        candidates.append(
            PlanItem(
                kind="review",
                title=f"{t.code + ' ' if t.code else ''}{t.title}",
                subject_name=subj.name if subj else None,
                subject_color=subj.color if subj else "#6366f1",
                topic_id=t.id,
                est_minutes=review_minutes,
                score=_topic_score(t, on_date),
            )
        )

    # Tasks
    for tk in open_tasks:
        subj = tk.subject
        title = tk.title
        if tk.recurrence_rule:
            title = f"🔁 {title}"
        # Pinned time: a task with scheduled_for (one-off OR recurring) should
        # land at its exact configured time-of-day, not get squeezed out by
        # reviews. For recurring tasks the time-of-day comes from the original
        # scheduled_for; the date is whatever `on_date` we're rendering.
        pinned: time | None = None
        if tk.scheduled_for:
            if tk.recurrence_rule or tk.scheduled_for.date() == on_date:
                pinned = tk.scheduled_for.time()
        candidates.append(
            PlanItem(
                kind="task",
                title=title,
                subject_name=subj.name if subj else None,
                subject_color=subj.color if subj else "#6366f1",
                task_id=tk.id,
                progress_pct=tk.progress_pct or 0,
                est_minutes=tk.est_minutes or 30,
                score=_task_score(tk, on_date),
                pinned_time=pinned,
            )
        )

    # Completed tasks scheduled for this date — keep visible with a tick.
    for tk in _done_tasks_for_day(db, on_date, user_id=user_id):
        if tk.scheduled_for and tk.scheduled_for.date() == on_date:
            subj = tk.subject
            candidates.append(
                PlanItem(
                    kind="task",
                    title=tk.title,
                    subject_name=subj.name if subj else None,
                    subject_color=subj.color if subj else "#6366f1",
                    task_id=tk.id,
                    progress_pct=100,
                    est_minutes=tk.est_minutes or 30,
                    score=0.0,  # done items go last
                    completed=True,
                )
            )

    # Completed spaced-revision reviews logged today — keep them visible with
    # a tick instead of letting them silently vanish from the plan.
    day_start = datetime.combine(on_date, time.min)
    day_end = datetime.combine(on_date, time.max)
    sess_q = (
        select(StudySession)
        .where(StudySession.started_at >= day_start)
        .where(StudySession.started_at <= day_end)
        .where(StudySession.topic_id.is_not(None))
    )
    if user_id is not None:
        sess_q = sess_q.where(StudySession.owner_id == user_id)
    todays_review_sessions = list(db.scalars(sess_q))
    seen_topic_ids = {c.topic_id for c in candidates if c.kind == "review" and c.topic_id}
    completed_topic_ids = set()
    for sess in todays_review_sessions:
        if sess.topic_id in completed_topic_ids:
            continue
        if sess.topic_id in seen_topic_ids:
            # The next review is already due today again — don't duplicate.
            continue
        topic: Topic | None = sess.topic
        if not topic:
            continue
        completed_topic_ids.add(topic.id)
        subj = topic.subject
        candidates.append(
            PlanItem(
                kind="review",
                title=f"{topic.code + ' ' if topic.code else ''}{topic.title}",
                subject_name=subj.name if subj else None,
                subject_color=subj.color if subj else "#6366f1",
                topic_id=topic.id,
                est_minutes=DEFAULT_REVIEW_MINUTES,
                score=0.0,
                completed=True,
            )
        )

    # Deadline prep nudge (pure reminder, 0 minutes). Skip 100% done items.
    for d in _upcoming_deadlines(db, on_date, user_id=user_id):
        if (d.progress_pct or 0) >= 100:
            continue
        days_left = (d.due_date - on_date).days
        if days_left in (7, 3, 1, 0):
            subj = d.subject
            candidates.append(
                PlanItem(
                    kind="deadline_prep",
                    title=f"⚠ {d.kind}: {d.title} — {days_left}d left",
                    subject_name=subj.name if subj else None,
                    subject_color=subj.color if subj else "#ef4444",
                    est_minutes=0,
                    score=20.0 - days_left,
                )
            )

    candidates.sort(key=lambda c: c.score, reverse=True)

    # Pack into slots greedily; aim to spread subjects across slots
    slot_cursors = [s.start for s in plan.slots]
    slot_remaining = [s.minutes for s in plan.slots]
    last_subject_per_slot: list[Optional[str]] = [None] * len(plan.slots)

    # ---- Phase 1: place pinned-time items at their exact configured time ----
    # We model "reserved" intervals per slot. Pinned items always win over
    # other candidates competing for that block. A pinned item is unscheduled
    # only if its time falls outside every availability slot.
    pinned_items = [c for c in candidates if c.pinned_time is not None and c.est_minutes > 0]
    other_items = [c for c in candidates if c not in pinned_items]
    reserved: list[list[tuple[datetime, datetime]]] = [[] for _ in plan.slots]

    for item in pinned_items:
        wanted_start = datetime.combine(on_date, item.pinned_time)
        wanted_end = wanted_start + timedelta(minutes=item.est_minutes)
        placed = False
        for i, slot in enumerate(plan.slots):
            if slot.start <= wanted_start and wanted_end <= slot.end:
                item.slot_index = i
                item.start = wanted_start
                item.end = wanted_end
                reserved[i].append((wanted_start, wanted_end))
                # Subtract from this slot's remaining budget so reviews can't
                # overlap. (Approximate — packer below uses cursor-based fill.)
                slot_remaining[i] = max(0, slot_remaining[i] - item.est_minutes)
                last_subject_per_slot[i] = item.subject_name
                plan.items.append(item)
                placed = True
                break
        if not placed:
            plan.unscheduled.append(item)

    # Advance slot cursors past any reserved block so the cursor-based packer
    # below doesn't double-book a pinned task's time.
    for i, slot in enumerate(plan.slots):
        if reserved[i]:
            reserved[i].sort()
            # Move cursor to end of latest contiguous reservation starting at slot start.
            cur = slot.start
            for r_start, r_end in reserved[i]:
                if r_start <= cur:
                    cur = max(cur, r_end)
            slot_cursors[i] = cur

    # ---- Phase 2: pack remaining items around the reservations ----
    for item in other_items:
        if item.est_minutes == 0:
            # deadline reminder, attach to first slot
            if plan.slots:
                item.slot_index = 0
                item.start = plan.slots[0].start
                item.end = plan.slots[0].start
            plan.items.append(item)
            continue

        chosen = -1
        # prefer slot whose last subject differs from this one and that fits
        ranked_slots = sorted(
            range(len(plan.slots)),
            key=lambda i: (
                last_subject_per_slot[i] == item.subject_name,  # False (different) first
                -_slot_energy_match(plan.slots[i], item.subject_name or ""),
                -slot_remaining[i],
            ),
        )
        for i in ranked_slots:
            if slot_remaining[i] >= item.est_minutes:
                chosen = i
                break

        if chosen == -1:
            plan.unscheduled.append(item)
            continue

        item.slot_index = chosen
        item.start = slot_cursors[chosen]
        item.end = item.start + timedelta(minutes=item.est_minutes)
        slot_cursors[chosen] = item.end
        slot_remaining[chosen] -= item.est_minutes
        last_subject_per_slot[chosen] = item.subject_name
        plan.items.append(item)

    plan.items.sort(key=lambda i: (i.slot_index if i.slot_index is not None else 99, i.start or datetime.min))

    # ----- Warnings the dashboard can surface -----
    review_candidates = [c for c in candidates if c.kind == "review"]
    if review_candidates and not plan.slots:
        plan.warnings.append(
            f"You have {len(review_candidates)} spaced revision item(s) due "
            f"on {on_date.strftime('%a %d %b')} but no availability slots configured "
            f"for that day."
        )
    if plan.unscheduled:
        plan.warnings.append(
            f"{len(plan.unscheduled)} item(s) couldn't fit into today's slots."
        )

    return plan


def _slot_energy_match(slot: TimeSlot, subject_name: str) -> float:
    """Hard subjects fit better in morning slots; light subjects in evening."""
    is_hard = any(k in subject_name.lower() for k in HARD_SUBJECT_KEYWORDS)
    is_morning = slot.start.hour < 12
    if is_hard and is_morning:
        return 1.0
    if not is_hard and not is_morning:
        return 0.6
    return 0.0
