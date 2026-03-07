"""Generate and inject context blocks for Copilot and Claude Code."""
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import (
    CONTEXT_MARKER_END,
    CONTEXT_MARKER_START,
    CONTEXT_MD_PATH,
    COPILOT_INSTRUCTIONS_PATH,
)

_OBS_LABEL = {
    "bugfix":    "bugfix",
    "feature":   "feature",
    "refactor":  "refactor",
    "discovery": "discovery",
    "decision":  "decision",
    "change":    "change",
    "other":     "other",
}


def generate_context_block(conn: sqlite3.Connection, limit: int = 50, hours: int = 72) -> str:
    cutoff_ms = int((datetime.now(timezone.utc).timestamp() - hours * 3600) * 1000)

    # Use COALESCE(r.timestamp, s.indexed_at) so sessions without per-request
    # timestamps still appear (older .json format has no request-level timestamps)
    rows = conn.execute(
        """
        SELECT r.request_id, r.seq_num,
               COALESCE(r.timestamp, s.indexed_at) AS effective_ts,
               r.obs_type, r.title,
               s.session_id, s.project_name
        FROM requests r
        JOIN sessions s ON r.session_id = s.session_id
        WHERE COALESCE(r.timestamp, s.indexed_at) > ?
          AND r.obs_type IS NOT NULL AND r.title IS NOT NULL
        ORDER BY s.project_name, effective_ts DESC
        LIMIT ?
        """,
        (cutoff_ms, limit),
    ).fetchall()

    if not rows:
        return ""

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        CONTEXT_MARKER_START,
        f"# [copilot-mem] recent context, {now_str}",
        "**Legend:** session-request | bugfix | feature | refactor | change | discovery | decision",
        "",
    ]

    # Group by project
    projects: dict[str, list] = {}
    for row in rows:
        pname = row["project_name"] or "(no project)"
        projects.setdefault(pname, []).append(row)

    for project_name, reqs in projects.items():
        lines.append(f"### {project_name}")
        lines.append("| ID | Time | Type | Title |")
        lines.append("|----|------|------|-------|")
        for req in reqs:
            ts = ""
            if req["effective_ts"]:
                ts = datetime.fromtimestamp(req["effective_ts"] / 1000).strftime("%I:%M %p")
            obs = _OBS_LABEL.get(req["obs_type"] or "other", "other")
            title = req["title"] or ""
            rid = f"#{req['session_id'][:6]}-{req['seq_num']}"
            lines.append(f"| {rid} | {ts} | {obs} | {title} |")
        lines.append("")

    # Preferences summary
    pref_rows = conn.execute(
        """SELECT project_name, content FROM preferences
           ORDER BY project_name, extracted_at DESC LIMIT 20"""
    ).fetchall()

    if pref_rows:
        lines.append("### Preferences & Decisions")
        for pr in pref_rows:
            proj = pr["project_name"] or "(global)"
            lines.append(f"- **{proj}**: {pr['content']}")
        lines.append("")

    lines.append(CONTEXT_MARKER_END)
    return "\n".join(lines)


def write_copilot_instructions(context_block: str) -> None:
    path = COPILOT_INSTRUCTIONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        content = path.read_text(encoding="utf-8")
        if CONTEXT_MARKER_START in content:
            pattern = re.escape(CONTEXT_MARKER_START) + r".*?" + re.escape(CONTEXT_MARKER_END)
            content = re.sub(pattern, context_block, content, flags=re.DOTALL)
        else:
            content = content.rstrip() + "\n\n" + context_block + "\n"
    else:
        content = context_block + "\n"

    path.write_text(content, encoding="utf-8")


def write_context_md(context_block: str) -> None:
    path = CONTEXT_MD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(context_block, encoding="utf-8")


def inject_context(conn: sqlite3.Connection, limit: int = 50, hours: int = 72) -> str:
    block = generate_context_block(conn, limit=limit, hours=hours)
    if block:
        write_copilot_instructions(block)
        write_context_md(block)
    return block
