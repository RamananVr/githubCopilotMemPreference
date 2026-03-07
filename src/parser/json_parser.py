"""Parser for the older single-JSON Copilot chat session format (version 3)."""
import json
import os
from pathlib import Path

from .models import CodeBlock, CopilotRequest, CopilotSession, FileReference, ToolCall


def _extract_response(response_list: list) -> tuple[str, str]:
    """Return (assistant_response_text, thinking_text) from a response list."""
    response_parts = []
    thinking_parts = []

    for item in response_list:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        value = item.get("value", "")
        if not isinstance(value, str):
            continue
        if kind == "thinking":
            if value:
                thinking_parts.append(value)
        else:
            if value:
                response_parts.append(value)

    return "\n".join(response_parts), "\n".join(thinking_parts)


def _extract_file_references(variable_data: dict) -> list[FileReference]:
    refs = []
    if not variable_data:
        return refs
    for var in variable_data.get("variables", []):
        if not isinstance(var, dict):
            continue
        value = var.get("value", {})
        if not isinstance(value, dict):
            continue
        uri = value.get("uri", {})
        if not isinstance(uri, dict):
            continue
        fs_path = uri.get("fsPath", "")
        if fs_path:
            refs.append(FileReference(
                file_path=fs_path,
                description=var.get("modelDescription", var.get("name", "")),
            ))
    return refs


def _extract_code_blocks(metadata: dict) -> list[CodeBlock]:
    blocks = []
    if not metadata:
        return blocks
    for block in metadata.get("codeBlocks", []):
        if not isinstance(block, dict):
            continue
        code = block.get("code", "")
        if code:
            blocks.append(CodeBlock(
                code=code,
                language=block.get("language", ""),
                context_text=block.get("markdownBeforeBlock", ""),
            ))
    return blocks


def _extract_tool_calls(response_list: list) -> list[ToolCall]:
    calls = []
    for item in response_list:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "toolInvocationSerialized":
            invocation = item.get("invocation", {})
            if isinstance(invocation, dict):
                calls.append(ToolCall(
                    tool_id=invocation.get("id", ""),
                    tool_label=invocation.get("displayLabel", ""),
                    invocation_message=invocation.get("invocationMessage", ""),
                ))
    return calls


def parse_json_session(file_path: str) -> CopilotSession | None:
    """Parse a .json Copilot chat session file. Returns None on failure."""
    path = Path(file_path)
    try:
        mtime = path.stat().st_mtime
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, PermissionError):
        return None

    if not isinstance(data, dict):
        return None

    # Derive session_id from filename
    session_id = path.stem

    session = CopilotSession(
        session_id=session_id,
        source_file=str(path),
        file_mtime=mtime,
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
                # Fallback: concatenate parts
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

        agent = req.get("agent", {})
        agent_id = agent.get("id") if isinstance(agent, dict) else None

        session.requests.append(CopilotRequest(
            request_id=req.get("requestId", f"{session_id}_{seq_num}"),
            seq_num=seq_num,
            user_message=user_text,
            assistant_response=assistant_response,
            thinking_text=thinking_text,
            file_references=_extract_file_references(req.get("variableData", {})),
            code_blocks=_extract_code_blocks(metadata),
            tool_calls=_extract_tool_calls(response_list),
            agent_id=agent_id,
            model_id=metadata.get("modelId"),
            timing_first_progress=timings.get("firstProgress"),
            timing_total_elapsed=timings.get("totalElapsed"),
        ))

    return session
