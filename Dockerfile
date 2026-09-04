# syntax=docker/dockerfile:1
#
# Backend-only image: the WebSocket voice server + loopback control plane
# (demos/voice_web_server.py). The Next.js frontend is a separate deployable
# (see package.json) and is not built by this Dockerfile.
#
# Build:  docker build -t openrealtime-server .
# Run:    docker run -p 8765:8765 --env-file .env openrealtime-server
#
# GPU avatar rendering (LiveTalking) is a separate, optional local process
# (scripts/avatar_services.sh) and is out of scope for this image — leave
# OPENREALTIME_AVATAR_RENDERER_MODE=disabled (the default) unless you provide
# your own avatar-rendering deployment.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Install dependencies first, in their own layer, so code-only changes don't
# invalidate the dependency cache.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra postgres --extra object-store

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra postgres --extra object-store

ENV PATH="/app/.venv/bin:${PATH}" \
    VOICEAGENT_WS_HOST=0.0.0.0 \
    VOICEAGENT_WS_PORT=8765 \
    OPENREALTIME_AVATAR_RENDERER_MODE=disabled

EXPOSE 8765

CMD ["python", "demos/voice_web_server.py", "start"]
