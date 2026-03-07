"""Parser for the newer incremental-patch JSONL Copilot chat session format."""
import json
from pathlib import Path

from .json_parser import (
    _extract_code_blocks,
    _extract_file_references,
    _extract_response,
    _extract_tool_calls,
)
from .models import CopilotRequest, CopilotSession


def _apply_patch(obj: dict | list, key_path: list, value) -> None:
    """Apply an in-place patch to obj at the given key_path."""
    if not key_path:
        return

    current = obj
    for key in key_path[:-1]:
        if isinstance(current, list) and isinstance(key, int):
            # Extend list if needed
            while len(current) <= key:
                current.append({})
            current = current[key]
        elif isinstance(current, dict):
            if key not in current:
                current[key] = {}
            current = current[key]
        else:
            return  # Can't navigate further

    last_key = key_path[-1]
    if isinstance(current, list) and isinstance(last_key, int):
        while len(current) <= last_key:
            current.append(None)
        current[last_key] = value
    elif isinstance(current, dict):
        current[last_key] = value


def _reconstruct_session(file_path: Path) -> dict | None:
    """Read a .jsonl file and apply all patches to reconstruct the full session object."""
    session_obj = None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    patch = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not isinstance(patch, dict):
                    continue

                kind = patch.get("kind")

                if kind == 0:
                    # Base session object
                    session_obj = patch
                elif kind in (1, 2) and session_obj is not None:
                    key_path = patch.get("k", [])
                    value = patch.get("v")
                    if isinstance(key_path, list) and key_path:
                        _apply_patch(session_obj, key_path, value)

    except (OSError, PermissionError):
        return None

    return session_obj


def parse_jsonl_session(file_path: str) -> CopilotSession | None:
    """Parse a .jsonl Copilot chat session file. Returns None on failure."""
    path = Path(file_path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None

    data = _reconstruct_session(path)
    if not isinstance(data, dict):
        return None

    session_id = data.get("sessionId", path.stem)

    # Parse creation date
    creation_date = None
    raw_date = data.get("creationDate")
    if isinstance(raw_date, (int, float)):
        creation_date = int(raw_date)
    elif isinstance(raw_date, str):
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            creation_date = int(dt.timestamp() * 1000)
        except ValueError:
            pass

    session = CopilotSession(
        session_id=session_id,
        source_file=str(path),
        file_mtime=mtime,
        creation_date=creation_date,
        custom_title=data.get("customTitle"),
        model_id=data.get("modelId"),
        initial_location=data.get("initialLocation", "panel"),
    )

    raw_requests = data.get("requests", [])
    if not isinstance(raw_requests, list):
        return session

    for seq_num, req in enumerate(raw_requests):
        if not isinstance(req, dict):
            continue

        message = req.get("message", {})
        user_text = ""
        if isinstance(message, dict):
            user_text = message.get("text", "")
            if not user_text:
                for part in message.get("parts", []):
                    if isinstance(part, dict):
                        user_text += part.get("text", "")

        if not user_text:
            continue

        response_list = req.get("response", [])
        if not isinstance(response_list, list):
            response_list = []

        assistant_response, thinking_text = _extract_response(response_list)

        metadata = {}
        result = req.get("result", {})
        if isinstance(result, dict):
            metadata = result.get("metadata", {}) or {}

        timings = result.get("timings", {}) if isinstance(result, dict) else {}
        if not isinstance(timings, dict):
            timings = {}

        # Timestamp from JSONL format (epoch ms)
        timestamp = req.get("timestamp")
        if not isinstance(timestamp, int):
            timestamp = None

        agent = req.get("agent", {})
        agent_id = agent.get("id") if isinstance(agent, dict) else None

        model_id = req.get("modelId") or metadata.get("modelId") or session.model_id

        session.requests.append(CopilotRequest(
            request_id=req.get("requestId", f"{session_id}_{seq_num}"),
            seq_num=seq_num,
            user_message=user_text,
            assistant_response=assistant_response,
            thinking_text=thinking_text,
            timestamp=timestamp,
            file_references=_extract_file_references(req.get("variableData", {})),
            code_blocks=_extract_code_blocks(metadata),
            tool_calls=_extract_tool_calls(response_list),
            agent_id=agent_id,
            model_id=model_id,
            timing_first_progress=timings.get("firstProgress"),
            timing_total_elapsed=timings.get("totalElapsed"),
        ))

    return session
