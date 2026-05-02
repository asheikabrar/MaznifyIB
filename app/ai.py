"""Anthropic Claude wrapper with tool-calling for StudyMate.

The student can:
  - chat
  - ask the assistant to add tasks, mark topics done, set availability, etc.
  - ask for syllabus extraction from an uploaded note

If ANTHROPIC_API_KEY is not configured, the assistant falls back to a stub
response so the rest of the app still works.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AvailabilityRule,
    ChatMessage,
    Deadline,
    NoteFile,
    Subject,
    Task,
    Topic,
)
from app import scheduler

settings = get_settings()
SUPPORTED_ANTHROPIC_MODELS = [
    "claude-3.5",
    "claude-instant-1",
    "claude-4-mini",
]
DEFAULT_ANTHROPIC_MODEL = "claude-3.5"


def get_anthropic_model(name: str | None = None) -> str:
    requested = (name or "").strip().lower()
    for model in SUPPORTED_ANTHROPIC_MODELS:
        if requested == model:
            return model
    return DEFAULT_ANTHROPIC_MODEL


def get_anthropic_model_candidates(name: str | None = None) -> list[str]:
    requested = (name or "").strip().lower()
    candidates: list[str] = []
    if requested and requested in SUPPORTED_ANTHROPIC_MODELS:
        candidates.append(requested)
    for model in SUPPORTED_ANTHROPIC_MODELS:
        if model not in candidates:
            candidates.append(model)
    return candidates


# ---------- tool schemas ----------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_task",
        "description": "Create a to-do task for the student. Use when she asks to remember/do something.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "subject": {"type": "string", "description": "Optional subject name."},
                "due_date": {"type": "string", "description": "ISO date YYYY-MM-DD, optional."},
                "est_minutes": {"type": "integer", "default": 30},
            },
            "required": ["title"],
        },
    },
    {
        "name": "add_deadline",
        "description": "Add a fixed deadline (IA, EE, mock, test).",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["IA", "EE", "TOK", "Mock", "Test", "Other"]},
                "title": {"type": "string"},
                "subject": {"type": "string"},
                "due_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
            },
            "required": ["kind", "title", "due_date"],
        },
    },
    {
        "name": "mark_topic_completed",
        "description": "Mark a topic as already-studied (e.g. Term 1) and seed it into spaced revision.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "topic_title_or_code": {"type": "string"},
                "completed_on": {"type": "string", "description": "ISO date, default today"},
                "recall": {"type": "string", "enum": ["forgot", "shaky", "solid", "strong"]},
            },
            "required": ["subject", "topic_title_or_code", "recall"],
        },
    },
    {
        "name": "review_topic",
        "description": "Record a review outcome for a topic (updates spaced-revision schedule).",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "topic_title_or_code": {"type": "string"},
                "rating": {"type": "string", "enum": ["again", "hard", "good", "easy"]},
            },
            "required": ["subject", "topic_title_or_code", "rating"],
        },
    },
    {
        "name": "add_topic",
        "description": "Add a new syllabus topic under a subject.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "code": {"type": "string"},
                "title": {"type": "string"},
                "ib_weight": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
            },
            "required": ["subject", "title"],
        },
    },
    {
        "name": "set_availability",
        "description": "Replace weekly study availability with the provided rules.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "weekday": {"type": "integer", "minimum": 0, "maximum": 6},
                            "start_time": {"type": "string", "description": "HH:MM"},
                            "end_time": {"type": "string", "description": "HH:MM"},
                        },
                        "required": ["weekday", "start_time", "end_time"],
                    },
                }
            },
            "required": ["rules"],
        },
    },
    {
        "name": "list_subjects",
        "description": "List all subjects.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_topics",
        "description": "List topics for a subject.",
        "input_schema": {
            "type": "object",
            "properties": {"subject": {"type": "string"}},
            "required": ["subject"],
        },
    },
    {
        "name": "search_notes",
        "description": (
            "Search the student's curriculum across topic notes, topic titles, and "
            "uploaded documents (PDFs/images that have been OCR'd). Returns matching "
            "snippets. Use this whenever she asks about a concept — her own notes are "
            "the primary source of truth."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "subject": {"type": "string", "description": "Optional — restrict to one subject."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_topic_notes",
        "description": "Fetch the student's notes and uploaded files for a specific topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "topic_title_or_code": {"type": "string"},
            },
            "required": ["subject", "topic_title_or_code"],
        },
    },
    {
        "name": "list_tasks",
        "description": (
            "List the student's tasks, optionally filtered by status, subject, or "
            "free-text query. Use this to answer questions like 'what tasks do I have "
            "this week' or 'summarise my open chemistry tasks'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "done", "all"], "default": "open"},
                "subject": {"type": "string"},
                "query": {"type": "string", "description": "Optional substring to match in task title or notes."},
            },
        },
    },
]


SYSTEM_PROMPT = """You are Maznify Coach, a study assistant for an IB Diploma Programme student.
Today's date is {today}.

# Scope — STRICT
You are limited to two domains and MUST refuse anything else:

1. The student's curriculum and study material — IB Diploma Programme content for
   the subjects in their Maznify workspace (Biology HL, Chemistry SL, Math AA SL,
   English Lang & Lit HL, Business Management HL, Arabic ab initio SL, Extended
   Essay, Theory of Knowledge, CAS, UCAT). This includes explaining concepts in
   those subjects, summarising the student's own topic notes / uploaded files,
   IA/EE/TOK guidance, exam technique, and revision strategy.

2. The Maznify app itself — how to use Today, Plan, Subjects, Tasks, Deadlines,
   History, Settings, AI Coach, the spaced-revision system (FSRS: Again/Hard/Good/Easy,
   Learning / In rotation / Relearning), availability rules, date overrides,
   recurring tasks, attachments, and account settings.

# Refusal rule
If the request is not clearly inside one of the two scopes above, respond with
exactly one short paragraph that:
  - politely refuses,
  - explains your scope (curriculum + Maznify app),
  - invites the student to ask a study or app question instead.
Do NOT call any tools when refusing. Do NOT attempt to answer the off-topic
request even partially.

Examples that MUST be refused: general celebrity news, sports scores, personal
advice unrelated to study, coding tasks unrelated to the IB syllabus, recipes,
travel planning, current events, romance/relationship advice, medical/legal
advice, jokes, role-play.

Examples that ARE allowed: "explain glycolysis", "summarise my Bio A1.1 notes",
"what's the formula for the binomial theorem", "how do I add a recurring task",
"what does 'Relearning' mean", "give me a 3-week plan for Chem IA", "summarise
the file I uploaded for TOK".

# Behaviour inside scope
- Be concise, warm, and proactive.
- When the student asks you to do something the app supports (add a task, mark
  a topic done, change availability, etc.) call the matching tool — don't just
  describe what you would do.
- When asked about a concept, FIRST call `search_notes` to see whether the
  student already has notes or uploaded files on it, and ground your answer in
  those. Only then add general explanation.
- If you call a tool, follow up with a short confirmation in plain language.
"""


# ---------- helpers ----------

def _find_subject(db: Session, name: str) -> Subject | None:
    name_l = name.strip().lower()
    for s in db.scalars(select(Subject)).all():
        if s.name.lower() == name_l or name_l in s.name.lower():
            return s
    return None


def _find_topic(db: Session, subject: Subject, title_or_code: str) -> Topic | None:
    q = title_or_code.strip().lower()
    for t in subject.topics:
        if t.code.lower() == q or t.title.lower() == q or q in t.title.lower():
            return t
    return None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# ---------- tool dispatch ----------

def _find_topic_for_user(db: Session, subject: Subject, title_or_code: str, user_id: int | None) -> Topic | None:
    q = title_or_code.strip().lower()
    candidates = subject.topics
    if user_id is not None:
        candidates = [t for t in candidates if t.owner_id == user_id]
    for t in candidates:
        if t.code.lower() == q or t.title.lower() == q or q in t.title.lower():
            return t
    return None


def execute_tool(
    db: Session, name: str, args: dict[str, Any], user_id: int | None = None,
) -> dict[str, Any]:
    if name == "create_task":
        subject = _find_subject(db, args["subject"]) if args.get("subject") else None
        task = Task(
            owner_id=user_id,
            title=args["title"],
            subject_id=subject.id if subject else None,
            due_date=_parse_date(args.get("due_date")),
            est_minutes=args.get("est_minutes", 30),
        )
        db.add(task)
        db.commit()
        return {"ok": True, "task_id": task.id}

    if name == "add_deadline":
        subject = _find_subject(db, args["subject"]) if args.get("subject") else None
        d = Deadline(
            owner_id=user_id,
            kind=args["kind"],
            title=args["title"],
            subject_id=subject.id if subject else None,
            due_date=_parse_date(args["due_date"]),
        )
        db.add(d)
        db.commit()
        return {"ok": True, "deadline_id": d.id}

    if name == "mark_topic_completed":
        subject = _find_subject(db, args["subject"])
        if not subject:
            return {"ok": False, "error": f"Subject '{args['subject']}' not found."}
        topic = _find_topic_for_user(db, subject, args["topic_title_or_code"], user_id)
        if not topic:
            topic = Topic(owner_id=user_id, subject_id=subject.id, title=args["topic_title_or_code"])
            db.add(topic)
            db.flush()
        completed_on_d = _parse_date(args.get("completed_on")) or date.today()
        scheduler.seed_completed_topic(
            topic, datetime.combine(completed_on_d, datetime.min.time()), args["recall"]
        )
        db.commit()
        return {"ok": True, "topic_id": topic.id, "next_due": topic.due.isoformat() if topic.due else None}

    if name == "review_topic":
        subject = _find_subject(db, args["subject"])
        if not subject:
            return {"ok": False, "error": f"Subject '{args['subject']}' not found."}
        topic = _find_topic_for_user(db, subject, args["topic_title_or_code"], user_id)
        if not topic:
            return {"ok": False, "error": "Topic not found."}
        scheduler.review_topic(topic, args["rating"])
        db.commit()
        return {"ok": True, "next_due": topic.due.isoformat() if topic.due else None}

    if name == "add_topic":
        subject = _find_subject(db, args["subject"])
        if not subject:
            return {"ok": False, "error": f"Subject '{args['subject']}' not found."}
        topic = Topic(
            owner_id=user_id,
            subject_id=subject.id,
            code=args.get("code", ""),
            title=args["title"],
            ib_weight=args.get("ib_weight", 3),
        )
        db.add(topic)
        db.commit()
        return {"ok": True, "topic_id": topic.id}

    if name == "set_availability":
        from datetime import time as dtime
        del_q = select(AvailabilityRule)
        if user_id is not None:
            del_q = del_q.where(AvailabilityRule.owner_id == user_id)
        for r in db.scalars(del_q).all():
            db.delete(r)
        for rule in args["rules"]:
            sh, sm = [int(x) for x in rule["start_time"].split(":")]
            eh, em = [int(x) for x in rule["end_time"].split(":")]
            db.add(
                AvailabilityRule(
                    owner_id=user_id,
                    weekday=rule["weekday"],
                    start_time=dtime(sh, sm),
                    end_time=dtime(eh, em),
                )
            )
        db.commit()
        return {"ok": True, "rules_count": len(args["rules"])}

    if name == "list_subjects":
        # Topic counts are per-user.
        out = []
        for s in db.scalars(select(Subject)).all():
            count = len([t for t in s.topics if user_id is None or t.owner_id == user_id])
            out.append({"name": s.name, "level": s.level, "topics": count})
        return {"subjects": out}

    if name == "list_topics":
        subject = _find_subject(db, args["subject"])
        if not subject:
            return {"ok": False, "error": "Subject not found."}
        topics = subject.topics
        if user_id is not None:
            topics = [t for t in topics if t.owner_id == user_id]
        return {
            "topics": [
                {"code": t.code, "title": t.title, "due": t.due.isoformat() if t.due else None}
                for t in topics
            ]
        }

    if name == "search_notes":
        q = args["query"].lower().strip()
        subject_filter = _find_subject(db, args["subject"]) if args.get("subject") else None
        hits: list[dict[str, Any]] = []

        # 1) Topic notes (student's own writing)
        topic_q = select(Topic)
        if user_id is not None:
            topic_q = topic_q.where(Topic.owner_id == user_id)
        if subject_filter:
            topic_q = topic_q.where(Topic.subject_id == subject_filter.id)
        for t in db.scalars(topic_q).all():
            haystack = f"{t.code} {t.title}\n{t.notes or ''}".lower()
            if q and q in haystack:
                idx = haystack.find(q)
                source = t.notes or t.title
                start = max(0, idx - 200)
                end = min(len(source), idx + 400)
                hits.append(
                    {
                        "kind": "topic_notes",
                        "subject": t.subject.name if t.subject else None,
                        "topic": f"{t.code} {t.title}".strip(),
                        "snippet": source[start:end] if source else t.title,
                    }
                )
            if len(hits) >= 8:
                break

        # 2) Task notes
        if len(hits) < 8:
            task_q = select(Task)
            if user_id is not None:
                task_q = task_q.where(Task.owner_id == user_id)
            if subject_filter:
                task_q = task_q.where(Task.subject_id == subject_filter.id)
            for tk in db.scalars(task_q).all():
                hay = f"{tk.title}\n{tk.notes or ''}".lower()
                if q and q in hay:
                    src = tk.notes or tk.title
                    idx = hay.find(q)
                    start = max(0, idx - 200)
                    end = min(len(src), idx + 400)
                    hits.append(
                        {
                            "kind": "task_notes",
                            "task": tk.title,
                            "subject": tk.subject.name if tk.subject else None,
                            "status": tk.status,
                            "snippet": src[start:end] if src else tk.title,
                        }
                    )
                if len(hits) >= 8:
                    break

        # 3) Uploaded files (topic, task, or subject attachments)
        if len(hits) < 8:
            file_q = select(NoteFile)
            if user_id is not None:
                file_q = file_q.where(NoteFile.owner_id == user_id)
            if subject_filter:
                file_q = file_q.where(NoteFile.subject_id == subject_filter.id)
            for nf in db.scalars(file_q).all():
                if not nf.extracted_text:
                    continue
                text = nf.extracted_text.lower()
                idx = text.find(q)
                if idx >= 0:
                    start = max(0, idx - 200)
                    end = min(len(nf.extracted_text), idx + 400)
                    hits.append(
                        {
                            "kind": "uploaded_file",
                            "filename": nf.filename,
                            "attached_to": "task" if nf.task_id else ("topic" if nf.topic_id else "subject"),
                            "snippet": nf.extracted_text[start:end],
                        }
                    )
                if len(hits) >= 8:
                    break

        return {"hits": hits}

    if name == "get_topic_notes":
        subject = _find_subject(db, args["subject"])
        if not subject:
            return {"ok": False, "error": "Subject not found."}
        topic = _find_topic_for_user(db, subject, args["topic_title_or_code"], user_id)
        if not topic:
            return {"ok": False, "error": "Topic not found."}
        file_q = select(NoteFile).where(NoteFile.topic_id == topic.id)
        if user_id is not None:
            file_q = file_q.where(NoteFile.owner_id == user_id)
        files = db.scalars(file_q).all()
        return {
            "topic": f"{topic.code} {topic.title}".strip(),
            "subject": subject.name,
            "notes": topic.notes or "",
            "files": [
                {
                    "filename": nf.filename,
                    "extracted_text": (nf.extracted_text or "")[:4000],
                }
                for nf in files
            ],
        }

    if name == "list_tasks":
        status = args.get("status", "open")
        subject_filter = _find_subject(db, args["subject"]) if args.get("subject") else None
        query = (args.get("query") or "").strip().lower()

        stmt = select(Task)
        if user_id is not None:
            stmt = stmt.where(Task.owner_id == user_id)
        if status in ("open", "done"):
            stmt = stmt.where(Task.status == status)
        if subject_filter:
            stmt = stmt.where(Task.subject_id == subject_filter.id)
        rows = list(db.scalars(stmt.order_by(Task.scheduled_for.desc().nullslast(), Task.id.desc())))
        if query:
            rows = [
                t for t in rows
                if query in (t.title or "").lower() or query in (t.notes or "").lower()
            ]
        out = []
        for t in rows[:30]:
            file_count = db.scalar(
                select(func.count(NoteFile.id)).where(NoteFile.task_id == t.id)
            ) or 0
            out.append(
                {
                    "id": t.id,
                    "title": t.title,
                    "subject": t.subject.name if t.subject else None,
                    "status": t.status,
                    "progress_pct": t.progress_pct,
                    "scheduled_for": t.scheduled_for.isoformat() if t.scheduled_for else None,
                    "est_minutes": t.est_minutes,
                    "notes": (t.notes or "")[:1000],
                    "attachments": file_count,
                }
            )
        return {"count": len(rows), "tasks": out}

    return {"ok": False, "error": f"Unknown tool {name}"}


# ---------- main chat ----------

def _client(api_key: str | None):
    """Build an Anthropic client. Falls back to settings key if user has none."""
    key = (api_key or "").strip() or settings.anthropic_api_key
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key)


def chat(
    db: Session,
    user_message: str,
    api_key: str | None = None,
    user_id: int | None = None,
    session_id: int | None = None,
) -> str:
    """Run a chat turn. Scoped per ``user_id`` and chat session."""
    db.add(
        ChatMessage(
            owner_id=user_id,
            session_id=session_id,
            role="user",
            content=user_message,
        )
    )
    db.commit()

    client = _client(api_key)
    if client is None:
        reply = (
            "The AI Coach is part of the premium plan and is not currently "
            "enabled on your account. Please contact your administrator to "
            "upgrade your access."
        )
        db.add(ChatMessage(owner_id=user_id, role="assistant", content=reply))
        db.commit()
        return reply

    hist_q = select(ChatMessage).order_by(ChatMessage.id.desc()).limit(20)
    if user_id is not None:
        hist_q = select(ChatMessage).where(ChatMessage.owner_id == user_id)
        if session_id is not None:
            hist_q = hist_q.where(ChatMessage.session_id == session_id)
        hist_q = hist_q.order_by(ChatMessage.id.desc()).limit(20)
    history = list(db.scalars(hist_q))[::-1]
    messages = [
        {"role": m.role, "content": m.content}
        for m in history
        if m.role in ("user", "assistant") and isinstance(m.content, str)
    ]

    system = SYSTEM_PROMPT.format(today=date.today().isoformat())

    model_candidates = get_anthropic_model_candidates(settings.anthropic_model)
    final_text = ""
    last_exception: Exception | None = None
    try:
        for model_name in model_candidates:
            try:
                for _ in range(5):
                    resp = client.messages.create(
                        model=model_name,
                        max_tokens=1024,
                        system=system,
                        tools=TOOLS,
                        messages=messages,
                    )

                    tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
                    text_blocks = [b for b in resp.content if getattr(b, "type", None) == "text"]

                    if not tool_uses:
                        final_text = "\n".join(b.text for b in text_blocks).strip()
                        break

                    messages.append(
                        {"role": "assistant", "content": [b.model_dump() for b in resp.content]}
                    )

                    tool_results = []
                    for tu in tool_uses:
                        try:
                            result = execute_tool(db, tu.name, tu.input or {}, user_id=user_id)
                        except Exception as ex:  # don't let a tool crash the chat
                            db.rollback()
                            result = {"ok": False, "error": str(ex)}
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tu.id,
                                "content": json.dumps(result),
                            }
                        )
                    messages.append({"role": "user", "content": tool_results})
                break
            except Exception as ex:
                msg = str(ex)
                last_exception = ex
                if "not_found_error" in msg or ("model:" in msg and "not found" in msg):
                    continue
                raise
        else:
            if last_exception is not None:
                raise last_exception
    except Exception as ex:
        # Surface clean error to the UI; common cases: invalid api key, rate limit, network.
        msg = str(ex)
        if "authentication_error" in msg or "invalid x-api-key" in msg or "401" in msg:
            final_text = (
                "⚠️ Anthropic rejected the API key on your account. Update it in "
                "Account settings."
            )
        elif "rate_limit" in msg or "429" in msg:
            final_text = "⚠️ Anthropic rate limit hit. Try again in a moment."
        elif "not_found_error" in msg or ("model:" in msg and "not found" in msg):
            final_text = (
                "⚠️ AI Coach error: configured Anthropic model was not found or unavailable. "
                "The app can use claude-3.5, claude-instant-1, or claude-4-mini, but your API key must have access. "
                "If none of those models are available, update your Anthropic account or use a different key."
            )
        else:
            final_text = f"⚠️ AI Coach error: {msg[:300]}"

    if not final_text:
        final_text = "Done."
    db.add(
        ChatMessage(
            owner_id=user_id,
            session_id=session_id,
            role="assistant",
            content=final_text,
        )
    )
    db.commit()
    return final_text
