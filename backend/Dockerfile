# AIOS backend image — one image, four roles (api / worker / beat / migrate),
# selected by the container `command`. Build from the REPO ROOT so the migrate
# role can bake db/migrations/ (which live outside backend/):
#     docker build -f backend/Dockerfile -t aios-backend .
#
# ---- builder: install the app + deps into an isolated venv ------------------
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# build-essential only in the builder (some sdists need a compiler); the runtime
# image stays slim and never carries a toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /src
# hatchling packages = ["app","workers","integrations"] (pyproject), so a plain
# `pip install .` builds a real wheel with all three. Copy exactly what the wheel
# build reads.
COPY backend/pyproject.toml backend/README.md ./
COPY backend/app ./app
COPY backend/workers ./workers
COPY backend/integrations ./integrations
# `.[ai]` bakes the Context/Content/ai-assist provider SDKs (anthropic, voyageai,
# pinecone) so a supplied ANTHROPIC_API_KEY actually activates — without the extra
# the seams lazy-import-fail and silently degrade to fakes. Override with
# --build-arg PKG_SPEC="." for a lean, provider-less image.
# DO NOT rename this back to PIP_TARGET: pip reads any PIP_<OPTION> env var as that
# option, and Docker exposes an ARG into the RUN environment — so an ARG named
# PIP_TARGET becomes `pip --target=.[ai]`, installing the whole app into a stray
# ./.[ai]/ dir instead of the venv (site-packages ends up empty → runtime "No module
# named 'app'"). Any name NOT starting with PIP_ is safe.
ARG PKG_SPEC=".[ai]"
# Install, then PROVE the three first-party packages are importable from the venv.
# If a build ever ships without them, this fails the build LOUDLY here instead of
# producing an image that dies at runtime with "No module named 'app'". find_spec
# checks importability without executing module code (no env needed at build time).
# NOTE: `python -P` is REQUIRED — without it cwd (/src, which holds ./app on disk) is
# on sys.path, so find_spec('app') passes even when the wheel didn't install the
# package into the venv (a false pass that shipped a runtime-broken image). -P drops
# cwd from sys.path so this checks the VENV install, not the source tree. Changing this
# RUN also busts any stale layer cache that reused a broken venv.
RUN pip install --upgrade pip && pip install "${PKG_SPEC}" \
    && python -P -c "import importlib.util as u, sys; miss=[m for m in ('app','app.db.rls_check','workers','integrations') if u.find_spec(m) is None]; sys.exit('BUILD ABORT — backend packages missing from the venv: '+', '.join(miss)) if miss else print('backend package import-check OK')"

# ---- runtime ----------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH"
# postgresql-client -> psql for the migrate entrypoint; curl -> the API healthcheck.
# (psycopg[binary] bundles its own libpq, so no libpq-dev needed at runtime.)
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
# Migrations + the bootstrap entrypoint the `migrate` one-shot service runs. The
# app code itself lives in the venv (installed above), not here.
COPY db/migrations /app/db/migrations
COPY infra/docker/migrate-entrypoint.sh /app/migrate-entrypoint.sh
RUN chmod +x /app/migrate-entrypoint.sh

# Non-root + a writable state dir (celery beat schedule + any artifact dirs).
RUN useradd --system --create-home --home-dir /home/aios aios \
    && mkdir -p /var/lib/aios \
    && chown -R aios:aios /var/lib/aios /app
USER aios

EXPOSE 8000
# Default role = the API. worker / beat / migrate override `command` in compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
