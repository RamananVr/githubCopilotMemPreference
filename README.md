# copilot-mem

Searchable index of your GitHub Copilot chat sessions — inspired by [claude-mem](https://github.com/thedotmack/claude-mem).

Indexes all VS Code Copilot chat history into a local SQLite database with FTS5 full-text search, and exposes it as an MCP server usable from both Copilot and Claude Code.

## Quick Start

```bash
pip install -r requirements.txt
python src/cli.py index
python src/cli.py stats
python src/cli.py search "your query"
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `python src/cli.py index` | Scan and index all sessions (incremental) |
| `python src/cli.py index --force` | Re-index everything |
| `python src/cli.py search "query"` | Full-text search |
| `python src/cli.py search "query" -p NovaCompute` | Search within a project |
| `python src/cli.py timeline <request-id>` | Show surrounding context |
| `python src/cli.py projects` | List all indexed projects |
| `python src/cli.py recent` | Most recent interactions |
| `python src/cli.py stats` | DB statistics |

## Auto-indexing (File Watcher)

```bash
python src/watcher/watcher.py
```

Or schedule `python src/cli.py index` via Windows Task Scheduler for simpler operation.

## MCP Server

### Claude Code
Already registered via `claude mcp add`. Available in Claude Code sessions.

### VS Code Copilot
1. Copy `.mcp.json` to your workspace root (or `~/.config/Code/User/` for global)
2. In VS Code, enable MCP servers in settings: `"github.copilot.advanced": { "mcp": true }`
3. Restart VS Code
4. In Copilot Chat, ask: *"Search my past Copilot sessions for [topic]"*

### Available MCP Tools
- `copilot_mem_search(query, project?, limit?)` — FTS5 search
- `copilot_mem_timeline(request_id, before?, after?)` — surrounding context
- `copilot_mem_get_requests(request_ids[])` — full details with code blocks
- `copilot_mem_recent(project?, limit?)` — most recent interactions
- `copilot_mem_projects()` — list all projects

## Data Sources

| Location | Description |
|----------|-------------|
| `%APPDATA%\Code\User\workspaceStorage\*\chatSessions\*.json/.jsonl` | Workspace-bound sessions |
| `%APPDATA%\Code\User\globalStorage\emptyWindowChatSessions\*.json/.jsonl` | Empty-window sessions |

## Storage

Database: `~/.copilot-mem/copilot-mem.db`
