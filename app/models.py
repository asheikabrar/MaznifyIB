from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    level: Mapped[str] = mapped_column(String(10))  # HL / SL
    color: Mapped[str] = mapped_column(String(20), default="#6366f1")
    icon: Mapped[str] = mapped_column(String(40), default="")  # emoji or short text
    sort_order: Mapped[int] = mapped_column(Integer, default=100)

    topics: Mapped[list["Topic"]] = relationship(back_populates="subject", cascade="all, delete-orphan")
    tasks: Mapped[list["Task"]] = relationship(back_populates="subject", cascade="all, delete-orphan")
    deadlines: Mapped[list["Deadline"]] = relationship(back_populates="subject", cascade="all, delete-orphan")


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topics.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(40), default="")  # e.g. "2.3"
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")  # student's own notes
    ib_weight: Mapped[int] = mapped_column(Integer, default=1)  # 1-5 importance
    completed_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    initial_recall: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # FSRS state (topic-level review)
    stability: Mapped[float] = mapped_column(Float, default=0.0)
    difficulty: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[int] = mapped_column(Integer, default=0)  # 0=New,1=Learning,2=Review,3=Relearning
    step: Mapped[int] = mapped_column(Integer, default=0)  # FSRS learning/relearning step index
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    last_review: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    due: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    subject: Mapped[Subject] = relationship(back_populates="topics")
    sessions: Mapped[list["StudySession"]] = relationship(back_populates="topic", cascade="all, delete-orphan")
    parent: Mapped[Optional["Topic"]] = relationship(
        back_populates="children", remote_side="Topic.id"
    )
    children: Mapped[list["Topic"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    subject_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topics.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    est_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open/done
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)  # 0..100
    # Recurrence: empty = one-off. Otherwise "DAILY" or "WEEKLY:0,2,4"
    # (comma-separated weekdays, 0=Mon..6=Sun). The scheduled_for time-of-day
    # is used as the daily start time on each repeat.
    recurrence_rule: Mapped[str] = mapped_column(String(80), default="")
    recurrence_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    subject: Mapped[Optional[Subject]] = relationship(back_populates="tasks")


class Deadline(Base):
    __tablename__ = "deadlines"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    subject_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topics.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))  # IA / EE / TOK / Mock / Test
    title: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[date] = mapped_column(Date)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)  # 0..100

    subject: Mapped[Optional[Subject]] = relationship(back_populates="deadlines")


class AvailabilityRule(Base):
    __tablename__ = "availability_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    weekday: Mapped[int] = mapped_column(Integer)  # 0=Mon .. 6=Sun
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)


class AvailabilityException(Base):
    __tablename__ = "availability_exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    on_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(200), default="")


class StudySession(Base):
    __tablename__ = "study_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topics.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # again/hard/good/easy
    # Optional test metadata (logged when the student records a test / exam result)
    test_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ib_score_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    topic: Mapped[Optional[Topic]] = relationship(back_populates="sessions")


class NoteFile(Base):
    __tablename__ = "note_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    subject_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topics.id"), nullable=True)
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(100))
    storage_path: Mapped[str] = mapped_column(String(500))
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RevisionDeskState(Base):
    __tablename__ = "revision_desk_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, unique=True, index=True)
    state: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StudyPlannerBlock(Base):
    __tablename__ = "study_planner_blocks"
    __table_args__ = (
        # Guards against the same slot being generated twice by concurrent requests
        # (e.g. the frontend's simultaneous /api/day + /api/week fetches landing on
        # separate serverless instances that can't share an in-process lock).
        UniqueConstraint("owner_id", "on_date", "slot_index", name="uq_planner_block_owner_date_slot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    slot_index: Mapped[int] = mapped_column(Integer, default=0)
    block_kind: Mapped[str] = mapped_column(String(40), default="rotating")
    subject_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    task_name: Mapped[str] = mapped_column(String(300), default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=50)
    start_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # "HH:MM", 24h
    end_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # "HH:MM", 24h
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revision_pushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    carried_forward: Mapped[bool] = mapped_column(Boolean, default=False)  # this block's leftover work was carried to the next day
    carried_from_id: Mapped[Optional[int]] = mapped_column(ForeignKey("study_planner_blocks.id"), nullable=True)
    source_rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("planner_fixed_rules.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    subject: Mapped[Optional[Subject]] = relationship()
    revision_links: Mapped[list["StudyPlannerRevisionLink"]] = relationship(
        back_populates="block", cascade="all, delete-orphan"
    )


class PlannerFixedRule(Base):
    """A recurring commitment (e.g. "every Tuesday") that auto-materializes into a fixed block each matching day."""
    __tablename__ = "planner_fixed_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    weekday: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0=Mon..6=Sun; NULL = every day
    subject_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subjects.id"), nullable=True)
    task_name: Mapped[str] = mapped_column(String(300), default="")
    start_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # "HH:MM"
    duration_minutes: Mapped[int] = mapped_column(Integer, default=50)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    subject: Mapped[Optional[Subject]] = relationship()


class StudyPlannerRevisionLink(Base):
    __tablename__ = "study_planner_revision_links"
    __table_args__ = (
        UniqueConstraint("block_id", "revision_subject_id", "revision_chapter_id", name="uq_planner_block_revision_link"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("study_planner_blocks.id"), index=True)
    revision_subject_id: Mapped[str] = mapped_column(String(120), default="")
    revision_chapter_id: Mapped[str] = mapped_column(String(120), default="")
    revision_subject_name: Mapped[str] = mapped_column(String(200), default="")
    revision_chapter_name: Mapped[str] = mapped_column(String(300), default="")
    due_date: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    block: Mapped[StudyPlannerBlock] = relationship(back_populates="revision_links")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="Chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("chat_sessions.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20))  # user / assistant / tool
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped[Optional[ChatSession]] = relationship(back_populates="messages")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(300))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    anthropic_api_key: Mapped[str] = mapped_column(String(300), default="")
    calendar_token: Mapped[str] = mapped_column(String(64), default="")  # secret used by the .ics subscription feed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
