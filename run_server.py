"""
Self-locating MCP server launcher.
Adds the repo root to sys.path regardless of cwd, then starts the server.
Use this as the entry point in .mcp.json so no absolute paths are needed.
"""
import sys
from pathlib import Path

# Ensure repo root is on path no matter where this script is invoked from
repo_root = Path(__file__).parent.resolve()
sys.path.insert(0, str(repo_root))

from src.server.mcp_server import main
import asyncio


def main_sync():
    """Synchronous entry point for the copilot-mem-server script."""
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
