# copilot-mem

Persistent, searchable memory for GitHub Copilot — inspired by [claude-mem](https://github.com/thedotmack/claude-mem).

Indexes all your VS Code Copilot chat history into a local SQLite database, classifies each interaction using Claude Haiku (bugfix / feature / refactor / discovery / decision / change), extracts your preferences, and injects context back into Copilot and Claude Code via MCP.

---

## Quick Start

```bat
git clone https://github.com/RamananVr/githubCopilotMemPreference.git
cd githubCopilotMemPreference
setup.bat
```

That's it. The setup script will:
1. Install [uv](https://docs.astral.sh/uv/) if missing
2. Create a virtual environment and install all dependencies
3. Copy `.mcp.json.example` → `.mcp.json`
4. Run an initial index of your Copilot sessions
5. Classify interactions (LLM if `ANTHROPIC_API_KEY` is set, rule-based otherwise)

---

## Requirements

| Requirement | Notes |
|-------------|-------|
| Python 3.10+ | Detected automatically by uv |
| VS Code + GitHub Copilot | Sessions stored in `%APPDATA%\Code\User\...` |
| `ANTHROPIC_API_KEY` | Optional — enables LLM classification |

---

## CLI Reference

```
uv run copilot-mem <command>
```

| Command | Description |
|---------|-------------|
| `index` | Scan and index all Copilot sessions (incremental) |
| `index --force` | Re-index everything |
| `index --classify` | Index + classify in one step |
| `classify` | LLM-classify unclassified sessions |
| `classify --force` | Re-classify all sessions |
| `search "query"` | Full-text search (FTS5) |
| `search "query" -p NovaCompute` | Search within a project |
| `search "query" --type decision` | Filter by type |
| `timeline <request-id>` | Show surrounding context |
| `context` | Preview the context block |
| `context --inject` | Write to `~/.github/copilot-instructions.md` |
| `preferences` | Show extracted preferences by project |
| `projects` | List all indexed projects |
| `recent` | Most recent interactions |
| `stats` | Database statistics |

**Observation types:** `bugfix` · `feature` · `refactor` · `discovery` · `decision` · `change` · `other`

---

## MCP Server

The MCP server exposes your Copilot history to any MCP-compatible AI client.

### VS Code Copilot

1. Copy the example config (done by `setup.bat`):
   ```bat
   copy .mcp.json.example .mcp.json
   ```
2. Enable MCP in VS Code settings:
   ```json
   "github.copilot.advanced": { "mcp": true }
   ```
3. Restart VS Code. Ask Copilot: *"Search my past sessions for how I handled authentication"*

### Claude Code

```bash
claude mcp add copilot-mem -- python run_server.py
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `copilot_mem_search(query, project?, obs_type?, limit?)` | FTS5 search |
| `copilot_mem_timeline(request_id, before?, after?)` | Surrounding context |
| `copilot_mem_get_requests(request_ids[])` | Full detail with code blocks |
| `copilot_mem_recent(project?, limit?)` | Most recent interactions |
| `copilot_mem_projects()` | List all projects |
| `copilot_mem_preferences(project?)` | Extracted preferences |

---

## Auto-Indexing

### File watcher (real-time)

```bat
uv run python src/watcher/watcher.py
```

### Windows Task Scheduler (recommended)

Schedule `uv run copilot-mem index --classify` to run hourly — lower overhead than a persistent watcher.

---

## LLM Classification

Set your Anthropic API key, then run:

```bat
set ANTHROPIC_API_KEY=sk-ant-...
uv run copilot-mem classify --force
uv run copilot-mem context --inject
```

Uses `claude-haiku-4-5-20251001` — approximately **$0.01** to classify a full backlog of sessions.

---

## Data Sources

| Location | Contents |
|----------|----------|
| `%APPDATA%\Code\User\workspaceStorage\*\chatSessions\*.json/.jsonl` | Workspace-bound sessions |
| `%APPDATA%\Code\User\globalStorage\emptyWindowChatSessions\*.json/.jsonl` | Empty-window sessions |

Database stored at: `~/.copilot-mem/copilot-mem.db`

---

## Project Structure

```
copilot-mem/
├── src/
│   ├── parser/         # JSON + JSONL session parsers
│   ├── indexer/        # SQLite schema + incremental indexer
│   ├── search/         # 3-layer search API
│   ├── llm/            # Claude Haiku classifier + prompts
│   ├── context/        # Context block generator + injector
│   ├── server/         # MCP server (stdio)
│   ├── watcher/        # File system watcher
│   └── cli.py          # CLI entry point
├── run_server.py       # MCP server launcher (self-locating)
├── config.py           # Paths and constants
├── pyproject.toml      # Dependencies (uv)
├── setup.bat           # One-command Windows setup
└── .mcp.json.example   # Portable MCP config template
```
