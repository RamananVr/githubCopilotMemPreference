"""File system watcher for incremental auto-indexing of Copilot sessions."""
import sys
import time
import threading
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent, FileDeletedEvent

from config import (
    DB_PATH,
    EMPTY_WINDOW_SESSIONS_ROOT,
    WORKSPACE_SESSIONS_ROOT,
    WATCHER_DEBOUNCE_SECONDS,
)
from src.indexer.db import init_db, get_indexed_files
from src.parser.json_parser import parse_json_session
from src.parser.jsonl_parser import parse_jsonl_session
from src.indexer.db import upsert_session, delete_session


class _DebounceTimer:
    """Coalesces rapid file events into a single callback."""

    def __init__(self, delay: float, callback):
        self._delay = delay
        self._callback = callback
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def schedule(self, path: str):
        with self._lock:
            if path in self._pending:
                self._pending[path].cancel()
            timer = threading.Timer(self._delay, self._fire, args=(path,))
            self._pending[path] = timer
            timer.start()

    def _fire(self, path: str):
        with self._lock:
            self._pending.pop(path, None)
        self._callback(path)


class CopilotSessionHandler(FileSystemEventHandler):
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._debounce = _DebounceTimer(WATCHER_DEBOUNCE_SECONDS, self._index_file)

    def _is_session_file(self, path: str) -> bool:
        p = Path(path)
        return p.suffix in (".json", ".jsonl") and p.name != "workspace.json"

    def on_created(self, event):
        if not event.is_directory and self._is_session_file(event.src_path):
            self._debounce.schedule(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and self._is_session_file(event.src_path):
            self._debounce.schedule(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory and self._is_session_file(event.src_path):
            self._handle_delete(event.src_path)

    def _index_file(self, path: str):
        p = Path(path)
        if not p.exists():
            return
        try:
            if p.suffix == ".jsonl":
                session = parse_jsonl_session(path)
            else:
                session = parse_json_session(path)
            if session and session.requests:
                upsert_session(self._conn, session)
                print(f"[copilot-mem] Indexed: {p.name} ({len(session.requests)} requests)", flush=True)
        except Exception as e:
            print(f"[copilot-mem] Error indexing {path}: {e}", flush=True)

    def _handle_delete(self, path: str):
        # Find session_id by source_file
        row = self._conn.execute(
            "SELECT session_id FROM sessions WHERE source_file = ?", (path,)
        ).fetchone()
        if row:
            delete_session(self._conn, row["session_id"])
            self._conn.commit()
            print(f"[copilot-mem] Removed: {Path(path).name}", flush=True)


def watch():
    """Start watching Copilot session directories. Blocks until interrupted."""
    conn = init_db(str(DB_PATH))
    handler = CopilotSessionHandler(conn)
    observer = Observer()

    watched = []
    for watch_dir in [WORKSPACE_SESSIONS_ROOT, EMPTY_WINDOW_SESSIONS_ROOT]:
        if watch_dir.exists():
            observer.schedule(handler, str(watch_dir), recursive=True)
            watched.append(watch_dir)

    if not watched:
        print("[copilot-mem] No VS Code session directories found.", flush=True)
        return

    observer.start()
    print(f"[copilot-mem] Watching {len(watched)} director(ies). Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    conn.close()


if __name__ == "__main__":
    watch()
