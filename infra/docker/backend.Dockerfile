# Multi-stage build for the AIOS backend (API + Celery worker share this image).
# Build context is backend/ (see docker-compose.dev.yml).

# --- builder: install into a self-contained venv --------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# README.md is required: pyproject `readme = "README.md"` is read during the build.
# All three packages (app, workers, integrations) must be present because the
# hatch wheel target declares packages = ["app", "workers", "integrations"].
COPY pyproject.toml README.md ./
COPY app ./app
COPY workers ./workers
COPY integrations ./integrations

# Non-editable install into an isolated venv we copy forward to the final image.
RUN python -m venv /venv \
    && /venv/bin/pip install --upgrade pip \
    && /venv/bin/pip install .

# --- final: slim runtime, non-root ----------------------------------------------
FROM python:3.11-slim AS final

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/venv \
    PATH="/venv/bin:$PATH"

# Run as an unprivileged user, never root.
RUN useradd --create-home --uid 1000 app

COPY --from=builder /venv /venv

WORKDIR /app
COPY --chown=app:app app ./app
COPY --chown=app:app workers ./workers
COPY --chown=app:app integrations ./integrations

USER app
EXPOSE 8000

# slim has no curl; probe liveness with the stdlib instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
