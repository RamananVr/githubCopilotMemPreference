"""Incremental indexer: scans VS Code Copilot chat session files and upserts into SQLite."""
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import sys
import os
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import EMPTY_WINDOW_SESSIONS_ROOT, WORKSPACE_SESSIONS_ROOT
from src.parser.json_parser import parse_json_session
from src.parser.jsonl_parser import parse_jsonl_session
from src.parser.models import CopilotSession
from src.indexer.db import get_indexed_files, upsert_session


@dataclass
class IndexStats:
    scanned: int = 0
    indexed: int = 0
    skipped: int = 0
    errors: int = 0


def _resolve_workspace_folder(workspace_hash_dir: Path) -> str | None:
    """Read workspace.json to find the folder URI."""
    workspace_json = workspace_hash_dir / "workspace.json"
    if not workspace_json.exists():
        return None
    try:
        with open(workspace_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("folder") or data.get("folderUri")
    except (OSError, json.JSONDecodeError):
        return None


def _iter_session_files() -> list[tuple[Path, str | None, str | None]]:
    """
    Yield (session_file, workspace_folder, workspace_hash) tuples.
    workspace_folder and workspace_hash are None for empty-window sessions.
    """
    results = []

    # Workspace-bound sessions
    if WORKSPACE_SESSIONS_ROOT.exists():
        for hash_dir in WORKSPACE_SESSIONS_ROOT.iterdir():
            if not hash_dir.is_dir():
                continue
            chat_dir = hash_dir / "chatSessions"
            if not chat_dir.exists():
                continue
            workspace_folder = _resolve_workspace_folder(hash_dir)
            for ext in ("*.json", "*.jsonl"):
                for f in chat_dir.glob(ext):
                    results.append((f, workspace_folder, hash_dir.name))

    # Empty-window sessions
    if EMPTY_WINDOW_SESSIONS_ROOT.exists():
        for ext in ("*.json", "*.jsonl"):
            for f in EMPTY_WINDOW_SESSIONS_ROOT.glob(ext):
                results.append((f, None, None))

    return results


def run_index(conn: sqlite3.Connection, force: bool = False, classify: bool = False) -> IndexStats:
    """
    Scan all session files and index new/modified ones.
    If force=True, re-index everything.
    """
    stats = IndexStats()
    indexed_files = {} if force else get_indexed_files(conn)
    newly_indexed: list[tuple[str, str | None]] = []  # (session_id, project_name)

    for session_file, workspace_folder, workspace_hash in _iter_session_files():
        stats.scanned += 1
        file_path_str = str(session_file)

        try:
            current_mtime = session_file.stat().st_mtime
        except OSError:
            stats.errors += 1
            continue

        # Skip unchanged files
        if not force and indexed_files.get(file_path_str) == current_mtime:
            stats.skipped += 1
            continue

        # Parse
        try:
            if session_file.suffix == ".jsonl":
                session = parse_jsonl_session(file_path_str)
            else:
                session = parse_json_session(file_path_str)
        except Exception:
            stats.errors += 1
            continue

        if session is None:
            stats.errors += 1
            continue

        # Skip sessions with no requests
        if not session.requests:
            stats.skipped += 1
            continue

        # Attach workspace context
        session.workspace_folder = workspace_folder
        session.workspace_hash = workspace_hash

        try:
            upsert_session(conn, session)
            stats.indexed += 1
            newly_indexed.append((session.session_id, session.project_name))
        except Exception:
            stats.errors += 1

    if classify and newly_indexed:
        from src.llm.classifier import classify_session
        for sid, pname in newly_indexed:
            try:
                classify_session(conn, sid, pname)
            except Exception:
                stats.errors += 1

    return stats
