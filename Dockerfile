FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/src ./src
RUN uv sync --frozen --no-dev

COPY fixtures /app/fixtures
RUN mkdir -p /app/backend/artifacts

ENTRYPOINT ["/app/backend/.venv/bin/profitlens"]
CMD ["chat"]
