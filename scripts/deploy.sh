#!/usr/bin/env bash
#
# scripts/deploy.sh — pull the latest code onto THE SERVER and restart into it.
#
# WHY THIS EXISTS: nothing reaches the server automatically. The weekly cron
# (scripts/weekly_refresh.sh) runs the PIPELINE; it never runs `git pull`. So code pushed to
# GitHub sits there until a human deploys it.
#
# AND WHY IT IS A SCRIPT RATHER THAN A REMEMBERED COMMAND: `git pull` alone changes nothing
# that is running. The image bakes the source in at build time, so without `--build` the
# containers keep serving the OLD code while `git log` on the server shows the new commit --
# a silent, convincing mismatch. (The same class of trap cost an hour on 2026-09-11, when a
# changed module sat on disk while the running process held the previous version in
# sys.modules.) This script always rebuilds.
#
# Run ON THE SERVER:  /opt/lofc/scripts/deploy.sh
#
# Exit codes: 0 deployed (or already current), 1 something failed -- read the output.

set -euo pipefail

REPO_ROOT="${LOFC_REPO_ROOT:-/opt/lofc}"
COMPOSE_FILE="${LOFC_COMPOSE_FILE:-$REPO_ROOT/docker-compose.prod.yml}"
cd "$REPO_ROOT"

say() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

before=$(git rev-parse --short HEAD)
say "current: $before"

say "pulling..."
git pull --ff-only

after=$(git rev-parse --short HEAD)
if [ "$before" = "$after" ]; then
    say "already up to date at $after — rebuilding anyway, in case a previous deploy stopped short"
else
    say "updated: $before -> $after"
    git --no-pager log --oneline "$before..$after"
fi

# ALWAYS rebuild, even when the commit did not move: a half-finished earlier deploy is
# exactly the state this script exists to recover from, and a no-op rebuild is cheap.
say "rebuilding and restarting..."
docker compose -f "$COMPOSE_FILE" up -d --build

# Migrations are idempotent and the pipeline applies them too, but running them here means a
# schema change is live the moment the code that needs it is -- not at 04:15 on Monday.
say "applying migrations..."
docker compose -f "$COMPOSE_FILE" exec -T app alembic upgrade head

say "container status:"
docker compose -f "$COMPOSE_FILE" ps

say "deployed at $after"
