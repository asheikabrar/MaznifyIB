"""FSRS-based spaced repetition scheduling for topics."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fsrs import Card, Rating, Scheduler, State

from app.models import Topic

_fsrs = Scheduler()

RatingStr = Literal["again", "hard", "good", "easy"]
RecallStr = Literal["forgot", "shaky", "solid", "strong"]

_RATING_MAP = {
    "again": Rating.Again,
    "hard": Rating.Hard,
    "good": Rating.Good,
    "easy": Rating.Easy,
}

# Map onboarding "how well do you remember it?" to an FSRS-equivalent rating
# used to seed initial state.
_RECALL_TO_RATING: dict[str, Rating] = {
    "forgot": Rating.Again,
    "shaky": Rating.Hard,
    "solid": Rating.Good,
    "strong": Rating.Easy,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _topic_to_card(topic: Topic) -> Card:
    # Topic.state stored as int; 0 means "never reviewed" -> default new Card
    if not topic.state:
        return Card()
    state = State(topic.state)
    # FSRS requires Card.step to be an int when state is Learning/Relearning.
    step = int(topic.step or 0) if state in (State.Learning, State.Relearning) else None
    return Card(
        state=state,
        step=step,
        stability=topic.stability or None,
        difficulty=topic.difficulty or None,
        due=_ensure_aware(topic.due),
        last_review=_ensure_aware(topic.last_review),
    )


def _apply_card_to_topic(topic: Topic, card: Card) -> None:
    topic.state = int(card.state)
    topic.step = int(card.step) if card.step is not None else 0
    topic.stability = float(card.stability or 0.0)
    topic.difficulty = float(card.difficulty or 0.0)
    # DB column is naive DateTime — strip tz info before storing.
    topic.last_review = card.last_review.replace(tzinfo=None) if card.last_review else None
    topic.due = card.due.replace(tzinfo=None) if card.due else None


def review_topic(topic: Topic, rating: RatingStr, when: datetime | None = None) -> Topic:
    """Apply a review rating to a topic and update its FSRS state."""
    when_aware = _ensure_aware(when) or _utcnow()
    card = _topic_to_card(topic)
    new_card, _log = _fsrs.review_card(card, _RATING_MAP[rating], when_aware)
    _apply_card_to_topic(topic, new_card)
    topic.reps = (topic.reps or 0) + 1
    if rating == "again":
        topic.lapses = (topic.lapses or 0) + 1
    return topic


def seed_completed_topic(
    topic: Topic, completed_on: datetime, recall: RecallStr
) -> Topic:
    """Seed FSRS state for a topic the student studied earlier (Term 1 backfill)."""
    rating = _RECALL_TO_RATING[recall]
    completed_aware = _ensure_aware(completed_on) or _utcnow()
    card = Card()
    new_card, _log = _fsrs.review_card(card, rating, completed_aware)
    _apply_card_to_topic(topic, new_card)
    topic.completed_on = completed_aware.date()
    topic.initial_recall = recall
    topic.reps = 1

    # Pull "due" forward to today if the seeded review already lapsed,
    # so it shows up in the plan instead of being overdue silently.
    now = datetime.utcnow()
    if topic.due and topic.due < now:
        topic.due = now
    return topic


def days_overdue(topic: Topic, now: datetime | None = None) -> float:
    if not topic.due:
        return 0.0
    now = now or datetime.utcnow()
    return max(0.0, (now - topic.due).total_seconds() / 86400.0)
