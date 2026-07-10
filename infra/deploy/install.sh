#!/usr/bin/env bash
#
# Provision the AIOS backend on a fresh Debian/Ubuntu VPS: native Redis + a
# Python venv + two systemd units (API and Celery worker). Idempotent - safe to
# re-run after a `git pull` to pick up code and unit changes.
#
# Prerequisites: run as root, with the repo already cloned to $DEPLOY_ROOT
# (e.g. `git clone <repo> /opt/aios`). Fill in /opt/aios/backend/.env first
# (copy from .env.example) or the API will boot in dev-degraded mode.
#
# Usage:  sudo bash infra/deploy/install.sh
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/aios}"
BACKEND_DIR="${DEPLOY_ROOT}/backend"
VENV_DIR="${BACKEND_DIR}/.venv"
APP_USER="${APP_USER:-aios}"
UNIT_SRC="${BACKEND_DIR}/../infra/systemd"

log() { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; }

if [[ "${EUID}" -ne 0 ]]; then
    err "must run as root (use sudo)"
    exit 1
fi

if [[ ! -d "${BACKEND_DIR}" ]]; then
    err "expected the repo at ${DEPLOY_ROOT} (missing ${BACKEND_DIR})."
    err "clone it first:  git clone <repo> ${DEPLOY_ROOT}"
    exit 1
fi

log "installing system packages (redis-server, python venv)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq redis-server python3-venv python3-pip

log "enabling redis-server"
systemctl enable --now redis-server

if ! id "${APP_USER}" &>/dev/null; then
    log "creating system user '${APP_USER}'"
    useradd --system --home-dir "${DEPLOY_ROOT}" --shell /usr/sbin/nologin "${APP_USER}"
else
    log "system user '${APP_USER}' already exists"
fi

if [[ ! -d "${VENV_DIR}" ]]; then
    log "creating virtualenv at ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
fi

log "installing the backend (non-editable) into the venv"
"${VENV_DIR}/bin/pip" install --upgrade pip -q
# Install from the backend project directory (reads pyproject.toml + README.md).
(cd "${BACKEND_DIR}" && "${VENV_DIR}/bin/pip" install . -q)

if [[ ! -f "${BACKEND_DIR}/.env" ]]; then
    log "no .env found - seeding from .env.example (EDIT IT before real use)"
    cp "${BACKEND_DIR}/.env.example" "${BACKEND_DIR}/.env"
fi

log "setting ownership to ${APP_USER}"
chown -R "${APP_USER}:${APP_USER}" "${DEPLOY_ROOT}"

log "installing systemd units"
install -m 0644 "${UNIT_SRC}/aios-api.service" /etc/systemd/system/aios-api.service
install -m 0644 "${UNIT_SRC}/aios-worker.service" /etc/systemd/system/aios-worker.service

log "reloading systemd + enabling services"
systemctl daemon-reload
systemctl enable --now aios-api.service
systemctl enable --now aios-worker.service

log "done. check status with:"
log "  systemctl status aios-api aios-worker redis-server"
log "  journalctl -u aios-api -f"
log "  curl -sf http://127.0.0.1:8000/health && echo"
