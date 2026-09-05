from __future__ import annotations

import json
import secrets
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.base import BaseHTTPMiddleware

from app import ai, auth, notes, planner, scheduler, study_planner
from app.config import get_settings
from app.db import Base, SessionLocal, apply_lightweight_migrations, engine, get_db
from app.models import (
    AvailabilityException,
    AvailabilityRule,
    ChatMessage,
    ChatSession,
    Deadline,
    NoteFile,
    PlannerFixedRule,
    RevisionDeskState,
    StudyPlannerBlock,
    StudyPlannerRevisionLink,
    StudySession,
    Subject,
    Task,
    Topic,
    User,
)
from app.seed import run as seed_run

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Maznify")
UPLOADS_DIR = notes.UPLOAD_DIR
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR), check_dir=False), name="uploads")


@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(engine)
    apply_lightweight_migrations()
    with SessionLocal() as db:
        # Always run seed (it's idempotent and updates icons/levels/sort_order)
        if not db.scalar(select(Subject).limit(1)):
            seed_run()
        auth.ensure_admin_user(db)
        # Top up every user's curriculum to match the latest CURRICULA. Adds
        # only missing entries; preserves existing notes, sub-units, FSRS state.
        auth.provision_all_users(db)


# ---------- auth gate ----------

PUBLIC_PATHS = {"/login", "/logout"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)
        uid = auth.read_session_user_id(request)
        if not uid:
            # No bfcache, no proxy cache, no stored copy — back button after
            # logout must hit the server again and get redirected to /login.
            resp = RedirectResponse(f"/login?next={path}", status_code=303)
            _apply_no_cache(resp)
            return resp
        request.state.user_id = uid
        response = await call_next(request)
        _apply_no_cache(response)
        return response


def _apply_no_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


app.add_middleware(AuthMiddleware)


def _require_user(request: Request, db: Session) -> User:
    user = auth.get_current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _require_admin(request: Request, db: Session) -> User:
    user = _require_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def _uid(request: Request) -> int:
    """Current user id from session — relies on AuthMiddleware having set it."""
    uid = getattr(request.state, "user_id", None)
    if uid is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return int(uid)


def _build_topics_by_subject(db: Session, user_id: int) -> dict[int, list[dict]]:
    """Build a {subject_id: [{id, label}, ...]} structure for cascading topic
    selects, using only the given user's topics (parents + indented children)."""
    topics_by_subject: dict[int, list[dict]] = {}
    user_topics = list(db.scalars(select(Topic).where(Topic.owner_id == user_id)))
    by_subject: dict[int, list[Topic]] = {}
    for t in user_topics:
        by_subject.setdefault(t.subject_id, []).append(t)
    for sid, ts in by_subject.items():
        rows: list[dict] = []
        parents = sorted([t for t in ts if t.parent_id is None],
                         key=lambda t: (t.code or "", t.title))
        children_by_parent: dict[int, list[Topic]] = {}
        for t in ts:
            if t.parent_id is not None:
                children_by_parent.setdefault(t.parent_id, []).append(t)
        for p in parents:
            rows.append({"id": p.id, "label": (f"{p.code} " if p.code else "") + p.title})
            for c in sorted(children_by_parent.get(p.id, []),
                            key=lambda t: (t.code or "", t.title)):
                rows.append({
                    "id": c.id,
                    "label": "    ↳ " + ((f"{c.code} " if c.code else "") + c.title),
                })
        topics_by_subject[sid] = rows
    return topics_by_subject


# Make a few helpers available in templates
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _common_ctx(request: Request, db: Session) -> dict:
    return {
        "request": request,
        "subjects": db.scalars(
            select(Subject).order_by(Subject.sort_order, Subject.name)
        ).all(),
        "today": date.today(),
        "WEEKDAYS": WEEKDAYS,
        "current_user": auth.get_current_user(request, db),
    }


# ---------- dashboard ----------
 
@app.get("/revision-desk", response_class=HTMLResponse)
def revision_desk(request: Request, db: Session = Depends(get_db)):
    _uid(request)
    ctx = _common_ctx(request, db)
    return templates.TemplateResponse("revision_desk.html", ctx)


@app.get("/revision-desk/state")
def revision_desk_state(request: Request, db: Session = Depends(get_db)):
    try:
        uid = _uid(request)
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error in _uid: {e}")
        raise HTTPException(status_code=500, detail=f"Auth error: {str(e)}")
    
    try:
        row = db.scalar(select(RevisionDeskState).where(RevisionDeskState.owner_id == uid))
        if row and row.state:
            try:
                state = json.loads(row.state)
            except Exception as e:
                print(f"JSON parse error: {e}")
                state = {"subjects": []}
        else:
            state = {"subjects": []}
        return {"state": state}
    except Exception as e:
        print(f"Error in revision_desk_state: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.post("/revision-desk/state")
async def save_revision_desk_state(request: Request, db: Session = Depends(get_db)):
    try:
        uid = _uid(request)
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error in _uid (POST): {e}")
        raise HTTPException(status_code=500, detail=f"Auth error: {str(e)}")
    
    try:
        # Parse incoming JSON
        state = await request.json()
        print(f"Received state for user {uid}, size: {len(json.dumps(state))} bytes")
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    
    if not isinstance(state, dict):
        raise HTTPException(status_code=400, detail="Invalid state payload: must be object")
    
    try:
        # Serialize state to JSON string
        state_json = json.dumps(state)
        print(f"Serialized state to {len(state_json)} bytes")
    except Exception as e:
        print(f"Error serializing state: {e}")
        raise HTTPException(status_code=400, detail=f"State JSON error: {str(e)}")
    
    try:
        # Query or create revision desk state
        row = db.scalar(select(RevisionDeskState).where(RevisionDeskState.owner_id == uid))
        if row:
            print(f"Updating existing revision_desk_states for user {uid}")
            row.state = state_json
            row.updated_at = datetime.utcnow()
        else:
            print(f"Creating new revision_desk_states for user {uid}")
            new_state = RevisionDeskState(
                owner_id=uid,
                state=state_json,
                updated_at=datetime.utcnow(),
            )
            db.add(new_state)
        
        # Commit to database
        db.commit()
        print(f"Successfully saved state for user {uid}")
        return {"ok": True}
    except Exception as e:
        print(f"Error in database operation: {type(e).__name__}: {e}")
        try:
            db.rollback()
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.post("/revision-desk/attachments/upload")
async def revision_desk_attachment_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    uid = _uid(request)
    filename = Path(file.filename or "upload").name
    stored_filename = f"{uid}-{int(datetime.utcnow().timestamp() * 1000)}-{filename}"
    dest_path = notes.UPLOAD_DIR / stored_filename
    content = await file.read()
    dest_path.write_bytes(content)
    return {"ok": True, "filename": filename, "attachment": f"/uploads/{stored_filename}"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    plan = planner.build_plan(db, date.today(), user_id=uid)
    deadlines = list(
        db.scalars(
            select(Deadline)
            .where(Deadline.owner_id == uid)
            .where(Deadline.due_date >= date.today())
            .where(Deadline.progress_pct < 100)
            .order_by(Deadline.due_date)
            .limit(8)
        )
    )
    # crude retention per subject — only count this user's topics
    retention = []
    user_topics_by_subject: dict[int, list[Topic]] = {}
    for t in db.scalars(select(Topic).where(Topic.owner_id == uid)).all():
        user_topics_by_subject.setdefault(t.subject_id, []).append(t)
    for s in db.scalars(select(Subject).order_by(Subject.sort_order, Subject.name)).all():
        my_topics = user_topics_by_subject.get(s.id, [])
        in_revision = [t for t in my_topics if t.state]
        total = len(my_topics)
        if not in_revision:
            retention.append({"subject": s, "pct": None, "studied": 0, "total": total})
            continue
        future = sum(1 for t in in_revision if t.due and t.due > datetime.utcnow())
        pct = round(100 * future / len(in_revision))
        retention.append({"subject": s, "pct": pct, "studied": len(in_revision), "total": total})

    items_by_subject: dict[str, list] = {r["subject"].name: [] for r in retention}
    items_by_subject["(no subject)"] = []
    for item in plan.items:
        key = item.subject_name or "(no subject)"
        items_by_subject.setdefault(key, []).append(item)

    topic_last_rating: dict[int, str] = {}
    review_topic_ids = [i.topic_id for i in plan.items if i.kind == "review" and i.topic_id]
    if review_topic_ids:
        latest_sessions = db.scalars(
            select(StudySession)
            .where(StudySession.owner_id == uid)
            .where(StudySession.topic_id.in_(review_topic_ids))
            .order_by(StudySession.id.desc())
        ).all()
        for s in latest_sessions:
            if s.topic_id not in topic_last_rating and s.rating:
                topic_last_rating[s.topic_id] = s.rating

    ctx = _common_ctx(request, db)
    ctx.update(
        {
            "plan": plan,
            "deadlines": deadlines,
            "retention": retention,
            "items_by_subject": items_by_subject,
            "topic_last_rating": topic_last_rating,
        }
    )
    return templates.TemplateResponse("dashboard.html", ctx)


# ---------- summary dashboard ----------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_summary(request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday
    week_end = week_start + timedelta(days=6)

    # ----- subject coverage stats (per-user topics only) -----
    user_topics_by_subject: dict[int, list[Topic]] = {}
    for t in db.scalars(select(Topic).where(Topic.owner_id == uid)).all():
        user_topics_by_subject.setdefault(t.subject_id, []).append(t)
    subject_stats: list[dict] = []
    for s in db.scalars(
        select(Subject).order_by(Subject.sort_order, Subject.name)
    ).all():
        my_topics = user_topics_by_subject.get(s.id, [])
        total = len(my_topics)
        studied = sum(1 for t in my_topics if t.state)
        due_now = sum(
            1 for t in my_topics
            if t.due and t.due <= datetime.utcnow()
        )
        coverage = round(100 * studied / total) if total else 0
        subject_stats.append({
            "subject": s,
            "total_topics": total,
            "studied": studied,
            "due_now": due_now,
            "coverage": coverage,
        })

    # ----- this week's study time + sessions (per day, last 7 days) -----
    week_range_start = datetime.combine(week_start, time.min)
    week_range_end = datetime.combine(week_end, time.max)
    week_sessions = list(
        db.scalars(
            select(StudySession)
            .where(StudySession.owner_id == uid)
            .where(StudySession.started_at >= week_range_start)
            .where(StudySession.started_at <= week_range_end)
        )
    )
    week_minutes = sum(s.minutes or 0 for s in week_sessions)
    week_count = len(week_sessions)

    # daily breakdown for sparkline
    daily_minutes: list[dict] = []
    cur = week_start
    while cur <= week_end:
        m = sum(s.minutes or 0 for s in week_sessions if s.started_at.date() == cur)
        daily_minutes.append({
            "date": cur,
            "weekday": WEEKDAYS[cur.weekday()],
            "minutes": m,
        })
        cur += timedelta(days=1)
    max_minutes = max((d["minutes"] for d in daily_minutes), default=0)

    # ----- streak (consecutive days with at least one session, ending today or yesterday) -----
    last_30_start = datetime.combine(today - timedelta(days=30), time.min)
    last_30 = db.scalars(
        select(StudySession)
        .where(StudySession.owner_id == uid)
        .where(StudySession.started_at >= last_30_start)
    ).all()
    days_with_study = {s.started_at.date() for s in last_30}
    streak = 0
    cursor = today
    while cursor in days_with_study:
        streak += 1
        cursor -= timedelta(days=1)
    if streak == 0 and (today - timedelta(days=1)) in days_with_study:
        # Allow streak ending yesterday so the badge stays useful in the morning
        cursor = today - timedelta(days=1)
        while cursor in days_with_study:
            streak += 1
            cursor -= timedelta(days=1)

    # ----- review rating mix this week -----
    rating_counts = {"again": 0, "hard": 0, "good": 0, "easy": 0}
    for s in week_sessions:
        if s.rating in rating_counts:
            rating_counts[s.rating] += 1

    # ----- upcoming deadlines (next 30 days) -----
    deadlines = list(
        db.scalars(
            select(Deadline)
            .where(Deadline.owner_id == uid)
            .where(Deadline.due_date >= today, Deadline.due_date <= today + timedelta(days=30))
            .where(Deadline.progress_pct < 100)
            .order_by(Deadline.due_date)
        )
    )

    # ----- task summary -----
    open_tasks = list(
        db.scalars(
            select(Task).where(Task.owner_id == uid, Task.status == "open")
        )
    )
    overdue_tasks = [
        t for t in open_tasks
        if t.scheduled_for and t.scheduled_for < datetime.combine(today, time.min)
    ]
    today_tasks = [
        t for t in open_tasks
        if t.scheduled_for and t.scheduled_for.date() == today
    ]

    # ----- "today" plan totals -----
    today_plan = planner.build_plan(db, today, user_id=uid)

    # ----- upcoming date overrides (next 30 days), grouped by date -----
    overrides = list(
        db.scalars(
            select(AvailabilityException)
            .where(AvailabilityException.owner_id == uid)
            .where(AvailabilityException.on_date >= today)
            .where(AvailabilityException.on_date <= today + timedelta(days=30))
            .order_by(AvailabilityException.on_date, AvailabilityException.start_time)
        )
    )
    overrides_grouped: list[dict] = []
    by_d: dict[date, list[AvailabilityException]] = {}
    for ex in overrides:
        by_d.setdefault(ex.on_date, []).append(ex)
    for d, items in sorted(by_d.items()):
        overrides_grouped.append({"date": d, "overrides": items})

    ctx = _common_ctx(request, db)
    ctx.update({
        "subject_stats": subject_stats,
        "daily_minutes": daily_minutes,
        "max_minutes": max_minutes,
        "week_minutes": week_minutes,
        "week_count": week_count,
        "week_start": week_start,
        "week_end": week_end,
        "streak": streak,
        "rating_counts": rating_counts,
        "deadlines": deadlines,
        "open_tasks_count": len(open_tasks),
        "overdue_tasks": overdue_tasks,
        "today_tasks": today_tasks,
        "today_plan": today_plan,
        "overrides_grouped": overrides_grouped,
    })
    return templates.TemplateResponse("dashboard_summary.html", ctx)


@app.get("/choose", response_class=HTMLResponse)
def choose_after_login(request: Request, db: Session = Depends(get_db)):
    """Simple landing page allowing the signed-in user to choose Study Mate or Revision Desk."""
    _uid(request)  # ensure user is authenticated; middleware will redirect to login otherwise
    ctx = _common_ctx(request, db)
    return templates.TemplateResponse("choose.html", ctx)


# ---------- subjects + topics ----------

@app.get("/subjects", response_class=HTMLResponse)
def subjects_index(request: Request, db: Session = Depends(get_db)):
    """Browse all subjects as cards. Each card links to its curriculum page."""
    uid = _uid(request)
    user_topics_by_subject: dict[int, list[Topic]] = {}
    for t in db.scalars(select(Topic).where(Topic.owner_id == uid)).all():
        user_topics_by_subject.setdefault(t.subject_id, []).append(t)
    rows = []
    for s in db.scalars(select(Subject).order_by(Subject.sort_order, Subject.name)).all():
        my = user_topics_by_subject.get(s.id, [])
        total = len(my)
        studied = sum(1 for t in my if t.state)
        due_now = sum(1 for t in my if t.due and t.due <= datetime.utcnow())
        coverage = round(100 * studied / total) if total else 0
        rows.append({
            "subject": s,
            "total": total,
            "studied": studied,
            "due_now": due_now,
            "coverage": coverage,
        })
    ctx = _common_ctx(request, db)
    ctx["subject_rows"] = rows
    return templates.TemplateResponse("subjects.html", ctx)


@app.get("/subjects/{subject_id}", response_class=HTMLResponse)
def subject_detail(subject_id: int, request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    subject = db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404)

    # Only this user's topics for this subject
    user_topics = list(
        db.scalars(
            select(Topic)
            .where(Topic.subject_id == subject_id)
            .where(Topic.owner_id == uid)
        )
    )
    topic_ids = [t.id for t in user_topics]

    files_by_topic: dict[int, list[NoteFile]] = {}
    if topic_ids:
        for nf in db.scalars(
            select(NoteFile).where(
                NoteFile.owner_id == uid,
                NoteFile.subject_id == subject_id,
                NoteFile.topic_id.in_(topic_ids),
            )
        ).all():
            files_by_topic.setdefault(nf.topic_id, []).append(nf)

    subject_deadlines = list(
        db.scalars(
            select(Deadline)
            .where(Deadline.owner_id == uid)
            .where(Deadline.subject_id == subject_id)
            .order_by(Deadline.due_date)
        )
    )

    topic_last_rating: dict[int, str] = {}
    if topic_ids:
        latest = db.scalars(
            select(StudySession)
            .where(StudySession.owner_id == uid)
            .where(StudySession.topic_id.in_(topic_ids))
            .order_by(StudySession.id.desc())
        ).all()
        for s in latest:
            if s.topic_id not in topic_last_rating and s.rating:
                topic_last_rating[s.topic_id] = s.rating

    ctx = _common_ctx(request, db)
    ctx["subject"] = subject
    ctx["user_topics"] = user_topics
    ctx["files_by_topic"] = files_by_topic
    ctx["subject_deadlines"] = subject_deadlines
    ctx["topic_last_rating"] = topic_last_rating
    return templates.TemplateResponse("subject.html", ctx)


@app.get("/deadlines", response_class=HTMLResponse)
def deadlines_view(
    request: Request,
    q: str = "",
    status: str = "all",  # "all" | "open" | "done"
    subject_id: str = "",
    date_from: str = "",
    date_to: str = "",
    db: Session = Depends(get_db),
):
    """Searchable deadlines summary — edit, delete, update progress."""
    uid = _uid(request)
    stmt = select(Deadline).where(Deadline.owner_id == uid)
    if subject_id:
        try:
            stmt = stmt.where(Deadline.subject_id == int(subject_id))
        except ValueError:
            pass
    df: date | None = None
    dt: date | None = None
    try:
        if date_from:
            df = date.fromisoformat(date_from)
        if date_to:
            dt = date.fromisoformat(date_to)
    except ValueError:
        df = dt = None
    if df:
        stmt = stmt.where(Deadline.due_date >= df)
    if dt:
        stmt = stmt.where(Deadline.due_date <= dt)

    rows = list(db.scalars(stmt.order_by(Deadline.due_date)))
    if status == "open":
        rows = [d for d in rows if (d.progress_pct or 0) < 100]
    elif status == "done":
        rows = [d for d in rows if (d.progress_pct or 0) >= 100]

    if q:
        ql = q.strip().lower()
        rows = [
            d for d in rows
            if ql in (d.title or "").lower()
            or (d.subject and ql in d.subject.name.lower())
            or ql in (d.kind or "").lower()
        ]

    topics_by_subject = _build_topics_by_subject(db, uid)

    ctx = _common_ctx(request, db)
    ctx.update({
        "deadlines": rows,
        "q": q,
        "status_filter": status,
        "subject_filter_id": subject_id,
        "date_from": date_from,
        "date_to": date_to,
        "topics_by_subject": topics_by_subject,
    })
    return templates.TemplateResponse("deadlines.html", ctx)


@app.post("/deadlines/{deadline_id}/edit")
def deadline_edit(
    deadline_id: int,
    request: Request,
    title: str = Form(""),
    kind: str = Form(""),
    subject_id: str = Form(""),
    topic_id: str = Form(""),
    due_date: str = Form(""),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    d = db.get(Deadline, deadline_id)
    if not d or d.owner_id != uid:
        raise HTTPException(404)
    if title.strip():
        d.title = title.strip()
    if kind.strip():
        d.kind = kind.strip()
    d.subject_id = int(subject_id) if subject_id else None
    d.topic_id = int(topic_id) if topic_id else None
    if due_date:
        try:
            d.due_date = date.fromisoformat(due_date)
        except ValueError:
            pass
    db.commit()
    return RedirectResponse(request.headers.get("referer") or "/deadlines", status_code=303)


@app.post("/deadlines/{deadline_id}/delete")
def delete_deadline(deadline_id: int, request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    d = db.get(Deadline, deadline_id)
    if d and d.owner_id == uid:
        db.delete(d)
        db.commit()
    return RedirectResponse(request.headers.get("referer") or "/plan", status_code=303)


@app.post("/deadlines/{deadline_id}/progress")
def deadline_progress(
    deadline_id: int,
    request: Request,
    progress_pct: int = Form(...),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    d = db.get(Deadline, deadline_id)
    if not d or d.owner_id != uid:
        raise HTTPException(404)
    d.progress_pct = max(0, min(100, int(progress_pct)))
    db.commit()
    return RedirectResponse(request.headers.get("referer") or "/plan", status_code=303)


@app.post("/subjects/{subject_id}/topics")
def add_topic(
    subject_id: int,
    request: Request,
    code: str = Form(""),
    title: str = Form(...),
    ib_weight: int = Form(3),
    parent_id: str = Form(""),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    subject = db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404)
    pid: int | None = None
    if parent_id:
        try:
            pid = int(parent_id)
            parent = db.get(Topic, pid)
            if not parent or parent.subject_id != subject_id or parent.owner_id != uid:
                pid = None
        except ValueError:
            pid = None
    db.add(
        Topic(
            owner_id=uid,
            subject_id=subject.id,
            parent_id=pid,
            code=code.strip(),
            title=title.strip(),
            ib_weight=ib_weight,
        )
    )
    db.commit()
    return RedirectResponse(f"/subjects/{subject_id}", status_code=303)


@app.post("/topics/{topic_id}/subtopic")
def add_subtopic(
    topic_id: int,
    request: Request,
    code: str = Form(""),
    title: str = Form(...),
    ib_weight: int = Form(3),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    parent = db.get(Topic, topic_id)
    if not parent or parent.owner_id != uid:
        raise HTTPException(404)
    db.add(
        Topic(
            owner_id=uid,
            subject_id=parent.subject_id,
            parent_id=parent.id,
            code=code.strip(),
            title=title.strip(),
            ib_weight=ib_weight,
        )
    )
    db.commit()
    return RedirectResponse(f"/subjects/{parent.subject_id}", status_code=303)


@app.post("/topics/{topic_id}/notes")
def save_topic_notes(
    topic_id: int,
    request: Request,
    notes_text: str = Form(""),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    topic = db.get(Topic, topic_id)
    if not topic or topic.owner_id != uid:
        raise HTTPException(404)
    topic.notes = notes_text
    db.commit()
    return RedirectResponse(f"/subjects/{topic.subject_id}#topic-{topic.id}", status_code=303)


@app.post("/topics/{topic_id}/upload")
async def topic_upload(
    topic_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    topic = db.get(Topic, topic_id)
    if not topic or topic.owner_id != uid:
        raise HTTPException(404)
    data = await file.read()
    nf = notes.save_upload(
        db,
        file.filename or "upload",
        file.content_type or "application/octet-stream",
        data,
        topic.subject_id,
        topic.id,
    )
    nf.owner_id = uid
    db.commit()
    return RedirectResponse(f"/subjects/{topic.subject_id}#topic-{topic.id}", status_code=303)


@app.post("/topics/{topic_id}/complete")
def complete_topic(
    topic_id: int,
    request: Request,
    completed_on: str = Form(...),
    recall: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    topic = db.get(Topic, topic_id)
    if not topic or topic.owner_id != uid:
        raise HTTPException(404)
    completed_dt = datetime.combine(date.fromisoformat(completed_on), time(12, 0))
    scheduler.seed_completed_topic(topic, completed_dt, recall)  # type: ignore[arg-type]
    db.commit()
    return RedirectResponse(f"/subjects/{topic.subject_id}", status_code=303)


@app.post("/subjects/{subject_id}/bulk-complete")
async def bulk_complete_topics(
    subject_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Mark several previously-studied topics done in one click and seed FSRS."""
    uid = _uid(request)
    subject = db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404)
    form = await request.form()
    topic_ids = [int(v) for v in form.getlist("topic_ids")]
    completed_on = str(form.get("completed_on") or date.today().isoformat())
    recall = str(form.get("recall") or "solid")
    completed_dt = datetime.combine(date.fromisoformat(completed_on), time(12, 0))
    for tid in topic_ids:
        topic = db.get(Topic, tid)
        if not topic or topic.subject_id != subject_id or topic.owner_id != uid:
            continue
        scheduler.seed_completed_topic(topic, completed_dt, recall)  # type: ignore[arg-type]
    db.commit()
    return RedirectResponse(f"/subjects/{subject_id}", status_code=303)


@app.post("/topics/{topic_id}/review")
def review_topic_route(
    topic_id: int,
    request: Request,
    rating: str = Form(...),
    minutes: int = Form(25),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    topic = db.get(Topic, topic_id)
    if not topic or topic.owner_id != uid:
        raise HTTPException(404)
    scheduler.review_topic(topic, rating)  # type: ignore[arg-type]
    db.add(StudySession(
        owner_id=uid, topic_id=topic_id,
        started_at=datetime.utcnow(), minutes=minutes, rating=rating,
    ))
    db.commit()
    referer = request.headers.get("referer") or "/"
    sep = "&" if "?" in referer else "?"
    return RedirectResponse(f"{referer}{sep}celebrated=1", status_code=303)


# ---------- topic history & test logging ----------

@app.get("/topics/{topic_id}/history", response_class=HTMLResponse)
def topic_history(
    topic_id: int,
    request: Request,
    page: int = 1,
    per_page: int = 100,
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    topic = db.get(Topic, topic_id)
    if not topic or topic.owner_id != uid:
        raise HTTPException(404)

    page = max(1, page)
    per_page = max(10, min(200, per_page))
    offset = (page - 1) * per_page

    base_filter = (
        StudySession.owner_id == uid,
        StudySession.topic_id == topic_id,
    )

    totals_stmt = select(
        func.count(),
        func.coalesce(func.sum(StudySession.minutes), 0),
    ).where(*base_filter)
    total_sessions, total_minutes = db.execute(totals_stmt).one()

    sessions = list(
        db.scalars(
            select(StudySession)
            .where(*base_filter)
            .order_by(StudySession.started_at.desc())
            .limit(per_page)
            .offset(offset)
        )
    )

    session_count = len(sessions)
    rating_counts = {"again": 0, "hard": 0, "good": 0, "easy": 0}
    for s in sessions:
        if s.rating in rating_counts:
            rating_counts[s.rating] += 1

    intervals: list[int] = []
    for i in range(session_count - 1):
        later = sessions[i].started_at
        prev = sessions[i + 1].started_at
        try:
            intervals.append(max(0, (later - prev).days))
        except Exception:
            pass
    avg_interval = round(sum(intervals) / len(intervals), 1) if intervals else None

    try:
        threshold = int(topic.stability) if topic.stability else 7
    except Exception:
        threshold = 7
    on_time_count = sum(1 for d in intervals if d <= threshold) if intervals else 0
    on_time_pct = int(100 * on_time_count / len(intervals)) if intervals else None

    page_count = (total_sessions + per_page - 1) // per_page if total_sessions else 1
    showing_from = offset + 1 if total_sessions else 0
    showing_to = offset + session_count

    ctx = _common_ctx(request, db)
    ctx.update({
        "topic": topic,
        "sessions": sessions,
        "total_sessions": total_sessions,
        "total_minutes": total_minutes,
        "avg_interval": avg_interval,
        "on_time_pct": on_time_pct,
        "rating_counts": rating_counts,
        "page": page,
        "per_page": per_page,
        "page_count": page_count,
        "showing_from": showing_from,
        "showing_to": showing_to,
    })
    return templates.TemplateResponse("topic_history.html", ctx)


@app.post("/topics/{topic_id}/history")
def log_test_score(
    topic_id: int,
    request: Request,
    minutes: int = Form(0),
    test_score: float | None = Form(None),
    ib_score_type: str = Form(""),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    topic = db.get(Topic, topic_id)
    if not topic or topic.owner_id != uid:
        raise HTTPException(404)
    db.add(StudySession(
        owner_id=uid,
        topic_id=topic_id,
        started_at=datetime.utcnow(),
        minutes=int(minutes),
        rating=None,
        test_score=test_score,
        ib_score_type=ib_score_type,
    ))
    db.commit()
    return RedirectResponse(request.headers.get("referer") or f"/subjects/{topic.subject_id}", status_code=303)


# ---------- tasks ----------

@app.get("/tasks", response_class=HTMLResponse)
def tasks_view(
    request: Request,
    q: str = "",
    status: str = "all",
    subject_id: str = "",
    date_from: str = "",
    date_to: str = "",
    db: Session = Depends(get_db),
):
    """Searchable task list with filters."""
    uid = _uid(request)
    stmt = select(Task).where(Task.owner_id == uid)
    if status == "open":
        stmt = stmt.where(Task.status == "open")
    elif status == "done":
        stmt = stmt.where(Task.status == "done")
    if subject_id:
        try:
            stmt = stmt.where(Task.subject_id == int(subject_id))
        except ValueError:
            pass
    # Date range — match against scheduled_for (preferred) or due_date.
    df: date | None = None
    dt: date | None = None
    try:
        if date_from:
            df = date.fromisoformat(date_from)
        if date_to:
            dt = date.fromisoformat(date_to)
    except ValueError:
        df = dt = None
    if df:
        stmt = stmt.where(
            (Task.scheduled_for >= datetime.combine(df, time.min))
            | ((Task.scheduled_for.is_(None)) & (Task.due_date >= df))
        )
    if dt:
        stmt = stmt.where(
            (Task.scheduled_for <= datetime.combine(dt, time.max))
            | ((Task.scheduled_for.is_(None)) & (Task.due_date <= dt))
        )

    tasks = list(db.scalars(stmt.order_by(Task.scheduled_for.desc().nullslast(), Task.id.desc())))

    # In-memory search across title, subject name, and topic title (handles
    # "search by title, subject or unit" requirement on a single query box).
    if q:
        ql = q.strip().lower()
        def matches(t: Task) -> bool:
            if ql in (t.title or "").lower():
                return True
            if t.subject and ql in t.subject.name.lower():
                return True
            if t.topic_id:
                topic = db.get(Topic, t.topic_id)
                if topic and (
                    ql in (topic.title or "").lower()
                    or ql in (topic.code or "").lower()
                ):
                    return True
            if t.notes and ql in t.notes.lower():
                return True
            return False
        tasks = [t for t in tasks if matches(t)]

    files_by_task: dict[int, list[NoteFile]] = {}
    if tasks:
        ids = [t.id for t in tasks]
        for nf in db.scalars(
            select(NoteFile).where(NoteFile.owner_id == uid, NoteFile.task_id.in_(ids))
        ).all():
            files_by_task.setdefault(nf.task_id, []).append(nf)

    # Topic lookup per subject (this user's topics only) for the edit forms
    topics_by_subject = _build_topics_by_subject(db, uid)

    ctx = _common_ctx(request, db)
    ctx.update({
        "tasks": tasks,
        "q": q,
        "status_filter": status,
        "subject_filter_id": subject_id,
        "date_from": date_from,
        "date_to": date_to,
        "files_by_task": files_by_task,
        "topics_by_subject": topics_by_subject,
    })
    return templates.TemplateResponse("tasks.html", ctx)


@app.post("/tasks/{task_id}/edit")
def task_edit(
    task_id: int,
    request: Request,
    title: str = Form(""),
    notes_text: str = Form(""),
    subject_id: str = Form(""),
    topic_id: str = Form(""),
    scheduled_date: str = Form(""),
    scheduled_time: str = Form(""),
    est_minutes: int = Form(30),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    t = db.get(Task, task_id)
    if not t or t.owner_id != uid:
        raise HTTPException(404)
    if title.strip():
        t.title = title.strip()
    t.notes = notes_text or ""
    t.subject_id = int(subject_id) if subject_id else None
    t.topic_id = int(topic_id) if topic_id else None
    t.est_minutes = int(est_minutes) if est_minutes else 30
    if scheduled_date and scheduled_time:
        try:
            sd = date.fromisoformat(scheduled_date)
            sh, sm = [int(x) for x in scheduled_time.split(":")[:2]]
            t.scheduled_for = datetime.combine(sd, time(sh, sm))
            t.due_date = sd
        except (ValueError, IndexError):
            pass
    elif not scheduled_date and not scheduled_time:
        t.scheduled_for = None
    db.commit()
    return RedirectResponse(request.headers.get("referer") or "/tasks", status_code=303)


@app.post("/tasks/{task_id}/delete")
def task_delete(task_id: int, request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    t = db.get(Task, task_id)
    if t and t.owner_id == uid:
        for nf in db.scalars(select(NoteFile).where(NoteFile.task_id == task_id)).all():
            nf.task_id = None
        db.delete(t)
        db.commit()
    return RedirectResponse(request.headers.get("referer") or "/tasks", status_code=303)


@app.post("/tasks/{task_id}/upload")
async def task_upload(
    task_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    t = db.get(Task, task_id)
    if not t or t.owner_id != uid:
        raise HTTPException(404)
    data = await file.read()
    nf = notes.save_upload(
        db,
        file.filename or "upload",
        file.content_type or "application/octet-stream",
        data,
        t.subject_id,
        t.topic_id,
    )
    nf.owner_id = uid
    nf.task_id = task_id
    db.commit()
    return RedirectResponse(request.headers.get("referer") or "/tasks", status_code=303)


@app.post("/tasks")
def create_task(
    request: Request,
    title: str = Form(...),
    subject_id: str = Form(""),
    topic_id: str = Form(""),
    scheduled_date: str = Form(...),
    scheduled_time: str = Form(...),
    est_minutes: int = Form(30),
    recurrence_kind: str = Form("none"),  # "none" | "daily" | "weekly"
    recurrence_until: str = Form(""),
    db: Session = Depends(get_db),
    weekday_0: str = Form(""),
    weekday_1: str = Form(""),
    weekday_2: str = Form(""),
    weekday_3: str = Form(""),
    weekday_4: str = Form(""),
    weekday_5: str = Form(""),
    weekday_6: str = Form(""),
):
    uid = _uid(request)
    sid = int(subject_id) if subject_id else None
    tid: int | None = None
    if topic_id:
        try:
            tid_int = int(topic_id)
            t = db.get(Topic, tid_int)
            if t and t.owner_id == uid and (sid is None or t.subject_id == sid):
                tid = t.id
                if sid is None:
                    sid = t.subject_id
        except ValueError:
            tid = None

    try:
        sd = date.fromisoformat(scheduled_date)
        sh, sm = [int(x) for x in scheduled_time.split(":")[:2]]
        scheduled_dt = datetime.combine(sd, time(sh, sm))
    except (ValueError, IndexError):
        return RedirectResponse(
            "/plan?error=Invalid+date+or+time", status_code=303
        )

    # Must fall inside an availability slot AND fit before slot ends.
    slots = planner.slots_for_date(db, sd, user_id=uid)
    fits = any(
        slot.start <= scheduled_dt
        and scheduled_dt + timedelta(minutes=int(est_minutes)) <= slot.end
        for slot in slots
    )
    if not fits:
        return RedirectResponse(
            "/plan?error=Chosen+time+is+outside+your+availability+slots+for+that+date"
            f"&on={scheduled_date}",
            status_code=303,
        )

    rule = ""
    if recurrence_kind == "daily":
        rule = "DAILY"
    elif recurrence_kind == "weekly":
        wds = []
        for i, val in enumerate([weekday_0, weekday_1, weekday_2, weekday_3, weekday_4, weekday_5, weekday_6]):
            if val:
                wds.append(str(i))
        if wds:
            rule = "WEEKLY:" + ",".join(wds)
    until = None
    if rule and recurrence_until:
        try:
            until = date.fromisoformat(recurrence_until)
        except ValueError:
            until = None

    db.add(
        Task(
            owner_id=uid,
            title=title,
            subject_id=sid,
            topic_id=tid,
            due_date=sd,  # used by deadline-style filters / urgency
            scheduled_for=scheduled_dt,
            est_minutes=est_minutes,
            recurrence_rule=rule,
            recurrence_until=until,
        )
    )
    db.commit()
    return RedirectResponse(
        request.headers.get("referer") or f"/plan?on={scheduled_date}", status_code=303
    )


@app.post("/tasks/{task_id}/done")
def task_done(
    task_id: int,
    request: Request,
    celebrate: str = "",
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    t = db.get(Task, task_id)
    if t and t.owner_id == uid:
        if t.recurrence_rule:
            db.add(
                StudySession(
                    owner_id=uid,
                    started_at=datetime.utcnow(),
                    minutes=t.est_minutes or 30,
                    rating="good",
                )
            )
            t.progress_pct = 0
        else:
            t.status = "done"
            t.progress_pct = 100
        db.commit()
    referer = request.headers.get("referer") or "/"
    if celebrate:
        sep = "&" if "?" in referer else "?"
        referer = f"{referer}{sep}celebrated=1"
    return RedirectResponse(referer, status_code=303)


@app.post("/tasks/{task_id}/reschedule")
def task_reschedule(
    task_id: int,
    request: Request,
    scheduled_date: str = Form(""),
    scheduled_time: str = Form(""),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    t = db.get(Task, task_id)
    if not t or t.owner_id != uid:
        raise HTTPException(404)
    if not scheduled_date or not scheduled_time:
        # Clear schedule
        t.scheduled_for = None
        db.commit()
        return RedirectResponse(request.headers.get("referer") or "/settings", status_code=303)
    try:
        sd = date.fromisoformat(scheduled_date)
        sh, sm = [int(x) for x in scheduled_time.split(":")[:2]]
        candidate = datetime.combine(sd, time(sh, sm))
    except (ValueError, IndexError):
        return RedirectResponse(
            (request.headers.get("referer") or "/settings") + "?error=Invalid+date+or+time",
            status_code=303,
        )
    slots = planner.slots_for_date(db, sd, user_id=uid)
    end_dt = candidate + timedelta(minutes=t.est_minutes or 30)
    fits = any(s.start <= candidate and end_dt <= s.end for s in slots)
    if not fits:
        return RedirectResponse(
            (request.headers.get("referer") or "/settings") + "?error=New+time+is+outside+availability+slots",
            status_code=303,
        )
    t.scheduled_for = candidate
    t.due_date = sd
    db.commit()
    return RedirectResponse(request.headers.get("referer") or "/settings", status_code=303)


@app.post("/tasks/{task_id}/progress")
def task_progress(
    task_id: int,
    request: Request,
    progress_pct: int = Form(...),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    t = db.get(Task, task_id)
    if not t or t.owner_id != uid:
        raise HTTPException(404)
    pct = max(0, min(100, int(progress_pct)))
    t.progress_pct = pct
    if pct >= 100:
        t.status = "done"
    elif t.status == "done" and pct < 100:
        t.status = "open"
    db.commit()
    return RedirectResponse(request.headers.get("referer") or "/", status_code=303)


@app.post("/topics/{topic_id}/reset")
def reset_topic(topic_id: int, request: Request, db: Session = Depends(get_db)):
    """Take a topic out of spaced revision and clear its FSRS state."""
    uid = _uid(request)
    t = db.get(Topic, topic_id)
    if not t or t.owner_id != uid:
        raise HTTPException(404)
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
    db.commit()
    return RedirectResponse(
        request.headers.get("referer") or f"/subjects/{t.subject_id}#topic-{t.id}",
        status_code=303,
    )


@app.post("/topics/{topic_id}/delete")
def delete_topic(topic_id: int, request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    t = db.get(Topic, topic_id)
    if not t or t.owner_id != uid:
        raise HTTPException(404)
    subject_id = t.subject_id
    db.delete(t)
    db.commit()
    return RedirectResponse(request.headers.get("referer") or f"/subjects/{subject_id}", status_code=303)


@app.post("/deadlines")
def create_deadline(
    request: Request,
    kind: str = Form(...),
    title: str = Form(...),
    subject_id: str = Form(""),
    topic_id: str = Form(""),
    due_date: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    sid = int(subject_id) if subject_id else None
    tid: int | None = None
    if topic_id:
        try:
            tid_int = int(topic_id)
            t = db.get(Topic, tid_int)
            if t and t.owner_id == uid and (sid is None or t.subject_id == sid):
                tid = t.id
                if sid is None:
                    sid = t.subject_id
        except ValueError:
            pass
    db.add(
        Deadline(
            owner_id=uid,
            kind=kind,
            title=title,
            subject_id=sid,
            topic_id=tid,
            due_date=date.fromisoformat(due_date),
        )
    )
    db.commit()
    return RedirectResponse(request.headers.get("referer") or "/plan", status_code=303)


# ---------- notes ----------

@app.get("/notes", response_class=HTMLResponse)
def notes_view(request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    files = db.scalars(
        select(NoteFile).where(NoteFile.owner_id == uid).order_by(NoteFile.created_at.desc())
    ).all()
    ctx = _common_ctx(request, db)
    ctx["files"] = files
    return templates.TemplateResponse("notes.html", ctx)


@app.post("/notes/upload")
async def notes_upload(
    request: Request,
    file: UploadFile = File(...),
    subject_id: str = Form(""),
    topic_id: str = Form(""),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    data = await file.read()
    sid = int(subject_id) if subject_id else None
    tid: int | None = None
    if topic_id:
        try:
            t_obj = db.get(Topic, int(topic_id))
            if t_obj and t_obj.owner_id == uid:
                tid = t_obj.id
        except ValueError:
            tid = None
    nf = notes.save_upload(
        db, file.filename or "upload",
        file.content_type or "application/octet-stream",
        data, sid, tid,
    )
    nf.owner_id = uid
    db.commit()
    return RedirectResponse("/notes", status_code=303)


# ---------- settings / availability ----------

@app.get("/settings", response_class=HTMLResponse)
def settings_view(request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    rules = db.scalars(
        select(AvailabilityRule)
        .where(AvailabilityRule.owner_id == uid)
        .order_by(AvailabilityRule.weekday, AvailabilityRule.start_time)
    ).all()
    by_day: dict[int, list[AvailabilityRule]] = {i: [] for i in range(7)}
    for r in rules:
        by_day[r.weekday].append(r)

    today = date.today()
    exceptions = list(
        db.scalars(
            select(AvailabilityException)
            .where(AvailabilityException.owner_id == uid)
            .where(AvailabilityException.on_date >= today)
            .order_by(AvailabilityException.on_date, AvailabilityException.start_time)
        )
    )
    # Group by date so the UI shows one row per date with all overrides on it.
    exceptions_grouped: list[dict] = []
    by_d: dict[date, list[AvailabilityException]] = {}
    for ex in exceptions:
        by_d.setdefault(ex.on_date, []).append(ex)
    for d, items in sorted(by_d.items()):
        exceptions_grouped.append({"date": d, "overrides": items})

    # Conflict scan: for every future scheduled task, check whether the slot
    # it was placed into still exists given current rules + exceptions.
    conflicts: list[dict] = []
    upcoming_tasks = list(
        db.scalars(
            select(Task)
            .where(Task.owner_id == uid)
            .where(Task.status == "open", Task.scheduled_for.is_not(None))
            .where(Task.scheduled_for >= datetime.combine(today, time.min))
        )
    )
    for tk in upcoming_tasks:
        sd = tk.scheduled_for.date()
        slots = planner.slots_for_date(db, sd, user_id=uid)
        end_dt = tk.scheduled_for + timedelta(minutes=tk.est_minutes or 30)
        fits = any(s.start <= tk.scheduled_for and end_dt <= s.end for s in slots)
        if not fits:
            conflicts.append(
                {
                    "task": tk,
                    "scheduled_for": tk.scheduled_for,
                    "minutes": tk.est_minutes or 30,
                }
            )

    ctx = _common_ctx(request, db)
    ctx["by_day"] = by_day
    ctx["exceptions"] = exceptions
    ctx["exceptions_grouped"] = exceptions_grouped
    ctx["conflicts"] = conflicts
    user = db.get(User, uid)
    token = _ensure_calendar_token(db, user)
    ctx["calendar_ics_path"] = f"/study-planner/calendar/{uid}.ics?token={token}"
    return templates.TemplateResponse("settings.html", ctx)


@app.post("/availability/add")
def availability_add(
    request: Request,
    weekday: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    sh, sm = [int(x) for x in start_time.split(":")]
    eh, em = [int(x) for x in end_time.split(":")]
    db.add(AvailabilityRule(
        owner_id=uid, weekday=weekday,
        start_time=time(sh, sm), end_time=time(eh, em),
    ))
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.post("/availability/{rule_id}/delete")
def availability_delete(rule_id: int, request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    r = db.get(AvailabilityRule, rule_id)
    if r and r.owner_id == uid:
        db.delete(r)
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.post("/availability/exception")
def availability_exception_add(
    request: Request,
    on_date: str = Form(...),
    mode: str = Form(...),  # "block_all" | "block_range" | "extra"
    start_time: str = Form(""),
    end_time: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    try:
        d = date.fromisoformat(on_date)
    except ValueError:
        return RedirectResponse("/settings?error=Invalid+date", status_code=303)

    st: time | None = None
    et: time | None = None
    if start_time and end_time:
        try:
            sh, sm = [int(x) for x in start_time.split(":")[:2]]
            eh, em = [int(x) for x in end_time.split(":")[:2]]
            st = time(sh, sm)
            et = time(eh, em)
        except ValueError:
            return RedirectResponse("/settings?error=Invalid+time", status_code=303)

    if mode == "block_all":
        ex = AvailabilityException(owner_id=uid, on_date=d, is_blocked=True, note=note)
    elif mode == "block_range":
        if not st or not et:
            return RedirectResponse("/settings?error=Provide+a+time+range+to+block", status_code=303)
        ex = AvailabilityException(
            owner_id=uid, on_date=d, start_time=st, end_time=et, is_blocked=True, note=note
        )
    elif mode == "extra":
        if not st or not et:
            return RedirectResponse("/settings?error=Provide+start+and+end+for+extra+slot", status_code=303)
        ex = AvailabilityException(
            owner_id=uid, on_date=d, start_time=st, end_time=et, is_blocked=False, note=note
        )
    else:
        return RedirectResponse("/settings?error=Unknown+mode", status_code=303)

    db.add(ex)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.post("/availability/exception/{ex_id}/delete")
def availability_exception_delete(ex_id: int, request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    ex = db.get(AvailabilityException, ex_id)
    if ex and ex.owner_id == uid:
        db.delete(ex)
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.post("/subjects/{subject_id}/appearance")
def subject_appearance(
    subject_id: int,
    icon: str = Form(""),
    color: str = Form(""),
    db: Session = Depends(get_db),
):
    s = db.get(Subject, subject_id)
    if not s:
        raise HTTPException(404)
    icon_v = (icon or "").strip()
    if icon_v:
        s.icon = icon_v[:40]
    color_v = (color or "").strip()
    if color_v:
        s.color = color_v[:20]
    db.commit()
    return RedirectResponse("/settings", status_code=303)


# ---------- chat ----------

def _next_chat_name(db: Session, user_id: int) -> str:
    count = db.scalar(select(func.count()).select_from(ChatSession).where(ChatSession.owner_id == user_id)) or 0
    return f"Chat {count + 1}"


def _get_active_chat_session(db: Session, user, session_id: int | None):
    if session_id is not None:
        session = db.get(ChatSession, session_id)
        if session and session.owner_id == user.id:
            return session
    session = db.scalars(
        select(ChatSession)
        .where(ChatSession.owner_id == user.id)
        .order_by(ChatSession.last_active_at.desc(), ChatSession.created_at.desc())
        .limit(1)
    ).first()
    if session:
        return session

    legacy_count = db.scalar(
        select(func.count()).select_from(ChatMessage)
        .where(ChatMessage.owner_id == user.id, ChatMessage.session_id.is_(None))
    )
    if legacy_count:
        session = ChatSession(owner_id=user.id, name="Legacy chat")
        db.add(session)
        db.commit()
        db.refresh(session)
        db.execute(
            update(ChatMessage)
            .where(ChatMessage.owner_id == user.id, ChatMessage.session_id.is_(None))
            .values(session_id=session.id)
        )
        db.commit()
        return session

    session = ChatSession(owner_id=user.id, name=_next_chat_name(db, user.id))
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@app.get("/chat", response_class=HTMLResponse)
def chat_view(request: Request, session_id: int | None = None, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    active_session = _get_active_chat_session(db, user, session_id)
    msgs = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == active_session.id)
        .order_by(ChatMessage.id.desc()).limit(40)
    ).all()[::-1]
    sessions = db.scalars(
        select(ChatSession)
        .where(ChatSession.owner_id == user.id)
        .order_by(ChatSession.last_active_at.desc(), ChatSession.created_at.desc())
    ).all()
    ctx = _common_ctx(request, db)
    ctx["messages"] = msgs
    ctx["sessions"] = sessions
    ctx["current_session"] = active_session
    ctx["has_api_key"] = bool((user.anthropic_api_key or "").strip())
    return templates.TemplateResponse("chat.html", ctx)


@app.post("/chat")
def chat_post(
    request: Request,
    message: str = Form(...),
    session_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    active_session = _get_active_chat_session(db, user, session_id)
    db.execute(
        update(ChatSession)
        .where(ChatSession.id == active_session.id)
        .values(last_active_at=datetime.utcnow())
    )
    db.commit()
    ai.chat(
        db,
        message,
        api_key=user.anthropic_api_key or None,
        user_id=user.id,
        session_id=active_session.id,
    )
    return RedirectResponse(f"/chat?session_id={active_session.id}", status_code=303)


@app.post("/chat/new")
def chat_new(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    session = ChatSession(owner_id=user.id, name=_next_chat_name(db, user.id))
    db.add(session)
    db.commit()
    db.refresh(session)
    return RedirectResponse(f"/chat?session_id={session.id}", status_code=303)


@app.post("/chat/sessions/{session_id}/delete")
def chat_delete_session(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    session = db.get(ChatSession, session_id)
    if not session or session.owner_id != user.id:
        raise HTTPException(404)
    db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete()
    db.delete(session)
    db.commit()
    return RedirectResponse("/chat", status_code=303)


# ---------- history ----------

@app.get("/history", response_class=HTMLResponse)
def history_view(
    request: Request,
    view: str = "week",
    on: str = "",
    db: Session = Depends(get_db),
):
    """Show study sessions either day-by-day or for a Mon–Sun week.

    `view` = "day" | "week" (default "week").
    `on`   = ISO date inside the day/week to show (default today).
    """
    today = date.today()
    on_date = date.fromisoformat(on) if on else today
    view = "day" if view == "day" else "week"

    if view == "day":
        start_d = on_date
        end_d = on_date
        prev_d = on_date - timedelta(days=1)
        next_d = on_date + timedelta(days=1)
        label = on_date.strftime("%A, %d %b %Y")
    else:
        # Monday of that week
        start_d = on_date - timedelta(days=on_date.weekday())
        end_d = start_d + timedelta(days=6)
        prev_d = start_d - timedelta(days=7)
        next_d = start_d + timedelta(days=7)
        label = f"Week of {start_d.strftime('%d %b')} – {end_d.strftime('%d %b %Y')}"

    range_start = datetime.combine(start_d, time.min)
    range_end = datetime.combine(end_d, time.max)

    uid = _uid(request)
    sessions = list(
        db.scalars(
            select(StudySession)
            .where(StudySession.owner_id == uid)
            .where(StudySession.started_at >= range_start)
            .where(StudySession.started_at <= range_end)
            .order_by(StudySession.started_at.desc())
        )
    )

    # Group sessions by day for the table
    by_day: dict[date, list[StudySession]] = {}
    cur = start_d
    while cur <= end_d:
        by_day[cur] = []
        cur += timedelta(days=1)
    for s in sessions:
        d = s.started_at.date()
        if d in by_day:
            by_day[d].append(s)

    # Daily totals (minutes) and rating breakdown
    day_stats = []
    for d in sorted(by_day.keys()):
        items = by_day[d]
        minutes = sum(s.minutes or 0 for s in items)
        rating_counts = {"again": 0, "hard": 0, "good": 0, "easy": 0}
        for s in items:
            if s.rating in rating_counts:
                rating_counts[s.rating] += 1
        day_stats.append(
            {
                "date": d,
                "weekday": WEEKDAYS[d.weekday()],
                "minutes": minutes,
                "count": len(items),
                "ratings": rating_counts,
                "sessions": items,
            }
        )

    total_minutes = sum(s["minutes"] for s in day_stats)
    total_count = sum(s["count"] for s in day_stats)

    ctx = _common_ctx(request, db)
    ctx.update(
        {
            "view": view,
            "label": label,
            "on_date": on_date,
            "start_d": start_d,
            "end_d": end_d,
            "prev_d": prev_d,
            "next_d": next_d,
            "day_stats": day_stats,
            "total_minutes": total_minutes,
            "total_count": total_count,
        }
    )
    return templates.TemplateResponse("history.html", ctx)


# ---------- plan ----------

@app.get("/plan", response_class=HTMLResponse)
def plan_view(request: Request, on: str = "", db: Session = Depends(get_db)):
    uid = _uid(request)
    on_date = date.fromisoformat(on) if on else date.today()
    plan = planner.build_plan(db, on_date, user_id=uid)

    # Group items by subject for the bottom card grid. Subjects with no items
    # for the day still show a card so the layout is stable.
    all_subjects = ctx_subjects = list(
        db.scalars(select(Subject).order_by(Subject.sort_order, Subject.name)).all()
    )
    items_by_subject: dict[str, list] = {s.name: [] for s in all_subjects}
    items_by_subject["(no subject)"] = []
    for item in plan.items:
        key = item.subject_name or "(no subject)"
        items_by_subject.setdefault(key, []).append(item)

    # Weekly availability grouped by weekday — used by the task scheduling form
    # so the user picks slot start times that match their configured availability.
    weekly_rules = list(
        db.scalars(
            select(AvailabilityRule)
            .where(AvailabilityRule.owner_id == uid)
            .order_by(AvailabilityRule.weekday, AvailabilityRule.start_time)
        )
    )
    rules_by_weekday: dict[int, list[dict]] = {i: [] for i in range(7)}
    for r in weekly_rules:
        rules_by_weekday[r.weekday].append(
            {
                "start": r.start_time.strftime("%H:%M"),
                "end": r.end_time.strftime("%H:%M"),
            }
        )

    # Per-date overrides for the next ~6 months — sent to the form so it can
    # honour blocks/extras when computing valid slot start times.
    horizon = on_date + timedelta(days=180)
    exceptions = db.scalars(
        select(AvailabilityException)
        .where(AvailabilityException.owner_id == uid)
        .where(AvailabilityException.on_date >= on_date - timedelta(days=1))
        .where(AvailabilityException.on_date <= horizon)
    ).all()
    exceptions_by_date: dict[str, list[dict]] = {}
    for ex in exceptions:
        exceptions_by_date.setdefault(ex.on_date.isoformat(), []).append(
            {
                "is_blocked": bool(ex.is_blocked),
                "start": ex.start_time.strftime("%H:%M") if ex.start_time else None,
                "end": ex.end_time.strftime("%H:%M") if ex.end_time else None,
            }
        )

    topics_by_subject = _build_topics_by_subject(db, uid)

    ctx = _common_ctx(request, db)
    ctx.update(
        {
            "plan": plan,
            "prev_date": on_date - timedelta(days=1),
            "next_date": on_date + timedelta(days=1),
            "items_by_subject": items_by_subject,
            "rules_by_weekday": rules_by_weekday,
            "exceptions_by_date": exceptions_by_date,
            "topics_by_subject": topics_by_subject,
        }
    )
    return templates.TemplateResponse("plan.html", ctx)


def _serialize_planner_subject(s: Subject) -> dict:
    return {"id": s.id, "name": s.name, "icon": s.icon, "color": s.color}


def _serialize_planner_block(
    b: StudyPlannerBlock,
    db: Optional[Session] = None,
    blocks_by_id: Optional[dict[int, StudyPlannerBlock]] = None,
) -> dict:
    carried_from_date = (
        study_planner.resolve_carry_over_origin_date(db, b, blocks_by_id) if db and b.carried_from_id else None
    )
    return {
        "id": b.id,
        "on_date": b.on_date.isoformat(),
        "slot_index": b.slot_index,
        "block_kind": b.block_kind,
        "subject_id": b.subject_id,
        "task_name": b.task_name,
        "duration_minutes": b.duration_minutes,
        "start_time": b.start_time or "",
        "end_time": b.end_time or "",
        "is_fixed": b.is_fixed,
        "is_optional": b.is_optional,
        "completed": b.completed,
        "carried_forward": b.carried_forward,
        "carried_from_id": b.carried_from_id,
        "carried_from_date": carried_from_date.isoformat() if carried_from_date else None,
        "carry_over_percent": b.carry_over_percent,
        "source_rule_id": b.source_rule_id,
        "revision_links": [
            {
                "revision_chapter_name": link.revision_chapter_name,
                "due_date": link.due_date,
            }
            for link in b.revision_links
        ],
    }


def _serialize_fixed_rule(r: PlannerFixedRule) -> dict:
    return {
        "id": r.id,
        "weekday": r.weekday,
        "subject_id": r.subject_id,
        "task_name": r.task_name,
        "start_time": r.start_time or "",
        "duration_minutes": r.duration_minutes,
        "is_optional": r.is_optional,
    }


def _planner_time_minutes(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        hh, mm = str(value).split(":")
        return int(hh) * 60 + int(mm)
    except (TypeError, ValueError):
        return None


def _planner_block_sort_key(start_time: Optional[str], slot_index: int, block_id: int) -> tuple:
    """Blocks with an explicit start time (fixed or not) sort chronologically by
    that time first, so setting e.g. 05:00/06:00 rearranges the whole day -- blocks
    without a time keep their manually-arranged slot order, placed after timed ones."""
    minutes = _planner_time_minutes(start_time)
    if minutes is not None:
        return (0, minutes, slot_index, block_id)
    return (1, 0, slot_index, block_id)


def _planner_day_payload(db: Session, uid: Optional[int], on_date: date) -> dict:
    week_start = study_planner.week_start_monday(on_date)
    study_planner.ensure_week_blocks_safe(db, uid, on_date)
    db.commit()
    week_blocks = study_planner.get_week_blocks(db, uid, week_start)
    return _build_planner_day_payload(db, uid, on_date, week_start, week_blocks)


def _build_planner_day_payload(
    db: Session,
    uid: Optional[int],
    on_date: date,
    week_start: date,
    week_blocks: list["StudyPlannerBlock"],
) -> dict:
    day_blocks = sorted(
        (b for b in week_blocks if b.on_date == on_date and b.block_kind != "placeholder"),
        key=lambda b: _planner_block_sort_key(b.start_time, b.slot_index, b.id),
    )
    week_blocks_by_id = {b.id: b for b in week_blocks}

    subjects = list(db.scalars(select(Subject).order_by(Subject.sort_order, Subject.name)).all())

    revision_state = study_planner.load_revision_desk_state(db, uid)
    due_cards = study_planner.get_due_cards_for_day(revision_state, on_date)

    due_cards_mapped: list[dict] = []
    for c in due_cards:
        sid = study_planner.map_due_card_subject_to_id(c, subjects)
        due_cards_mapped.append(
            {
                "subject_id": sid,
                "revision_subject_id": c.subject_id,
                "revision_chapter_id": c.chapter_id,
                "subject_name": c.subject_name,
                "chapter_name": c.chapter_name,
                "due_date": c.due_date,
            }
        )

    linked_keys = [
        f"{link.revision_subject_id}::{link.revision_chapter_id}"
        for b in day_blocks
        for link in b.revision_links
    ]

    day_required = [b for b in day_blocks if not b.is_optional]
    day_completed = bool(day_required) and all(b.completed for b in day_required)
    streak_days = study_planner.planner_streak_days(db, uid, date.today())
    fixed_rules = study_planner.get_fixed_rules_for_user(db, uid)

    return {
        "on": on_date.isoformat(),
        "prev": (on_date - timedelta(days=1)).isoformat(),
        "next": (on_date + timedelta(days=1)).isoformat(),
        "week_start": week_start.isoformat(),
        "week_dates": [(week_start + timedelta(days=i)).isoformat() for i in range(7)],
        "day_blocks": [_serialize_planner_block(b, db, week_blocks_by_id) for b in day_blocks],
        "subjects": [_serialize_planner_subject(s) for s in subjects],
        "due_cards": due_cards_mapped,
        "linked_keys": linked_keys,
        "streak_days": streak_days,
        "day_completed": day_completed,
        "fixed_rules": [_serialize_fixed_rule(r) for r in fixed_rules],
    }


def _planner_week_payload(db: Session, uid: Optional[int], on_date: date) -> dict:
    week_start = study_planner.week_start_monday(on_date)
    study_planner.ensure_week_blocks_safe(db, uid, on_date)
    db.commit()
    week_blocks = study_planner.get_week_blocks(db, uid, week_start)
    return _build_planner_week_payload(db, uid, week_start, week_blocks)


def _build_planner_week_payload(
    db: Session,
    uid: Optional[int],
    week_start: date,
    week_blocks: list["StudyPlannerBlock"],
) -> dict:
    week_dates = [week_start + timedelta(days=i) for i in range(7)]
    blocks_by_day: dict[str, list[dict]] = {d.isoformat(): [] for d in week_dates}
    week_blocks_by_id = {b.id: b for b in week_blocks}
    for b in week_blocks:
        if b.block_kind == "placeholder":
            continue
        blocks_by_day.setdefault(b.on_date.isoformat(), []).append(_serialize_planner_block(b, db, week_blocks_by_id))
    for day_iso in blocks_by_day:
        blocks_by_day[day_iso].sort(key=lambda b: _planner_block_sort_key(b["start_time"], b["slot_index"], b["id"]))

    subjects = list(db.scalars(select(Subject).order_by(Subject.sort_order, Subject.name)).all())
    weekly_totals = study_planner.weekly_subject_minutes(week_blocks)

    day_completed_map: dict[str, bool] = {}
    for day_iso, blocks in blocks_by_day.items():
        required = [b for b in blocks if not b["is_optional"]]
        day_completed_map[day_iso] = bool(required) and all(b["completed"] for b in required)

    return {
        "week_start": week_start.isoformat(),
        "week_dates": [d.isoformat() for d in week_dates],
        "blocks_by_day": blocks_by_day,
        "weekly_totals": {str(k): v for k, v in weekly_totals.items()},
        "subjects": [_serialize_planner_subject(s) for s in subjects],
        "day_completed_map": day_completed_map,
    }


def _planner_day_payload_light(db: Session, uid: Optional[int], on_date: date) -> dict:
    """Same result as _planner_day_payload() but skips ensure_week_blocks_safe() --
    for use right after a block mutation (toggle/edit/delete/carry-over/move/reorder),
    where the week is already known to exist because we just read/wrote a block in it.
    Re-running the full week generation-check (a week-wide query + subjects + revision-desk
    state load + fixed-rules query + a SAVEPOINT + commit) on every single checkbox click
    was pure redundant latency, especially over the network to prod's Postgres."""
    week_start = study_planner.week_start_monday(on_date)
    week_blocks = study_planner.get_week_blocks(db, uid, week_start)
    return _build_planner_day_payload(db, uid, on_date, week_start, week_blocks)


def _planner_combined_payload(db: Session, uid: Optional[int], on_date: date) -> dict:
    """day + week payloads from a single ensure_week_blocks_safe() + get_week_blocks() call --
    the frontend used to fetch these separately (2 round trips, 2 concurrent generation
    attempts for the same week -- the root cause of the duplicate-block race)."""
    week_start = study_planner.week_start_monday(on_date)
    study_planner.ensure_week_blocks_safe(db, uid, on_date)
    db.commit()
    week_blocks = study_planner.get_week_blocks(db, uid, week_start)
    return {
        "day": _build_planner_day_payload(db, uid, on_date, week_start, week_blocks),
        "week": _build_planner_week_payload(db, uid, week_start, week_blocks),
    }


def _parse_planner_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return date.today()


def _normalize_planner_time(value) -> Optional[str]:
    """Validate a "HH:MM" 24h time string; returns None if blank/invalid."""
    if not value:
        return None
    value = str(value).strip()
    try:
        time.fromisoformat(value)
    except ValueError:
        return None
    return value[:5]


@app.get("/study-planner/api/day")
def study_planner_api_day(request: Request, on: str = "", db: Session = Depends(get_db)):
    uid = _uid(request)
    on_date = _parse_planner_date(on) if on else date.today()
    return _planner_day_payload(db, uid, on_date)


@app.get("/study-planner/api/week")
def study_planner_api_week(request: Request, on: str = "", db: Session = Depends(get_db)):
    uid = _uid(request)
    on_date = _parse_planner_date(on) if on else date.today()
    return _planner_week_payload(db, uid, on_date)


@app.get("/study-planner/api/plan")
def study_planner_api_plan(request: Request, on: str = "", db: Session = Depends(get_db)):
    """Combined day+week payload in one request -- the frontend used to fire /api/day
    and /api/week concurrently for the same week, doubling round trips."""
    uid = _uid(request)
    on_date = _parse_planner_date(on) if on else date.today()
    return _planner_combined_payload(db, uid, on_date)


@app.post("/study-planner/api/blocks/{block_id}/toggle")
async def study_planner_api_block_toggle(block_id: int, request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    block = db.get(StudyPlannerBlock, block_id)
    if not block or block.owner_id != uid:
        raise HTTPException(404)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    now_completed = bool(payload.get("completed"))
    was_completed = bool(block.completed)
    block.completed = now_completed
    block.completed_at = datetime.utcnow() if now_completed else None

    if now_completed and not was_completed and block.revision_pushed_at is None:
        pushed = study_planner.push_block_links_to_revision_state(db, uid, block)
        if pushed > 0:
            block.revision_pushed_at = datetime.utcnow()

    db.commit()
    return _planner_day_payload_light(db, uid, block.on_date)


@app.post("/study-planner/api/blocks/{block_id}/update")
async def study_planner_api_block_update(block_id: int, request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    block = db.get(StudyPlannerBlock, block_id)
    if not block or block.owner_id != uid:
        raise HTTPException(404)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    block.task_name = str(payload.get("task_name") or "").strip()
    try:
        block.duration_minutes = max(10, min(180, int(payload.get("duration_minutes") or 50)))
    except (TypeError, ValueError):
        block.duration_minutes = 50
    block.start_time = _normalize_planner_time(payload.get("start_time"))
    block.end_time = _normalize_planner_time(payload.get("end_time"))

    if "is_fixed" in payload:
        block.is_fixed = bool(payload.get("is_fixed"))

    subject_id = payload.get("subject_id")
    block.subject_id = int(subject_id) if subject_id else None

    db.commit()
    return _planner_day_payload_light(db, uid, block.on_date)


@app.post("/study-planner/api/blocks/{block_id}/delete")
async def study_planner_api_block_delete(block_id: int, request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    block = db.get(StudyPlannerBlock, block_id)
    if not block or block.owner_id != uid:
        raise HTTPException(404)

    on_date = block.on_date
    db.delete(block)
    db.flush()

    remaining = db.scalar(
        select(func.count())
        .select_from(StudyPlannerBlock)
        .where(StudyPlannerBlock.owner_id == uid)
        .where(StudyPlannerBlock.on_date == on_date)
    ) or 0
    if remaining == 0:
        # keep a hidden placeholder so ensure_week_blocks() won't regenerate the default
        # schedule for a day the student intentionally emptied out
        db.add(
            StudyPlannerBlock(
                owner_id=uid,
                on_date=on_date,
                slot_index=0,
                block_kind="placeholder",
                task_name="",
                duration_minutes=0,
                is_fixed=False,
                is_optional=True,
            )
        )

    db.commit()
    return _planner_day_payload_light(db, uid, on_date)


@app.post("/study-planner/api/blocks/add")
async def study_planner_api_block_add(request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    on_date = _parse_planner_date(payload.get("on") or "")
    study_planner.ensure_week_blocks_safe(db, uid, on_date)
    db.flush()

    # a manually-added block means this day is no longer "empty"
    db.execute(
        delete(StudyPlannerBlock)
        .where(StudyPlannerBlock.owner_id == uid)
        .where(StudyPlannerBlock.on_date == on_date)
        .where(StudyPlannerBlock.block_kind == "placeholder")
    )

    day_blocks = list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == uid)
            .where(StudyPlannerBlock.on_date == on_date)
        )
    )
    max_slot = max((b.slot_index for b in day_blocks), default=-1)

    try:
        duration_minutes = max(10, min(180, int(payload.get("duration_minutes") or 50)))
    except (TypeError, ValueError):
        duration_minutes = 50
    subject_id = payload.get("subject_id")

    block = StudyPlannerBlock(
        owner_id=uid,
        on_date=on_date,
        slot_index=max_slot + 1,
        block_kind="custom",
        subject_id=int(subject_id) if subject_id else None,
        task_name=str(payload.get("task_name") or "").strip() or "Study block",
        duration_minutes=duration_minutes,
        start_time=_normalize_planner_time(payload.get("start_time")),
        end_time=_normalize_planner_time(payload.get("end_time")),
        is_fixed=bool(payload.get("is_fixed")),
        is_optional=bool(payload.get("is_optional")),
    )
    db.add(block)
    db.commit()
    return _planner_day_payload_light(db, uid, on_date)


@app.post("/study-planner/api/fixed-rules/add")
async def study_planner_api_fixed_rule_add(request: Request, db: Session = Depends(get_db)):
    """Create a recurring fixed commitment (e.g. "every Tuesday") and materialize
    it into the currently-viewed week right away."""
    uid = _uid(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    weekday_raw = payload.get("weekday")
    weekday: Optional[int] = None
    if weekday_raw not in (None, "", "all"):
        try:
            weekday = int(weekday_raw)
        except (TypeError, ValueError):
            weekday = None
        if weekday is not None and not (0 <= weekday <= 6):
            weekday = None

    try:
        duration_minutes = max(10, min(180, int(payload.get("duration_minutes") or 50)))
    except (TypeError, ValueError):
        duration_minutes = 50
    subject_id = payload.get("subject_id")

    rule = PlannerFixedRule(
        owner_id=uid,
        weekday=weekday,
        subject_id=int(subject_id) if subject_id else None,
        task_name=str(payload.get("task_name") or "").strip() or "Study block",
        start_time=_normalize_planner_time(payload.get("start_time")),
        duration_minutes=duration_minutes,
        is_optional=bool(payload.get("is_optional")),
    )
    db.add(rule)
    db.commit()

    on_date = _parse_planner_date(payload.get("on") or "") if payload.get("on") else date.today()
    study_planner.ensure_week_blocks_safe(db, uid, on_date)
    db.commit()
    return _planner_day_payload_light(db, uid, on_date)


@app.post("/study-planner/api/fixed-rules/{rule_id}/delete")
async def study_planner_api_fixed_rule_delete(rule_id: int, request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    rule = db.get(PlannerFixedRule, rule_id)
    if not rule or rule.owner_id != uid:
        raise HTTPException(404)

    db.delete(rule)
    # drop any not-yet-happened generated instances so they stop showing on the plan
    db.execute(
        delete(StudyPlannerBlock)
        .where(StudyPlannerBlock.owner_id == uid)
        .where(StudyPlannerBlock.source_rule_id == rule_id)
        .where(StudyPlannerBlock.on_date >= date.today())
        .where(StudyPlannerBlock.completed.is_(False))
    )
    db.commit()

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    on_date = _parse_planner_date(payload.get("on") or "") if payload.get("on") else date.today()
    return _planner_day_payload(db, uid, on_date)


@app.post("/study-planner/api/blocks/{block_id}/carry-over")
async def study_planner_api_block_carry_over(block_id: int, request: Request, db: Session = Depends(get_db)):
    """Mark today's block as done (so the student's daily streak isn't broken) and
    push the unfinished remainder onto tomorrow's plan as a new linked block."""
    uid = _uid(request)
    block = db.get(StudyPlannerBlock, block_id)
    if not block or block.owner_id != uid:
        raise HTTPException(404)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    try:
        remaining_minutes = max(10, min(180, int(payload.get("remaining_minutes") or block.duration_minutes)))
    except (TypeError, ValueError):
        remaining_minutes = block.duration_minutes

    percent_finished = payload.get("percent_finished")
    if percent_finished not in (None, ""):
        try:
            block.carry_over_percent = max(0, min(100, int(percent_finished)))
        except (TypeError, ValueError):
            block.carry_over_percent = None

    block.completed = True
    block.completed_at = datetime.utcnow()
    block.carried_forward = True

    next_date = block.on_date + timedelta(days=1)
    study_planner.ensure_week_blocks_safe(db, uid, next_date)
    db.flush()

    # a carried-over task means tomorrow is no longer "empty"
    db.execute(
        delete(StudyPlannerBlock)
        .where(StudyPlannerBlock.owner_id == uid)
        .where(StudyPlannerBlock.on_date == next_date)
        .where(StudyPlannerBlock.block_kind == "placeholder")
    )

    next_day_blocks = list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == uid)
            .where(StudyPlannerBlock.on_date == next_date)
        )
    )
    max_slot = max((b.slot_index for b in next_day_blocks), default=-1)

    new_block = StudyPlannerBlock(
        owner_id=uid,
        on_date=next_date,
        slot_index=max_slot + 1,
        block_kind=block.block_kind,
        subject_id=block.subject_id,
        task_name=f"\u21bb {block.task_name}".strip() if block.task_name else "Continued study block",
        duration_minutes=remaining_minutes,
        is_fixed=False,
        is_optional=False,
        carried_from_id=block.id,
        # the % reflects overall task progress, not just today's share -- carry it
        # forward so tomorrow's block still shows how far along the task really is
        carry_over_percent=block.carry_over_percent,
    )
    db.add(new_block)
    db.flush()

    # move any linked due cards forward with the unfinished work rather than
    # marking them pushed against a block that wasn't actually finished
    for link in list(block.revision_links):
        link.block_id = new_block.id

    db.commit()
    return _planner_day_payload_light(db, uid, block.on_date)


@app.post("/study-planner/api/blocks/{block_id}/move")
async def study_planner_api_block_move(block_id: int, request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    block = db.get(StudyPlannerBlock, block_id)
    if not block or block.owner_id != uid:
        raise HTTPException(404)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    direction = payload.get("direction") or "up"

    # any block -- fixed included -- can be moved; blocks are otherwise sorted
    # chronologically by start_time, so this only affects untimed blocks' order
    day_blocks = list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == uid)
            .where(StudyPlannerBlock.on_date == block.on_date)
            .order_by(StudyPlannerBlock.slot_index, StudyPlannerBlock.id)
        )
    )
    try:
        idx = [b.id for b in day_blocks].index(block.id)
    except ValueError:
        idx = -1

    if idx >= 0:
        swap_idx = idx - 1 if direction == "up" else idx + 1
        if 0 <= swap_idx < len(day_blocks):
            other = day_blocks[swap_idx]
            a_slot, b_slot = block.slot_index, other.slot_index
            # two-phase update: the unique(owner_id, on_date, slot_index) constraint is
            # checked per-row, so swapping directly can transiently collide mid-flush
            block.slot_index, other.slot_index = -1, -2
            db.flush()
            block.slot_index, other.slot_index = b_slot, a_slot

    db.commit()
    return _planner_day_payload_light(db, uid, block.on_date)


@app.post("/study-planner/api/blocks/{block_id}/pull-subject-due")
async def study_planner_api_pull_subject_due(block_id: int, request: Request, db: Session = Depends(get_db)):
    """Pull any due revision cards for this block's subject onto the day's plan.
    Each due card becomes its own standalone due-review block (not merged into this
    or any other block) so Focused blocks stay reserved for studying new content."""
    uid = _uid(request)
    block = db.get(StudyPlannerBlock, block_id)
    if not block or block.owner_id != uid:
        raise HTTPException(404)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    on_date = _parse_planner_date(payload.get("on") or "") if payload.get("on") else block.on_date

    if block.subject_id:
        subjects = list(db.scalars(select(Subject).order_by(Subject.sort_order, Subject.name)).all())
        revision_state = study_planner.load_revision_desk_state(db, uid)
        due_cards = study_planner.get_due_cards_for_day(revision_state, on_date)
        matching = [c for c in due_cards if study_planner.map_due_card_subject_to_id(c, subjects) == block.subject_id]
        if matching:
            # fetch the day's blocks once and reuse across the loop instead of
            # re-querying per due card
            day_blocks = list(
                db.scalars(
                    select(StudyPlannerBlock)
                    .where(StudyPlannerBlock.owner_id == uid)
                    .where(StudyPlannerBlock.on_date == on_date)
                    .options(selectinload(StudyPlannerBlock.revision_links))
                )
            )
            for card in matching:
                _add_due_card_as_block(db, uid, on_date, block.subject_id, card, day_blocks)

    db.commit()
    return _planner_day_payload_light(db, uid, on_date)


def _add_due_card_as_block(
    db: Session,
    uid: int,
    on_date: date,
    subject_id: Optional[int],
    due_card: "study_planner.RevisionDueCard",
    day_blocks: Optional[list[StudyPlannerBlock]] = None,
) -> Optional[StudyPlannerBlock]:
    """Create a standalone due-review block for one due revision card, unless that
    exact card is already linked to a block on this day. Pass an already-fetched
    day_blocks list (with revision_links loaded) to avoid re-querying in a loop --
    it's extended in place so repeat calls stay consistent."""
    if day_blocks is None:
        day_blocks = list(
            db.scalars(
                select(StudyPlannerBlock)
                .where(StudyPlannerBlock.owner_id == uid)
                .where(StudyPlannerBlock.on_date == on_date)
                .options(selectinload(StudyPlannerBlock.revision_links))
            )
        )
    already_linked = any(
        link.revision_subject_id == due_card.subject_id and link.revision_chapter_id == due_card.chapter_id
        for b in day_blocks
        for link in b.revision_links
    )
    if already_linked:
        return None

    max_slot = max((b.slot_index for b in day_blocks), default=-1)
    subj = db.get(Subject, subject_id) if subject_id else None
    block = StudyPlannerBlock(
        owner_id=uid,
        on_date=on_date,
        slot_index=max_slot + 1,
        block_kind="due_review",
        subject_id=subject_id,
        task_name=f"{subj.name if subj else due_card.subject_name}: {due_card.chapter_name}",
        duration_minutes=30,
        is_fixed=False,
        is_optional=False,
    )
    db.add(block)
    db.flush()
    study_planner.add_due_link_to_block(db, block, due_card)
    day_blocks.append(block)
    return block


@app.post("/study-planner/api/add-due")
async def study_planner_api_add_due(request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    on_date = _parse_planner_date(payload.get("on") or "")
    revision_subject_id = str(payload.get("revision_subject_id") or "")
    revision_chapter_id = str(payload.get("revision_chapter_id") or "")

    subjects = list(db.scalars(select(Subject).order_by(Subject.sort_order, Subject.name)).all())
    revision_state = study_planner.load_revision_desk_state(db, uid)
    due_cards = study_planner.get_due_cards_for_day(revision_state, on_date)
    due_card = next(
        (
            c
            for c in due_cards
            if c.subject_id == revision_subject_id and c.chapter_id == revision_chapter_id
        ),
        None,
    )
    if not due_card:
        return _planner_day_payload_light(db, uid, on_date)

    mapped_subject_id = study_planner.map_due_card_subject_to_id(due_card, subjects)

    study_planner.ensure_week_blocks_safe(db, uid, on_date)
    db.flush()

    # a manually-added due block means this day is no longer "empty"
    db.execute(
        delete(StudyPlannerBlock)
        .where(StudyPlannerBlock.owner_id == uid)
        .where(StudyPlannerBlock.on_date == on_date)
        .where(StudyPlannerBlock.block_kind == "placeholder")
    )
    db.flush()

    # always a standalone due-review block -- kept separate from Focused blocks,
    # which are reserved for studying new content
    _add_due_card_as_block(db, uid, on_date, mapped_subject_id, due_card)
    db.commit()
    return _planner_day_payload_light(db, uid, on_date)


@app.post("/study-planner/api/blocks/reorder")
async def study_planner_api_blocks_reorder(request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    on_date = _parse_planner_date(payload.get("on") or "")
    order = payload.get("order") or []
    if not isinstance(order, list):
        raise HTTPException(status_code=400, detail="Invalid order")

    day_blocks = list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == uid)
            .where(StudyPlannerBlock.on_date == on_date)
        )
    )
    # any block -- fixed included -- can be dragged into a new position
    blocks_by_id = {b.id: b for b in day_blocks}

    next_slot = 0
    seen: set[int] = set()
    targets: list[tuple[StudyPlannerBlock, int]] = []
    for raw_id in order:
        try:
            bid = int(raw_id)
        except (TypeError, ValueError):
            continue
        block = blocks_by_id.get(bid)
        if not block or bid in seen:
            continue
        targets.append((block, next_slot))
        next_slot += 1
        seen.add(bid)

    # two-phase update: the unique(owner_id, on_date, slot_index) constraint is checked
    # per-row, so reassigning slots directly can transiently collide mid-flush for
    # permutations that aren't a simple append (e.g. swaps)
    for i, (block, _) in enumerate(targets):
        block.slot_index = -(i + 1)
    db.flush()
    for block, slot in targets:
        block.slot_index = slot

    db.commit()
    return _planner_day_payload_light(db, uid, on_date)


def _ics_escape(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _ensure_calendar_token(db: Session, user: User) -> str:
    if not user.calendar_token:
        user.calendar_token = secrets.token_urlsafe(24)
        db.commit()
    return user.calendar_token


@app.get("/study-planner/calendar/{user_id}.ics")
def study_planner_calendar_ics(user_id: int, token: str = "", db: Session = Depends(get_db)):
    # Subscribed to directly by external calendar apps (Google/Apple/Outlook),
    # so this can't rely on the session cookie -- a per-user secret token instead.
    user = db.get(User, user_id)
    if not user or not user.calendar_token or not secrets.compare_digest(user.calendar_token, token):
        raise HTTPException(status_code=404)

    today = date.today()
    range_start = today - timedelta(days=7)
    range_end = today + timedelta(days=28)

    seen_weeks: set[date] = set()
    cursor = range_start
    while cursor <= range_end:
        week_start = study_planner.week_start_monday(cursor)
        if week_start not in seen_weeks:
            seen_weeks.add(week_start)
            study_planner.ensure_week_blocks_safe(db, user_id, cursor)
        cursor += timedelta(days=7)
    db.commit()

    blocks = list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == user_id)
            .where(StudyPlannerBlock.on_date >= range_start)
            .where(StudyPlannerBlock.on_date <= range_end)
            .where(StudyPlannerBlock.block_kind != "placeholder")
            .order_by(StudyPlannerBlock.on_date, StudyPlannerBlock.slot_index)
        )
    )
    subjects_by_id = {s.id: s for s in db.scalars(select(Subject))}
    tzid = get_settings().app_timezone
    now_stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//StudyMate//Study Planner//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:StudyMate Study Planner",
        f"X-WR-TIMEZONE:{tzid}",
    ]
    for b in blocks:
        subj = subjects_by_id.get(b.subject_id)
        icon = f"{subj.icon} " if subj and subj.icon else ""
        summary = f"{icon}{b.task_name or (subj.name if subj else 'Study block')}"
        start_hm = b.start_time or "17:00"
        start_dt = datetime.combine(b.on_date, time.fromisoformat(start_hm))
        if b.end_time:
            end_dt = datetime.combine(b.on_date, time.fromisoformat(b.end_time))
        else:
            end_dt = start_dt + timedelta(minutes=b.duration_minutes or 50)
        desc_bits = [f"Subject: {subj.name}"] if subj else []
        if b.is_fixed:
            desc_bits.append("Fixed block")
        if b.completed:
            desc_bits.append("Completed in StudyMate")
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:studymate-block-{b.id}@studymate.local")
        lines.append(f"DTSTAMP:{now_stamp}")
        lines.append(f"DTSTART;TZID={tzid}:{start_dt.strftime('%Y%m%dT%H%M%S')}")
        lines.append(f"DTEND;TZID={tzid}:{end_dt.strftime('%Y%m%dT%H%M%S')}")
        lines.append(f"SUMMARY:{_ics_escape(summary)}")
        lines.append(f"DESCRIPTION:{_ics_escape(' / '.join(desc_bits) or 'Generated by StudyMate Study Planner')}")
        lines.append(f"STATUS:{'CONFIRMED' if not b.completed else 'CONFIRMED'}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    body = "\r\n".join(lines) + "\r\n"
    return Response(content=body, media_type="text/calendar; charset=utf-8")


@app.post("/settings/calendar-token/regenerate")
def settings_calendar_token_regenerate(request: Request, db: Session = Depends(get_db)):
    uid = _uid(request)
    user = db.get(User, uid)
    if not user:
        raise HTTPException(404)
    user.calendar_token = secrets.token_urlsafe(24)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.get("/study-planner", response_class=HTMLResponse)
def study_planner_view(
    request: Request,
    on: str = "",
    view: str = "timeline",
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    try:
        on_date = date.fromisoformat(on) if on else date.today()
    except ValueError:
        on_date = date.today()

    week_start = study_planner.week_start_monday(on_date)
    study_planner.ensure_week_blocks_safe(db, uid, on_date)
    db.commit()

    week_blocks = study_planner.get_week_blocks(db, uid, week_start)
    day_blocks = [b for b in week_blocks if b.on_date == on_date]
    blocks_by_day: dict[date, list[StudyPlannerBlock]] = {week_start + timedelta(days=i): [] for i in range(7)}
    for b in week_blocks:
        blocks_by_day.setdefault(b.on_date, []).append(b)

    subjects = list(db.scalars(select(Subject).order_by(Subject.sort_order, Subject.name)).all())
    subject_by_id = {s.id: s for s in subjects}

    revision_state = study_planner.load_revision_desk_state(db, uid)
    due_cards = study_planner.get_due_cards_for_day(revision_state, on_date)

    due_cards_mapped: list[dict] = []
    for c in due_cards:
        sid = study_planner.map_due_card_subject_to_id(c, subjects)
        due_cards_mapped.append(
            {
                "subject_id": sid,
                "revision_subject_id": c.subject_id,
                "revision_chapter_id": c.chapter_id,
                "subject_name": c.subject_name,
                "chapter_name": c.chapter_name,
                "due_date": c.due_date,
            }
        )

    linked_keys = {
        f"{link.revision_subject_id}::{link.revision_chapter_id}"
        for b in day_blocks
        for link in b.revision_links
    }

    due_by_subject_id: dict[int, list[dict]] = {}
    for card in due_cards_mapped:
        sid = card["subject_id"]
        if sid is None:
            continue
        due_by_subject_id.setdefault(sid, []).append(card)

    weekly_totals = study_planner.weekly_subject_minutes(week_blocks)
    day_required = [b for b in day_blocks if not b.is_optional]
    day_completed = bool(day_required) and all(b.completed for b in day_required)
    streak_days = study_planner.planner_streak_days(db, uid, date.today())

    ctx = _common_ctx(request, db)
    ctx.update(
        {
            "planner_on": on_date,
            "planner_prev": on_date - timedelta(days=1),
            "planner_next": on_date + timedelta(days=1),
            "planner_week_start": week_start,
            "planner_week_dates": [week_start + timedelta(days=i) for i in range(7)],
            "planner_day_blocks": day_blocks,
            "planner_blocks_by_day": blocks_by_day,
            "planner_subjects": subjects,
            "planner_subject_by_id": subject_by_id,
            "planner_due_cards": due_cards_mapped,
            "planner_due_by_subject_id": due_by_subject_id,
            "planner_linked_keys": linked_keys,
            "planner_weekly_totals": weekly_totals,
            "planner_streak_days": streak_days,
            "planner_day_completed": day_completed,
            "planner_view": "week" if view == "week" else "timeline",
        }
    )
    return templates.TemplateResponse("study_planner.html", ctx)


@app.post("/study-planner/blocks/{block_id}/update")
def study_planner_block_update(
    block_id: int,
    request: Request,
    task_name: str = Form(""),
    duration_minutes: int = Form(50),
    subject_id: str = Form(""),
    start_time: str = Form(""),
    end_time: str = Form(""),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    block = db.get(StudyPlannerBlock, block_id)
    if not block or block.owner_id != uid:
        raise HTTPException(404)

    block.task_name = task_name.strip()
    block.duration_minutes = max(10, min(180, int(duration_minutes or 50)))
    block.start_time = _normalize_planner_time(start_time)
    block.end_time = _normalize_planner_time(end_time)

    if not block.is_fixed:
        block.subject_id = int(subject_id) if subject_id else None

    db.commit()
    return RedirectResponse(
        request.headers.get("referer") or f"/study-planner?on={block.on_date.isoformat()}",
        status_code=303,
    )


@app.post("/study-planner/blocks/{block_id}/toggle")
def study_planner_block_toggle(
    block_id: int,
    request: Request,
    completed: str = Form(""),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    block = db.get(StudyPlannerBlock, block_id)
    if not block or block.owner_id != uid:
        raise HTTPException(404)

    now_completed = completed == "1"
    was_completed = bool(block.completed)
    block.completed = now_completed
    block.completed_at = datetime.utcnow() if now_completed else None

    if now_completed and not was_completed and block.revision_pushed_at is None:
        pushed = study_planner.push_block_links_to_revision_state(db, uid, block)
        if pushed > 0:
            block.revision_pushed_at = datetime.utcnow()

    db.commit()
    return RedirectResponse(
        request.headers.get("referer") or f"/study-planner?on={block.on_date.isoformat()}",
        status_code=303,
    )


@app.post("/study-planner/blocks/{block_id}/move")
def study_planner_block_move(
    block_id: int,
    request: Request,
    direction: str = Form("up"),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    block = db.get(StudyPlannerBlock, block_id)
    if not block or block.owner_id != uid:
        raise HTTPException(404)
    if block.is_fixed:
        return RedirectResponse(
            request.headers.get("referer") or f"/study-planner?on={block.on_date.isoformat()}",
            status_code=303,
        )

    day_blocks = list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == uid)
            .where(StudyPlannerBlock.on_date == block.on_date)
            .order_by(StudyPlannerBlock.slot_index, StudyPlannerBlock.id)
        )
    )
    movable = [b for b in day_blocks if not b.is_fixed]
    try:
        idx = [b.id for b in movable].index(block.id)
    except ValueError:
        idx = -1

    if idx >= 0:
        swap_idx = idx - 1 if direction == "up" else idx + 1
        if 0 <= swap_idx < len(movable):
            other = movable[swap_idx]
            a_slot, b_slot = block.slot_index, other.slot_index
            # two-phase update: the unique(owner_id, on_date, slot_index) constraint is
            # checked per-row, so swapping directly can transiently collide mid-flush
            block.slot_index, other.slot_index = -1, -2
            db.flush()
            block.slot_index, other.slot_index = b_slot, a_slot

    db.commit()
    return RedirectResponse(
        request.headers.get("referer") or f"/study-planner?on={block.on_date.isoformat()}",
        status_code=303,
    )


@app.post("/study-planner/blocks/reorder")
async def study_planner_blocks_reorder(request: Request, db: Session = Depends(get_db)):
    """Drag-and-drop reorder for rotating blocks (fixed blocks always stay first)."""
    uid = _uid(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        on_date = date.fromisoformat(str(payload.get("on") or ""))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")
    order = payload.get("order") or []
    if not isinstance(order, list):
        raise HTTPException(status_code=400, detail="Invalid order")

    day_blocks = list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == uid)
            .where(StudyPlannerBlock.on_date == on_date)
        )
    )
    fixed_count = sum(1 for b in day_blocks if b.is_fixed)
    movable_by_id = {b.id: b for b in day_blocks if not b.is_fixed}

    next_slot = fixed_count
    seen: set[int] = set()
    targets: list[tuple[StudyPlannerBlock, int]] = []
    for raw_id in order:
        try:
            bid = int(raw_id)
        except (TypeError, ValueError):
            continue
        block = movable_by_id.get(bid)
        if not block or bid in seen:
            continue
        targets.append((block, next_slot))
        next_slot += 1
        seen.add(bid)

    # two-phase update: avoids a transient unique(owner_id, on_date, slot_index) collision
    for i, (block, _) in enumerate(targets):
        block.slot_index = -(i + 1)
    db.flush()
    for block, slot in targets:
        block.slot_index = slot

    db.commit()
    return {"ok": True}


@app.post("/study-planner/blocks/{block_id}/pull-subject-due")
def study_planner_pull_subject_due(
    block_id: int,
    request: Request,
    on: str = Form(""),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    block = db.get(StudyPlannerBlock, block_id)
    if not block or block.owner_id != uid:
        raise HTTPException(404)
    if not block.subject_id:
        return RedirectResponse(
            request.headers.get("referer") or f"/study-planner?on={block.on_date.isoformat()}",
            status_code=303,
        )

    on_date = block.on_date
    if on:
        try:
            on_date = date.fromisoformat(on)
        except ValueError:
            on_date = block.on_date

    subjects = list(db.scalars(select(Subject).order_by(Subject.sort_order, Subject.name)).all())
    revision_state = study_planner.load_revision_desk_state(db, uid)
    due_cards = study_planner.get_due_cards_for_day(revision_state, on_date)

    added = False
    for card in due_cards:
        sid = study_planner.map_due_card_subject_to_id(card, subjects)
        if sid != block.subject_id:
            continue
        added = study_planner.add_due_link_to_block(db, block, card) or added

    if added and not block.task_name.strip():
        subj = db.get(Subject, block.subject_id)
        if subj:
            block.task_name = f"{subj.name}: due revision cards"

    db.commit()
    return RedirectResponse(
        request.headers.get("referer") or f"/study-planner?on={on_date.isoformat()}",
        status_code=303,
    )


@app.post("/study-planner/add-due")
def study_planner_add_due_to_day(
    request: Request,
    on: str = Form(...),
    revision_subject_id: str = Form(...),
    revision_chapter_id: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = _uid(request)
    try:
        on_date = date.fromisoformat(on)
    except ValueError:
        on_date = date.today()

    subjects = list(db.scalars(select(Subject).order_by(Subject.sort_order, Subject.name)).all())
    revision_state = study_planner.load_revision_desk_state(db, uid)
    due_cards = study_planner.get_due_cards_for_day(revision_state, on_date)
    due_card = next(
        (
            c
            for c in due_cards
            if c.subject_id == revision_subject_id and c.chapter_id == revision_chapter_id
        ),
        None,
    )
    if not due_card:
        return RedirectResponse(f"/study-planner?on={on_date.isoformat()}", status_code=303)

    mapped_subject_id = study_planner.map_due_card_subject_to_id(due_card, subjects)
    if mapped_subject_id is None:
        return RedirectResponse(f"/study-planner?on={on_date.isoformat()}", status_code=303)

    study_planner.ensure_week_blocks_safe(db, uid, on_date)
    db.flush()

    day_blocks = list(
        db.scalars(
            select(StudyPlannerBlock)
            .where(StudyPlannerBlock.owner_id == uid)
            .where(StudyPlannerBlock.on_date == on_date)
            .order_by(StudyPlannerBlock.slot_index, StudyPlannerBlock.id)
        )
    )
    target = next(
        (
            b
            for b in day_blocks
            if (not b.is_fixed) and b.subject_id == mapped_subject_id
        ),
        None,
    )

    if target is None:
        max_slot = max((b.slot_index for b in day_blocks), default=-1)
        subj = db.get(Subject, mapped_subject_id)
        target = StudyPlannerBlock(
            owner_id=uid,
            on_date=on_date,
            slot_index=max_slot + 1,
            block_kind="rotating",
            subject_id=mapped_subject_id,
            task_name=f"{subj.name if subj else 'Subject'}: due revision cards",
            duration_minutes=50,
            is_fixed=False,
            is_optional=False,
        )
        db.add(target)
        db.flush()

    study_planner.add_due_link_to_block(db, target, due_card)
    db.commit()
    return RedirectResponse(f"/study-planner?on={on_date.isoformat()}", status_code=303)


# ---------- auth: login / logout ----------

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/", error: str = "", db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "next": next,
            "error": error,
            "today": date.today(),
            "subjects": [],
            "WEEKDAYS": WEEKDAYS,
            "current_user": None,
        },
    )


def _is_safe_next(next_path: str) -> bool:
    if not next_path or not next_path.startswith("/") or next_path.startswith("//"):
        return False
    try:
        parsed = urlparse(next_path)
    except Exception:
        return False
    return parsed.scheme == "" and parsed.netloc == ""


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == username.strip()))
    if not user or not auth.verify_password(password, user.password_hash):
        return RedirectResponse(
            f"/login?error=Invalid+username+or+password&next={next}", status_code=303
        )
    token = auth.make_session_token(user.id)
    # If the caller provided a safe path other than the generic '/', go there.
    # Otherwise redirect to a choice landing page so the student can pick Study Mate or Revision Desk.
    if _is_safe_next(next) and next != "/":
        final = next
    else:
        final = "/choose"
    resp = RedirectResponse(final, status_code=303)
    resp.set_cookie(
        auth.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        secure=(request.url.scheme == "https"),
        path="/",
    )
    return resp


@app.get("/logout")
@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE, path="/", samesite="lax")
    _apply_no_cache(resp)
    return resp





# ---------- admin: user management ----------

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    users = db.scalars(select(User).order_by(User.username)).all()
    ctx = _common_ctx(request, db)
    ctx["users"] = users
    return templates.TemplateResponse("users.html", ctx)


@app.post("/admin/users")
def admin_user_create(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(""),
    email: str = Form(""),
    anthropic_api_key: str = Form(""),
    is_admin: str = Form(""),
    db: Session = Depends(get_db),
):
    _require_admin(request, db)
    uname = username.strip()
    if not uname or not password:
        return RedirectResponse(
            "/admin/users?error=Username+and+password+required", status_code=303
        )
    if db.scalar(select(User).where(User.username == uname)):
        return RedirectResponse(
            "/admin/users?error=Username+already+exists", status_code=303
        )
    new_user = User(
        username=uname,
        display_name=display_name.strip(),
        email=email.strip(),
        password_hash=auth.hash_password(password),
        anthropic_api_key=anthropic_api_key.strip(),
        is_admin=bool(is_admin),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    auth.provision_user_workspace(db, new_user)
    return RedirectResponse("/admin/users", status_code=303)


@app.post("/admin/users/{user_id}/edit")
def admin_user_edit(
    user_id: int,
    request: Request,
    display_name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    anthropic_api_key: str = Form(""),
    api_key_action: str = Form(""),  # "" | "set" | "clear"
    is_admin: str = Form(""),
    db: Session = Depends(get_db),
):
    me = _require_admin(request, db)
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404)
    target.display_name = display_name.strip()
    target.email = email.strip()
    if password.strip():
        target.password_hash = auth.hash_password(password)
    # API key handling
    if api_key_action == "clear":
        target.anthropic_api_key = ""
    elif anthropic_api_key.strip():
        target.anthropic_api_key = anthropic_api_key.strip()
    # Don't let an admin remove their own admin flag (avoids lockout).
    if target.id != me.id:
        target.is_admin = bool(is_admin)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@app.post("/admin/users/{user_id}/delete")
def admin_user_delete(user_id: int, request: Request, db: Session = Depends(get_db)):
    me = _require_admin(request, db)
    if user_id == me.id:
        return RedirectResponse(
            "/admin/users?error=You+cannot+delete+your+own+account",
            status_code=303,
        )
    target = db.get(User, user_id)
    if target:
        # Wipe all user-scoped data first (FK references aren't cascading on owner_id).
        db.query(StudySession).filter(StudySession.owner_id == user_id).delete()
        db.query(NoteFile).filter(NoteFile.owner_id == user_id).delete()
        db.query(ChatMessage).filter(ChatMessage.owner_id == user_id).delete()
        db.query(StudyPlannerRevisionLink).filter(StudyPlannerRevisionLink.block_id.in_(
            select(StudyPlannerBlock.id).where(StudyPlannerBlock.owner_id == user_id)
        )).delete(synchronize_session=False)
        db.query(StudyPlannerBlock).filter(StudyPlannerBlock.owner_id == user_id).delete()
        db.query(Task).filter(Task.owner_id == user_id).delete()
        db.query(Deadline).filter(Deadline.owner_id == user_id).delete()
        db.query(AvailabilityRule).filter(AvailabilityRule.owner_id == user_id).delete()
        db.query(AvailabilityException).filter(AvailabilityException.owner_id == user_id).delete()
        # Topics last (they're referenced by sessions/tasks/etc above).
        db.query(Topic).filter(Topic.owner_id == user_id).delete()
        db.delete(target)
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@app.get("/account", response_class=HTMLResponse)
def account_view(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    ctx = _common_ctx(request, db)
    ctx["account_user"] = user
    return templates.TemplateResponse("account.html", ctx)


@app.post("/account")
def account_update(
    request: Request,
    display_name: str = Form(""),
    email: str = Form(""),
    current_password: str = Form(""),
    new_password: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    user.display_name = display_name.strip()
    user.email = email.strip()
    if new_password.strip():
        if not auth.verify_password(current_password, user.password_hash):
            return RedirectResponse("/account?error=current+password+incorrect", status_code=303)
        user.password_hash = auth.hash_password(new_password)
    db.commit()
    return RedirectResponse("/account?ok=1", status_code=303)
