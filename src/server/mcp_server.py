"""MCP server exposing copilot-mem search tools via stdio transport."""
import sys
import json
import asyncio
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from config import DB_PATH
from src.indexer.db import init_db
from src.search.search import (
    get_requests,
    list_projects,
    recent,
    search,
    timeline,
)

app = Server("copilot-mem")
_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        _conn = init_db(str(DB_PATH))
    return _conn


def _to_text(data) -> str:
    return json.dumps(data, indent=2, default=str)


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="copilot_mem_search",
            description=(
                "Search past GitHub Copilot chat sessions for relevant context, "
                "decisions, and code snippets. Supports FTS5 query syntax."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "project": {"type": "string", "description": "Filter by project name (optional)"},
                    "obs_type": {"type": "string", "description": "Filter by type: bugfix, feature, refactor, discovery, decision, change, other"},
                    "limit": {"type": "integer", "description": "Max results (default 20)", "default": 20},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="copilot_mem_timeline",
            description="Get surrounding context for a specific Copilot chat interaction.",
            inputSchema={
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Request ID from search results"},
                    "before": {"type": "integer", "default": 5},
                    "after": {"type": "integer", "default": 5},
                },
                "required": ["request_id"],
            },
        ),
        types.Tool(
            name="copilot_mem_get_requests",
            description=(
                "Get full details of specific Copilot chat interactions, "
                "including code blocks, file references, and tool calls."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "request_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of request IDs to fetch",
                    },
                },
                "required": ["request_ids"],
            },
        ),
        types.Tool(
            name="copilot_mem_recent",
            description="Get the most recent Copilot chat interactions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Filter by project name (optional)"},
                    "limit": {"type": "integer", "default": 10},
                },
            },
        ),
        types.Tool(
            name="copilot_mem_projects",
            description="List all indexed projects with session and request counts.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="copilot_mem_preferences",
            description="Get extracted user preferences and decisions from past Copilot sessions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {"type": "string", "description": "Filter by project name (optional)"},
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    conn = _get_conn()

    if name == "copilot_mem_search":
        results = search(
            conn,
            query=arguments["query"],
            project=arguments.get("project"),
            obs_type=arguments.get("obs_type"),
            limit=arguments.get("limit", 20),
        )
        data = [
            {
                "request_id": r.request_id,
                "session_id": r.session_id,
                "project": r.project_name,
                "obs_type": r.obs_type,
                "title": r.title,
                "question": r.user_message,
                "snippet": r.snippet,
                "timestamp": r.timestamp,
            }
            for r in results
        ]
        return [types.TextContent(type="text", text=_to_text(data))]

    elif name == "copilot_mem_timeline":
        entries = timeline(
            conn,
            anchor_request_id=arguments["request_id"],
            before=arguments.get("before", 5),
            after=arguments.get("after", 5),
        )
        data = [
            {
                "request_id": e.request_id,
                "seq_num": e.seq_num,
                "is_anchor": e.is_anchor,
                "user_message": e.user_message,
                "assistant_response": e.assistant_response,
            }
            for e in entries
        ]
        return [types.TextContent(type="text", text=_to_text(data))]

    elif name == "copilot_mem_get_requests":
        reqs = get_requests(conn, request_ids=arguments["request_ids"])
        data = [
            {
                "request_id": r.request_id,
                "session_id": r.session_id,
                "project": r.project_name,
                "user_message": r.user_message,
                "assistant_response": r.assistant_response,
                "thinking_text": r.thinking_text,
                "agent_id": r.agent_id,
                "model_id": r.model_id,
                "file_references": r.file_references,
                "code_blocks": r.code_blocks,
                "tool_calls": r.tool_calls,
            }
            for r in reqs
        ]
        return [types.TextContent(type="text", text=_to_text(data))]

    elif name == "copilot_mem_recent":
        results = recent(
            conn,
            project=arguments.get("project"),
            limit=arguments.get("limit", 10),
        )
        data = [
            {
                "request_id": r.request_id,
                "project": r.project_name,
                "question": r.user_message,
                "timestamp": r.timestamp,
            }
            for r in results
        ]
        return [types.TextContent(type="text", text=_to_text(data))]

    elif name == "copilot_mem_projects":
        projects = list_projects(conn)
        data = [
            {
                "project": p.project_name,
                "sessions": p.session_count,
                "requests": p.request_count,
            }
            for p in projects
        ]
        return [types.TextContent(type="text", text=_to_text(data))]

    elif name == "copilot_mem_preferences":
        from src.search.search import get_preferences
        prefs = get_preferences(conn, project=arguments.get("project"))
        data = [
            {"project": p.project_name, "content": p.content, "extracted_at": p.extracted_at}
            for p in prefs
        ]
        return [types.TextContent(type="text", text=_to_text(data))]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
