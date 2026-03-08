@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================
echo   copilot-mem  ^|  Quick Setup
echo ============================================
echo.

REM ── 1. Check / install uv ────────────────────────────────────────────────
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo [1/5] Installing uv...
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if %errorlevel% neq 0 (
        echo ERROR: uv install failed. Install manually: https://docs.astral.sh/uv/
        exit /b 1
    )
    REM Refresh PATH so uv is available in this session
    set "PATH=%USERPROFILE%\.cargo\bin;%USERPROFILE%\.local\bin;%PATH%"
) else (
    echo [1/5] uv already installed. OK
)

REM ── 2. Create venv + install deps ────────────────────────────────────────
echo [2/5] Installing dependencies with uv sync...
uv sync
if %errorlevel% neq 0 (
    echo ERROR: uv sync failed.
    exit /b 1
)

REM ── 3. Copy MCP config if not present ────────────────────────────────────
echo [3/5] Setting up MCP config...
if not exist .mcp.json (
    copy .mcp.json.example .mcp.json >nul
    echo       Copied .mcp.json.example ^-^> .mcp.json
    echo       Edit .mcp.json if 'python' is not on your PATH.
) else (
    echo       .mcp.json already exists. Skipped.
)

REM ── 4. Run initial index ──────────────────────────────────────────────────
echo [4/5] Indexing Copilot sessions...
uv run copilot-mem index
if %errorlevel% neq 0 (
    echo WARNING: Indexing failed. Run manually: uv run copilot-mem index
)

REM ── 5. Run classification (uses LLM if ANTHROPIC_API_KEY is set) ──────────
echo [5/5] Classifying sessions...
if defined ANTHROPIC_API_KEY (
    echo       ANTHROPIC_API_KEY found. Using LLM classification.
) else (
    echo       ANTHROPIC_API_KEY not set. Using rule-based fallback.
    echo       Set it later and run: uv run copilot-mem classify --force
)
uv run copilot-mem classify

echo.
echo ============================================
echo   Setup complete!
echo ============================================
echo.
echo   Commands:
echo     uv run copilot-mem index              -- re-index sessions
echo     uv run copilot-mem search "query"     -- search
echo     uv run copilot-mem classify           -- LLM classify
echo     uv run copilot-mem context --inject   -- update copilot-instructions.md
echo     uv run copilot-mem preferences        -- show extracted preferences
echo     uv run copilot-mem --help             -- all commands
echo.
echo   MCP server for VS Code Copilot:
echo     Ensure .mcp.json exists (copied from .mcp.json.example)
echo     Enable MCP in VS Code settings: github.copilot.advanced.mcp = true
echo.
echo   MCP server for Claude Code:
echo     claude mcp add copilot-mem -- python run_server.py
echo.

endlocal
