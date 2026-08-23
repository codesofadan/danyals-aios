#!/usr/bin/env bash
# Give a Claude Code session (or a human) its own isolated checkout.
#
# WHY THIS EXISTS
# ---------------
# On 2026-08-23 three sessions worked this repository through ONE checkout. Two
# concrete failures came out of it, neither caused by anyone doing anything wrong:
#
#   1. `git checkout -b` moves the branch pointer for the WHOLE tree, so one session
#      branching silently relocated the other two.
#   2. A 24-minute `pytest` run against a tree being edited by another session
#      reported three failures that were TRUE OF NO COMMIT ANYONE MADE - it imported
#      test files that already expected a new behaviour while the matching source
#      change had not landed yet. A torn read. The board went red; nothing was broken.
#
# (2) is the one that matters: a shared checkout can manufacture failures out of
# nothing, and the time lost is spent chasing a regression that does not exist.
#
# A worktree is a second working directory backed by the SAME .git. Branches, commits
# and history are shared; the files on disk are not. Costs one command and some disk.
#
# USAGE
#   scripts/session-worktree.sh <branch> [path]
#
#   scripts/session-worktree.sh recovery/p0-5-restore-beat
#       -> ../danyals-aios--p0-5-restore-beat, new branch off the current HEAD
#
#   scripts/session-worktree.sh recovery/p0-3-job-contract
#       -> checks out the EXISTING branch there instead of creating it
#
# Then start the session with that directory as its working directory.
#
# NOTE ON PYTHON: the backend is installed editable, so a worktree needs its own venv
# or PYTHONPATH, otherwise imports can resolve back to the original checkout and you
# are testing the wrong files. This script prints the exact commands; it does not run
# them, because building a venv is slow and not always wanted.
set -euo pipefail

BRANCH="${1:-}"
if [[ -z "$BRANCH" ]]; then
  echo "usage: $(basename "$0") <branch> [path]" >&2
  exit 64
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
REPO_NAME="$(basename "$REPO_ROOT")"
SLUG="${BRANCH//\//-}"
TARGET="${2:-$(dirname "$REPO_ROOT")/${REPO_NAME}--${SLUG##*recovery-}}"

if [[ -e "$TARGET" ]]; then
  echo "refusing: $TARGET already exists" >&2
  exit 1
fi

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "branch '$BRANCH' exists -> checking it out at $TARGET"
  git worktree add "$TARGET" "$BRANCH"
else
  echo "branch '$BRANCH' is new -> creating it off $(git rev-parse --short HEAD) at $TARGET"
  git worktree add -b "$BRANCH" "$TARGET"
fi

cat <<MSG

Worktree ready: $TARGET
  branch: $BRANCH

Before running the backend suite there, give it its own environment - otherwise the
editable install can resolve imports back to $REPO_ROOT and you will be testing files
you are not looking at:

  cd "$TARGET/backend"
  python3 -m venv .venv && ./.venv/bin/python -m pip install -q -e ".[dev]"

Or, for a quick read-only check without building a venv:

  PYTHONPATH="$TARGET/backend" "$REPO_ROOT/backend/.venv/bin/python" -m pytest ...

When finished:
  git worktree remove "$TARGET"      # refuses if there are uncommitted changes
  git worktree list                  # what exists right now
MSG
