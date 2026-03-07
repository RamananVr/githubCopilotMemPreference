"""SQLite database layer with FTS5 full-text search."""
import sqlite3
import time
from pathlib import Path

from ..parser.models import CopilotSession


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize (or open) the database, creating schema if needed."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_schema(conn)
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id       TEXT PRIMARY KEY,
            workspace_folder TEXT,
            workspace_hash   TEXT,
            project_name     TEXT,
            creation_date    INTEGER,
            custom_title     TEXT,
            initial_location TEXT,
            model_id         TEXT,
            source_file      TEXT NOT NULL,
            file_mtime       REAL NOT NULL,
            indexed_at       INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS requests (
            request_id             TEXT PRIMARY KEY,
            session_id             TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            seq_num                INTEGER NOT NULL,
            timestamp              INTEGER,
            user_message           TEXT NOT NULL,
            assistant_response     TEXT,
            thinking_text          TEXT,
            agent_id               TEXT,
            model_id               TEXT,
            timing_first_progress  INTEGER,
            timing_total_elapsed   INTEGER
        );

        CREATE TABLE IF NOT EXISTS file_references (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id  TEXT NOT NULL REFERENCES requests(request_id) ON DELETE CASCADE,
            file_path   TEXT NOT NULL,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS code_blocks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id   TEXT NOT NULL REFERENCES requests(request_id) ON DELETE CASCADE,
            language     TEXT,
            code         TEXT NOT NULL,
            context_text TEXT
        );

        CREATE TABLE IF NOT EXISTS tool_calls (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id         TEXT NOT NULL REFERENCES requests(request_id) ON DELETE CASCADE,
            tool_id            TEXT,
            tool_label         TEXT,
            invocation_message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_requests_session    ON requests(session_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_project    ON sessions(project_name);
        CREATE INDEX IF NOT EXISTS idx_sessions_creation   ON sessions(creation_date);
        CREATE INDEX IF NOT EXISTS idx_file_refs_request   ON file_references(request_id);
        CREATE INDEX IF NOT EXISTS idx_code_blocks_request ON code_blocks(request_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS requests_fts USING fts5(
            user_message,
            assistant_response,
            thinking_text,
            content='requests',
            content_rowid='rowid',
            tokenize='porter unicode61'
        );
    """)

    # Ensure triggers exist (CREATE TRIGGER IF NOT EXISTS not supported in older SQLite)
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    if "requests_ai" not in triggers:
        conn.execute("""
            CREATE TRIGGER requests_ai AFTER INSERT ON requests BEGIN
                INSERT INTO requests_fts(rowid, user_message, assistant_response, thinking_text)
                VALUES (new.rowid, new.user_message, new.assistant_response, new.thinking_text);
            END
        """)
    if "requests_ad" not in triggers:
        conn.execute("""
            CREATE TRIGGER requests_ad AFTER DELETE ON requests BEGIN
                INSERT INTO requests_fts(requests_fts, rowid, user_message, assistant_response, thinking_text)
                VALUES ('delete', old.rowid, old.user_message, old.assistant_response, old.thinking_text);
            END
        """)

    _migrate_schema(conn)
    conn.commit()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Non-destructive migrations for new columns and tables."""
    req_cols = {row[1] for row in conn.execute("PRAGMA table_info(requests)").fetchall()}
    if "obs_type" not in req_cols:
        conn.execute("ALTER TABLE requests ADD COLUMN obs_type TEXT")
    if "title" not in req_cols:
        conn.execute("ALTER TABLE requests ADD COLUMN title TEXT")

    sess_cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "summary" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN summary TEXT")
    if "classified_at" not in sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN classified_at INTEGER")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS preferences (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name      TEXT,
            content           TEXT NOT NULL,
            source_request_id TEXT REFERENCES requests(request_id) ON DELETE SET NULL,
            extracted_at      INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_preferences_project ON preferences(project_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_obs_type ON requests(obs_type)")


def get_indexed_files(conn: sqlite3.Connection) -> dict[str, float]:
    """Return {source_file: file_mtime} for all indexed sessions."""
    rows = conn.execute("SELECT source_file, file_mtime FROM sessions").fetchall()
    return {row["source_file"]: row["file_mtime"] for row in rows}


def delete_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def upsert_session(conn: sqlite3.Connection, session: CopilotSession) -> None:
    """Insert or replace a session and all its child records."""
    from config import MAX_RESPONSE_CHARS

    # Delete existing records (cascade handles child tables)
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session.session_id,))

    conn.execute(
        """INSERT INTO sessions
           (session_id, workspace_folder, workspace_hash, project_name,
            creation_date, custom_title, initial_location, model_id,
            source_file, file_mtime, indexed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            session.session_id,
            session.workspace_folder,
            session.workspace_hash,
            session.project_name,
            session.creation_date,
            session.custom_title,
            session.initial_location,
            session.model_id,
            session.source_file,
            session.file_mtime,
            int(time.time() * 1000),
        ),
    )

    for req in session.requests:
        response = (req.assistant_response or "")[:MAX_RESPONSE_CHARS]

        conn.execute(
            """INSERT INTO requests
               (request_id, session_id, seq_num, timestamp,
                user_message, assistant_response, thinking_text,
                agent_id, model_id, timing_first_progress, timing_total_elapsed)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                req.request_id,
                session.session_id,
                req.seq_num,
                req.timestamp,
                req.user_message,
                response,
                (req.thinking_text or "")[:MAX_RESPONSE_CHARS],
                req.agent_id,
                req.model_id,
                req.timing_first_progress,
                req.timing_total_elapsed,
            ),
        )

        if req.file_references:
            conn.executemany(
                "INSERT INTO file_references (request_id, file_path, description) VALUES (?,?,?)",
                [(req.request_id, fr.file_path, fr.description) for fr in req.file_references],
            )

        if req.code_blocks:
            conn.executemany(
                "INSERT INTO code_blocks (request_id, language, code, context_text) VALUES (?,?,?,?)",
                [(req.request_id, cb.language, cb.code[:MAX_RESPONSE_CHARS], cb.context_text)
                 for cb in req.code_blocks],
            )

        if req.tool_calls:
            conn.executemany(
                "INSERT INTO tool_calls (request_id, tool_id, tool_label, invocation_message) VALUES (?,?,?,?)",
                [(req.request_id, tc.tool_id, tc.tool_label, tc.invocation_message)
                 for tc in req.tool_calls],
            )

    conn.commit()


def db_stats(conn: sqlite3.Connection) -> dict:
    sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    requests = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    projects = conn.execute("SELECT COUNT(DISTINCT project_name) FROM sessions WHERE project_name IS NOT NULL").fetchone()[0]
    return {"sessions": sessions, "requests": requests, "projects": projects}


def update_request_classification(conn: sqlite3.Connection, request_id: str, obs_type: str, title: str) -> None:
    conn.execute(
        "UPDATE requests SET obs_type = ?, title = ? WHERE request_id = ?",
        (obs_type, title, request_id),
    )


def update_session_summary(conn: sqlite3.Connection, session_id: str, summary: str) -> None:
    conn.execute(
        "UPDATE sessions SET summary = ?, classified_at = ? WHERE session_id = ?",
        (summary, int(time.time() * 1000), session_id),
    )


def insert_preferences(conn: sqlite3.Connection, preferences: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO preferences (project_name, content, source_request_id, extracted_at) VALUES (?,?,?,?)",
        [(p["project_name"], p["content"], p["source_request_id"], int(time.time() * 1000))
         for p in preferences],
    )


def get_unclassified_sessions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT session_id, project_name, creation_date FROM sessions
           WHERE classified_at IS NULL ORDER BY creation_date ASC"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_session_requests(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT request_id, seq_num, user_message, assistant_response, thinking_text, timestamp
           FROM requests WHERE session_id = ? ORDER BY seq_num""",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_preferences(conn: sqlite3.Connection, project: str | None = None) -> list[dict]:
    if project:
        rows = conn.execute(
            "SELECT * FROM preferences WHERE project_name = ? ORDER BY extracted_at DESC", (project,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM preferences ORDER BY project_name, extracted_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]
