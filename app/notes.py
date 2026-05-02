"""Notes upload + lightweight syllabus extraction.

For text/PDFs we attempt a plain-text read. For images and unsupported types,
the file is stored and (if Anthropic is configured) Claude vision is used
to OCR the content. Without a key we just store the file.
"""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import NoteFile, Subject, Topic
from app.ai import get_anthropic_model, get_anthropic_model_candidates

settings = get_settings()


def _get_upload_dir() -> Path:
    upload_dir = Path(settings.upload_dir)
    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        return upload_dir
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "studymate-uploads"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def save_upload(
    db: Session,
    filename: str,
    mime: str,
    data: bytes,
    subject_id: int | None = None,
    topic_id: int | None = None,
) -> NoteFile:
    safe = filename.replace("/", "_").replace("\\", "_")
    upload_dir = _get_upload_dir()
    path = upload_dir / f"{int.from_bytes(os.urandom(4), 'big'):08x}_{safe}"
    path.write_bytes(data)

    extracted = _try_extract_text(path, mime, data)

    nf = NoteFile(
        subject_id=subject_id,
        topic_id=topic_id,
        filename=filename,
        mime=mime,
        storage_path=str(path),
        extracted_text=extracted,
    )
    db.add(nf)
    db.commit()
    db.refresh(nf)
    return nf


def _try_extract_text(path: Path, mime: str, data: bytes) -> str:
    if mime.startswith("text/") or path.suffix.lower() in {".txt", ".md"}:
        try:
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    # Images / PDFs: use Claude vision if key available
    if settings.anthropic_api_key and (mime.startswith("image/") or mime == "application/pdf"):
        return _claude_extract(path, mime, data)
    return ""


def _claude_extract(path: Path, mime: str, data: bytes) -> str:
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        model_names = get_anthropic_model_candidates(settings.anthropic_model)
        b64 = base64.standard_b64encode(data).decode("ascii")
        if mime.startswith("image/"):
            block = {
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": b64},
            }
        else:
            block = {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            }

        last_error: Exception | None = None
        for model_name in model_names:
            try:
                resp = client.messages.create(
                    model=model_name,
                    max_tokens=4000,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                block,
                                {
                                    "type": "text",
                                    "text": "Transcribe all readable text from this document. "
                                    "Return plain text only, preserving section headings and lists.",
                                },
                            ],
                        }
                    ],
                )
                return "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
            except Exception as e:
                last_error = e
                msg = str(e)
                if "not_found_error" in msg or ("model:" in msg and "not found" in msg):
                    continue
                raise
        if last_error:
            raise last_error
        return ""
    except Exception as e:  # pragma: no cover
        return f"[extraction failed: {e}]"


# ---------- syllabus extraction ----------

def extract_syllabus_topics(text: str) -> list[dict]:
    """Heuristic: lines like '1.2 Title' or 'Topic 3: Title'.

    Returns list of {code, title}. If no structure is detected, splits by lines
    longer than 6 chars.
    """
    import re

    topics: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) < 4:
            continue
        m = re.match(r"^(?:Topic\s+)?([\d]+(?:\.[\d]+)*)[\s:.\-]+(.{4,200})$", line)
        if m:
            topics.append({"code": m.group(1), "title": m.group(2).strip().rstrip(".")})
            continue
    if not topics:
        # fallback: every reasonable line becomes a topic
        for raw in text.splitlines():
            line = raw.strip(" -•\t")
            if 5 <= len(line) <= 160 and any(c.isalpha() for c in line):
                topics.append({"code": "", "title": line})
            if len(topics) >= 80:
                break
    return topics


def import_syllabus(db: Session, subject: Subject, items: Iterable[dict]) -> int:
    existing = {(t.code, t.title.lower()) for t in subject.topics}
    added = 0
    for it in items:
        key = (it.get("code", ""), it["title"].lower())
        if key in existing:
            continue
        db.add(
            Topic(
                subject_id=subject.id,
                code=it.get("code", ""),
                title=it["title"],
                ib_weight=it.get("ib_weight", 3),
            )
        )
        added += 1
    db.commit()
    return added
