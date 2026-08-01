# StudyMate DP1

A personal study companion for an IB DP1 student.

- 6 IB subjects pre-seeded (Biology HL, Chemistry HL, Math AA SL, English Lang & Lit SL, Business Management SL, Arabic ab initio SL).
- **Automatic spaced revision** with FSRS (modern successor to SM-2).
- **Term 1 backfill** — mark previously-studied topics with a confidence rating; they're seeded into the rotation.
- **Variable weekly availability** — different study slots per weekday; planner packs items into them.
- **Notes & images upload** — PDFs, images, handwritten photos. With an Anthropic key, Claude vision OCRs them.
- **Syllabus auto-import** — upload a syllabus PDF, tick "extract topics", and topics are added to the subject.
- **AI Coach (Claude)** — chat that can create tasks, mark topics done, change availability, etc., via tool-calling.

## Run locally (Windows / PowerShell)

```powershell
cd C:\Users\ahame\studymate-dp1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env       # then edit .env and add ANTHROPIC_API_KEY or COAGENT_ANTHROPIC_API_KEY
# Optional: set ANTHROPIC_MODEL to a supported free model like claude-3.5, claude-instant-1, or claude-4-mini
python -m app.seed
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 .

## Without an Anthropic key
Everything works *except* the AI Coach (it returns a stub message) and OCR of images/PDFs (the file is stored, no text extracted). You can still use the planner, FSRS revision, tasks, deadlines, and manual syllabus entry.

## Project layout
```
app/
  main.py        # FastAPI routes
  models.py      # SQLAlchemy models
  db.py          # Engine + session
  config.py      # Settings (.env)
  scheduler.py   # FSRS spaced revision
  planner.py     # Daily plan generator (slot packer)
  notes.py       # Uploads + OCR + syllabus extraction
  ai.py          # Claude chat with tool-calling
  seed.py        # Subjects + weekly availability
  templates/     # Jinja HTML (Tailwind via CDN)
uploads/         # Uploaded files (created on first upload)
```

## Daily flow
1. Open Today (`/`) — see slots packed with reviews + tasks.
2. After studying, hit **Again / Hard / Good / Easy** to update FSRS.
3. Add Term 1 topics from each subject page so they enter rotation.
4. Upload notes from `/notes`, optionally extracting syllabus topics.
5. Use the AI Coach for natural-language edits ("push today to tomorrow", "add IA deadline May 20", "explain glycolysis using my notes").

## Deploy later
- Backend: Railway / Fly.io
- DB: swap `DATABASE_URL` to a Neon Postgres URL
- Single `Procfile` line: `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`
