#!/usr/bin/env bash
# Prepare a fresh job worktree: install dependencies, copy env files.
#
# `job advance <job> spec` runs this once, with the new worktree as the working
# directory, before any agent starts. If it exits non-zero the worktree is
# removed and the job stays at intake. Keep it non-interactive.
#
# INSTALL.md replaces the line below with this project's real setup, e.g.:
#
#   npm ci --prefer-offline
#   cp "$FACTORY_MAIN/.env.example" .env
#
# Delete this file if a fresh checkout needs no setup.
set -euo pipefail

echo "factory/setup.sh has nothing to do yet." >&2
