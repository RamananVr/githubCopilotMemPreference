import os
from pathlib import Path

# ── VS Code storage paths ─────────────────────────────────────────────────────
# Override via env vars for Docker / cross-platform use:
#   VSCODE_WORKSPACE_SESSIONS   path to workspaceStorage/
#   VSCODE_EMPTY_WINDOW_SESSIONS  path to emptyWindowChatSessions/
#   COPILOT_MEM_DB_DIR          path to database directory

def _default_vscode_storage() -> Path:
    """Resolve the VS Code User storage dir for the current OS."""
    if override := os.environ.get("VSCODE_STORAGE_ROOT"):
        return Path(override)
    system = os.name  # 'nt' = Windows, 'posix' = Linux/macOS
    if system == "nt":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return appdata / "Code" / "User"
    elif (darwin := Path.home() / "Library" / "Application Support" / "Code" / "User").exists():
        return darwin  # macOS
    else:
        return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Code" / "User"


_VSCODE_STORAGE = _default_vscode_storage()

WORKSPACE_SESSIONS_ROOT = Path(
    os.environ.get("VSCODE_WORKSPACE_SESSIONS", _VSCODE_STORAGE / "workspaceStorage")
)
EMPTY_WINDOW_SESSIONS_ROOT = Path(
    os.environ.get("VSCODE_EMPTY_WINDOW_SESSIONS", _VSCODE_STORAGE / "globalStorage" / "emptyWindowChatSessions")
)

DB_DIR = Path(os.environ.get("COPILOT_MEM_DB_DIR", Path.home() / ".copilot-mem"))
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
COPILOT_INSTRUCTIONS_PATH = Path(
    os.environ.get("COPILOT_INSTRUCTIONS_PATH", Path.home() / ".github" / "copilot-instructions.md")
)
CONTEXT_MD_PATH = DB_DIR / "context.md"
CONTEXT_MARKER_START = "<!-- copilot-mem:start -->"
CONTEXT_MARKER_END = "<!-- copilot-mem:end -->"

# Valid observation types
OBS_TYPES = ("bugfix", "feature", "refactor", "discovery", "decision", "change", "other")
