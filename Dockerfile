# syntax=docker/dockerfile:1
# ── copilot-mem ───────────────────────────────────────────────────────────────
# Multi-stage build: installs deps in builder, copies only what's needed to
# the slim runtime image.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install deps into /app/.venv (no editable install yet — source not copied)
RUN uv sync --frozen --no-install-project --no-dev

# Copy source and install the project itself
COPY . .
RUN uv sync --frozen --no-dev


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

WORKDIR /app

# Non-root user for security
RUN groupadd -r copilot && useradd -r -g copilot copilot

# Copy installed venv and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src    /app/src
COPY --from=builder /app/config.py     /app/config.py
COPY --from=builder /app/run_server.py /app/run_server.py

# Make venv the active Python
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

# ── Volume mount points (documented; mount from host at runtime) ──────────────
# /vscode-data   → host VS Code User storage dir (read-only)
# /data          → persistent DB directory
VOLUME ["/vscode-data", "/data"]

# ── Environment defaults (override at runtime) ────────────────────────────────
ENV VSCODE_WORKSPACE_SESSIONS=/vscode-data/workspaceStorage
ENV VSCODE_EMPTY_WINDOW_SESSIONS=/vscode-data/globalStorage/emptyWindowChatSessions
ENV COPILOT_MEM_DB_DIR=/data
ENV COPILOT_INSTRUCTIONS_PATH=/data/copilot-instructions.md

# Ownership
RUN chown -R copilot:copilot /app
USER copilot

# Default: run the CLI via installed entry point
ENTRYPOINT ["copilot-mem"]
CMD ["--help"]
