"""LLM-enhanced and rule-based classification for CopilotRequests."""
import json
import os
import re
import sqlite3
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import ANTHROPIC_MODEL, CLASSIFIER_BATCH_SIZE, CLASSIFIER_MAX_MSG_CHARS, OBS_TYPES
from src.llm.prompts import (
    CLASSIFY_BATCH_USER,
    CLASSIFY_SYSTEM,
    PREFERENCES_SYSTEM,
    PREFERENCES_USER,
    SUMMARIZE_SYSTEM,
    SUMMARIZE_USER,
)
from src.indexer.db import (
    get_session_requests,
    get_unclassified_sessions,
    insert_preferences,
    update_request_classification,
    update_session_summary,
)


@dataclass
class ClassifyResult:
    sessions_processed: int = 0
    requests_classified: int = 0
    preferences_extracted: int = 0
    errors: int = 0
    used_llm: bool = False


def _get_anthropic_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


# ── Rule-based fallback ──────────────────────────────────────────────────────

_RULE_PATTERNS = {
    "bugfix":    re.compile(r"\b(bug|fix|error|crash|broken|issue|fail|wrong|not working|exception|traceback)\b", re.I),
    "refactor":  re.compile(r"\b(refactor|restructure|clean up|reorganize|simplify|extract|move|rename)\b", re.I),
    "decision":  re.compile(r"\b(decide|decision|choose|go with|prefer|should we|let.s use|approach)\b", re.I),
    "feature":   re.compile(r"\b(add|implement|create|build|new feature|introduce|support for)\b", re.I),
    "discovery": re.compile(r"\b(how does|what is|explain|understand|learn|investigate|why does|look into)\b", re.I),
    "change":    re.compile(r"\b(change|update|modify|switch|replace|migrate|convert|adjust)\b", re.I),
}


def _rule_classify(user_message: str) -> str:
    for obs_type in ("bugfix", "refactor", "decision", "feature", "discovery", "change"):
        if _RULE_PATTERNS[obs_type].search(user_message):
            return obs_type
    return "other"


def _rule_title(user_message: str) -> str:
    first_line = user_message.strip().split("\n")[0][:80]
    first_line = re.sub(r"[#*`]", "", first_line).strip()
    if len(first_line) > 60:
        first_line = first_line[:57] + "..."
    return first_line or "Untitled"


# ── LLM helpers ──────────────────────────────────────────────────────────────

def _strip_fencing(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _llm_classify_batch(client, requests: list[dict]) -> list[dict]:
    exchanges = []
    for r in requests:
        msg = (r["user_message"] or "")[:CLASSIFIER_MAX_MSG_CHARS]
        resp = (r["assistant_response"] or "")[:500]
        exchanges.append(f'[ID: {r["request_id"]}]\nUser: {msg}\nAssistant: {resp}')

    prompt = CLASSIFY_BATCH_USER.format(
        count=len(requests),
        exchanges="\n---\n".join(exchanges),
    )

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=CLASSIFY_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    results = json.loads(_strip_fencing(response.content[0].text))
    for r in results:
        if r.get("obs_type") not in OBS_TYPES:
            r["obs_type"] = "other"
    return results


def _llm_summarize(client, requests: list[dict], project_name: str) -> str:
    exchanges = [(r["user_message"] or "")[:CLASSIFIER_MAX_MSG_CHARS] for r in requests]
    prompt = SUMMARIZE_USER.format(
        request_count=len(requests),
        project_name=project_name or "(no project)",
        exchanges="\n---\n".join(f"User: {m}" for m in exchanges),
    )
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=512,
        system=SUMMARIZE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    data = json.loads(_strip_fencing(response.content[0].text))
    bullets = data.get("bullets", [])
    return "\n".join(f"- {b}" for b in bullets[:3])


def _llm_extract_preferences(client, requests: list[dict], project_name: str) -> list[str]:
    exchanges = []
    for r in requests:
        msg = (r["user_message"] or "")[:CLASSIFIER_MAX_MSG_CHARS]
        resp = (r["assistant_response"] or "")[:1000]
        exchanges.append(f"User: {msg}\nAssistant: {resp}")

    prompt = PREFERENCES_USER.format(
        project_name=project_name or "(no project)",
        exchanges="\n---\n".join(exchanges),
    )
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=512,
        system=PREFERENCES_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    data = json.loads(_strip_fencing(response.content[0].text))
    return data.get("preferences", [])


# ── Public API ────────────────────────────────────────────────────────────────

def classify_session(
    conn: sqlite3.Connection,
    session_id: str,
    project_name: str | None,
    use_llm: bool = True,
) -> ClassifyResult:
    result = ClassifyResult()
    requests = get_session_requests(conn, session_id)
    if not requests:
        return result

    client = _get_anthropic_client() if use_llm else None
    result.used_llm = client is not None

    if client:
        # Batch classify
        for i in range(0, len(requests), CLASSIFIER_BATCH_SIZE):
            batch = requests[i : i + CLASSIFIER_BATCH_SIZE]
            try:
                classifications = _llm_classify_batch(client, batch)
                for c in classifications:
                    update_request_classification(conn, c["id"], c["obs_type"], c["title"])
                    result.requests_classified += 1
            except Exception:
                for r in batch:
                    update_request_classification(conn, r["request_id"], _rule_classify(r["user_message"]), _rule_title(r["user_message"]))
                    result.requests_classified += 1
                result.errors += 1

        # Summarize
        try:
            summary = _llm_summarize(client, requests, project_name or "")
            update_session_summary(conn, session_id, summary)
        except Exception:
            update_session_summary(conn, session_id, "")
            result.errors += 1

        # Extract preferences
        try:
            prefs = _llm_extract_preferences(client, requests, project_name or "")
            if prefs:
                pref_records = [
                    {"project_name": project_name, "content": p, "source_request_id": requests[0]["request_id"]}
                    for p in prefs
                ]
                insert_preferences(conn, pref_records)
                result.preferences_extracted += len(prefs)
        except Exception:
            result.errors += 1
    else:
        # Rule-based fallback
        for r in requests:
            update_request_classification(conn, r["request_id"], _rule_classify(r["user_message"]), _rule_title(r["user_message"]))
            result.requests_classified += 1
        update_session_summary(conn, session_id, "")

    conn.commit()
    result.sessions_processed = 1
    return result


def classify_all_unclassified(conn: sqlite3.Connection, use_llm: bool = True) -> ClassifyResult:
    total = ClassifyResult()
    client = _get_anthropic_client() if use_llm else None
    total.used_llm = client is not None

    sessions = get_unclassified_sessions(conn)
    for sess in sessions:
        r = classify_session(conn, sess["session_id"], sess.get("project_name"), use_llm=use_llm)
        total.sessions_processed += r.sessions_processed
        total.requests_classified += r.requests_classified
        total.preferences_extracted += r.preferences_extracted
        total.errors += r.errors

    return total
