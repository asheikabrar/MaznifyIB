from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- lightweight migrations ----------
# create_all() doesn't add new columns to existing tables. For SQLite we
# introspect and add any missing columns ourselves. Keep this list short and
# only for additive changes; for anything bigger, switch to Alembic.
_MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, DDL fragment)
    ("tasks", "progress_pct", "INTEGER NOT NULL DEFAULT 0"),
    ("topics", "notes", "TEXT NOT NULL DEFAULT ''"),
    ("topics", "parent_id", "INTEGER NULL REFERENCES topics(id)"),
    ("topics", "step", "INTEGER NOT NULL DEFAULT 0"),
    ("subjects", "icon", "VARCHAR(40) NOT NULL DEFAULT ''"),
    ("deadlines", "progress_pct", "INTEGER NOT NULL DEFAULT 0"),
    ("subjects", "sort_order", "INTEGER NOT NULL DEFAULT 100"),
    ("users", "anthropic_api_key", "VARCHAR(300) NOT NULL DEFAULT ''"),
    ("tasks", "scheduled_for", "DATETIME NULL"),
    ("tasks", "topic_id", "INTEGER NULL REFERENCES topics(id)"),
    ("deadlines", "topic_id", "INTEGER NULL REFERENCES topics(id)"),
    ("note_files", "task_id", "INTEGER NULL REFERENCES tasks(id)"),
    ("tasks", "recurrence_rule", "VARCHAR(80) NOT NULL DEFAULT ''"),
    ("tasks", "recurrence_until", "DATE NULL"),
    # Per-user data isolation: every user-scoped table gets owner_id.
    ("topics", "owner_id", "INTEGER NULL REFERENCES users(id)"),
    ("tasks", "owner_id", "INTEGER NULL REFERENCES users(id)"),
    ("deadlines", "owner_id", "INTEGER NULL REFERENCES users(id)"),
    ("availability_rules", "owner_id", "INTEGER NULL REFERENCES users(id)"),
    ("availability_exceptions", "owner_id", "INTEGER NULL REFERENCES users(id)"),
    ("study_sessions", "owner_id", "INTEGER NULL REFERENCES users(id)"),
    ("note_files", "owner_id", "INTEGER NULL REFERENCES users(id)"),
    ("chat_messages", "owner_id", "INTEGER NULL REFERENCES users(id)"),
    ("chat_messages", "session_id", "INTEGER NULL REFERENCES chat_sessions(id)"),
]


_OWNER_TABLES = (
    "topics", "tasks", "deadlines",
    "availability_rules", "availability_exceptions",
    "study_sessions", "note_files", "chat_messages",
)


def apply_lightweight_migrations() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    newly_added_owner_id_tables: list[str] = []
    with engine.begin() as conn:
        for table, column, ddl in _MIGRATIONS:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column in cols:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            if column == "owner_id" and table in _OWNER_TABLES:
                newly_added_owner_id_tables.append(table)

    # Back-fill: any pre-existing rows now have NULL owner_id. Assign them
    # to the first admin user so the historical data continues to belong
    # to a known account instead of leaking across new users.
    if newly_added_owner_id_tables:
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1")
            ).fetchone()
            if row:
                admin_id = row[0]
                for table in newly_added_owner_id_tables:
                    conn.execute(
                        text(f"UPDATE {table} SET owner_id = :uid WHERE owner_id IS NULL"),
                        {"uid": admin_id},
                    )
