import os
from pathlib import Path

APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
VSCODE_STORAGE = APPDATA / "Code" / "User"

WORKSPACE_SESSIONS_ROOT = VSCODE_STORAGE / "workspaceStorage"
EMPTY_WINDOW_SESSIONS_ROOT = VSCODE_STORAGE / "globalStorage" / "emptyWindowChatSessions"

DB_DIR = Path.home() / ".copilot-mem"
DB_PATH = DB_DIR / "copilot-mem.db"

# Truncate long responses to avoid bloating the FTS index
MAX_RESPONSE_CHARS = 50_000

# Debounce delay for file watcher (seconds)
WATCHER_DEBOUNCE_SECONDS = 5

# LLM classification
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
CLASSIFIER_BATCH_SIZE = 10  # requests per API call
CLASSIFIER_MAX_MSG_CHARS = 2000  # truncate user_message for classification prompt

# Context injection targets
COPILOT_INSTRUCTIONS_PATH = Path.home() / ".github" / "copilot-instructions.md"
CONTEXT_MD_PATH = DB_DIR / "context.md"
CONTEXT_MARKER_START = "<!-- copilot-mem:start -->"
CONTEXT_MARKER_END = "<!-- copilot-mem:end -->"

# Valid observation types
OBS_TYPES = ("bugfix", "feature", "refactor", "discovery", "decision", "change", "other")
