# syntax=docker/dockerfile:1
# One image for the API (default), the ingest worker, migrations and the schedule loader:
#   python -m transitpulse.ingest | python -m transitpulse.migrate | python -m transitpulse.load_static

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY transitpulse ./transitpulse
COPY migrations ./migrations

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER nobody
EXPOSE 8000
CMD ["uvicorn", "transitpulse.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
