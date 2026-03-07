"""3-layer search API: search → timeline → get_requests."""
import sqlite3
from dataclasses import dataclass, field


@dataclass
class SearchResult:
    request_id: str
    session_id: str
    project_name: str | None
    user_message: str
    snippet: str
    timestamp: int | None
    rank: float
    obs_type: str | None = None
    title: str | None = None


@dataclass
class Preference:
    id: int
    project_name: str | None
    content: str
    source_request_id: str | None
    extracted_at: int | None


@dataclass
class TimelineEntry:
    request_id: str
    session_id: str
    seq_num: int
    timestamp: int | None
    user_message: str
    assistant_response: str
    is_anchor: bool = False


@dataclass
class FullRequest:
    request_id: str
    session_id: str
    project_name: str | None
    seq_num: int
    timestamp: int | None
    user_message: str
    assistant_response: str
    thinking_text: str
    agent_id: str | None
    model_id: str | None
    file_references: list[dict] = field(default_factory=list)
    code_blocks: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class ProjectSummary:
    project_name: str
    session_count: int
    request_count: int
    earliest: int | None
    latest: int | None


def search(
    conn: sqlite3.Connection,
    query: str,
    project: str | None = None,
    obs_type: str | None = None,
    limit: int = 20,
) -> list[SearchResult]:
    """FTS5 search across user messages and assistant responses."""
    # Build WHERE clause additions
    extra_where = ""
    params: list = [query]
    if project:
        extra_where += " AND s.project_name = ?"
        params.append(project)
    if obs_type:
        extra_where += " AND r.obs_type = ?"
        params.append(obs_type)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT r.request_id, r.session_id, s.project_name,
               r.user_message, r.timestamp, r.obs_type, r.title,
               snippet(requests_fts, 0, '[', ']', '...', 20) AS snip,
               requests_fts.rank
        FROM requests_fts
        JOIN requests r ON requests_fts.rowid = r.rowid
        JOIN sessions s ON r.session_id = s.session_id
        WHERE requests_fts MATCH ?{extra_where}
        ORDER BY requests_fts.rank
        LIMIT ?
        """,
        params,
    ).fetchall()

    return [
        SearchResult(
            request_id=row["request_id"],
            session_id=row["session_id"],
            project_name=row["project_name"],
            user_message=row["user_message"][:200],
            snippet=row["snip"] or "",
            timestamp=row["timestamp"],
            rank=row["rank"],
            obs_type=row["obs_type"],
            title=row["title"],
        )
        for row in rows
    ]


def timeline(
    conn: sqlite3.Connection,
    anchor_request_id: str,
    before: int = 5,
    after: int = 5,
) -> list[TimelineEntry]:
    """Return surrounding requests in the same session for context."""
    anchor = conn.execute(
        "SELECT session_id, seq_num FROM requests WHERE request_id = ?",
        (anchor_request_id,),
    ).fetchone()

    if not anchor:
        return []

    session_id = anchor["session_id"]
    seq_num = anchor["seq_num"]

    rows = conn.execute(
        """
        SELECT request_id, seq_num, timestamp, user_message, assistant_response
        FROM requests
        WHERE session_id = ?
          AND seq_num BETWEEN ? AND ?
        ORDER BY seq_num
        """,
        (session_id, seq_num - before, seq_num + after),
    ).fetchall()

    return [
        TimelineEntry(
            request_id=row["request_id"],
            session_id=session_id,
            seq_num=row["seq_num"],
            timestamp=row["timestamp"],
            user_message=row["user_message"],
            assistant_response=(row["assistant_response"] or "")[:500],
            is_anchor=(row["request_id"] == anchor_request_id),
        )
        for row in rows
    ]


def get_requests(conn: sqlite3.Connection, request_ids: list[str]) -> list[FullRequest]:
    """Fetch full details for specific request IDs."""
    if not request_ids:
        return []

    placeholders = ",".join("?" * len(request_ids))
    rows = conn.execute(
        f"""
        SELECT r.*, s.project_name
        FROM requests r
        JOIN sessions s ON r.session_id = s.session_id
        WHERE r.request_id IN ({placeholders})
        """,
        request_ids,
    ).fetchall()

    results = []
    for row in rows:
        rid = row["request_id"]

        file_refs = conn.execute(
            "SELECT file_path, description FROM file_references WHERE request_id = ?", (rid,)
        ).fetchall()
        code_blocks = conn.execute(
            "SELECT language, code, context_text FROM code_blocks WHERE request_id = ?", (rid,)
        ).fetchall()
        tool_calls = conn.execute(
            "SELECT tool_id, tool_label, invocation_message FROM tool_calls WHERE request_id = ?", (rid,)
        ).fetchall()

        results.append(FullRequest(
            request_id=rid,
            session_id=row["session_id"],
            project_name=row["project_name"],
            seq_num=row["seq_num"],
            timestamp=row["timestamp"],
            user_message=row["user_message"],
            assistant_response=row["assistant_response"] or "",
            thinking_text=row["thinking_text"] or "",
            agent_id=row["agent_id"],
            model_id=row["model_id"],
            file_references=[dict(r) for r in file_refs],
            code_blocks=[dict(r) for r in code_blocks],
            tool_calls=[dict(r) for r in tool_calls],
        ))

    return results


def list_projects(conn: sqlite3.Connection) -> list[ProjectSummary]:
    rows = conn.execute(
        """
        SELECT s.project_name,
               COUNT(DISTINCT s.session_id) AS session_count,
               COUNT(r.request_id)           AS request_count,
               MIN(r.timestamp)              AS earliest,
               MAX(r.timestamp)              AS latest
        FROM sessions s
        LEFT JOIN requests r ON s.session_id = r.session_id
        WHERE s.project_name IS NOT NULL
        GROUP BY s.project_name
        ORDER BY latest DESC NULLS LAST
        """
    ).fetchall()

    return [
        ProjectSummary(
            project_name=row["project_name"],
            session_count=row["session_count"],
            request_count=row["request_count"],
            earliest=row["earliest"],
            latest=row["latest"],
        )
        for row in rows
    ]


def recent(
    conn: sqlite3.Connection,
    project: str | None = None,
    obs_type: str | None = None,
    limit: int = 10,
) -> list[SearchResult]:
    """Get most recent requests, optionally filtered by project or obs_type."""
    extra_where = ""
    params: list = []
    if project:
        extra_where += " AND s.project_name = ?"
        params.append(project)
    if obs_type:
        extra_where += " AND r.obs_type = ?"
        params.append(obs_type)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT r.request_id, r.session_id, s.project_name,
               r.user_message, r.timestamp, r.obs_type, r.title
        FROM requests r
        JOIN sessions s ON r.session_id = s.session_id
        WHERE 1=1{extra_where}
        ORDER BY r.timestamp DESC NULLS LAST, r.rowid DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    return [
        SearchResult(
            request_id=row["request_id"],
            session_id=row["session_id"],
            project_name=row["project_name"],
            user_message=row["user_message"][:200],
            snippet=row["user_message"][:200],
            timestamp=row["timestamp"],
            rank=0.0,
            obs_type=row["obs_type"],
            title=row["title"],
        )
        for row in rows
    ]


def get_preferences(
    conn: sqlite3.Connection,
    project: str | None = None,
) -> list[Preference]:
    if project:
        rows = conn.execute(
            "SELECT * FROM preferences WHERE project_name = ? ORDER BY extracted_at DESC",
            (project,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM preferences ORDER BY project_name, extracted_at DESC"
        ).fetchall()
    return [
        Preference(
            id=r["id"],
            project_name=r["project_name"],
            content=r["content"],
            source_request_id=r["source_request_id"],
            extracted_at=r["extracted_at"],
        )
        for r in rows
    ]
