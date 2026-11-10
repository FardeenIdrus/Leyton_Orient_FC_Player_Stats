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

# A running bash script keeps reading the file it started with, even after `git pull` replaces
# it -- so a pull that changed THIS script would otherwise finish with the old steps (2026-11-10:
# that started Caddy without its upstream file and took every domain down). Re-run the new
# version once; the guard stops a loop.
if [ -z "${LOFC_DEPLOY_REEXEC:-}" ] && ! git diff --quiet "$before" "$after" -- scripts/deploy.sh; then
    say "deploy.sh itself changed -- restarting with the new version"
    LOFC_DEPLOY_REEXEC=1 exec "$REPO_ROOT/scripts/deploy.sh" "$@"
fi

# ALWAYS rebuild, even when the commit did not move: a half-finished earlier deploy is
# exactly the state this script exists to recover from, and a no-op rebuild is cheap.
# Build FIRST, restart second: the web containers are switched separately below, so a plain
# `up -d --build` (which would recreate the serving web container cold) is never used.
say "building images..."
docker compose -f "$COMPOSE_FILE" build

# Caddy imports caddy/web_upstream.caddy; before the first switch it names the Streamlit
# dashboard (web_switch.sh writes it from then on).
mkdir -p caddy
[ -f caddy/web_upstream.caddy ] || echo "reverse_proxy dashboard:8501" > caddy/web_upstream.caddy

say "restarting the database, pipeline helper, Streamlit dashboard and Caddy..."
docker compose -f "$COMPOSE_FILE" up -d db app dashboard caddy

# Migrations are idempotent and the pipeline applies them too, but running them here means a
# schema change is live the moment the code that needs it is -- not at 04:15 on Monday.
say "applying migrations..."
docker compose -f "$COMPOSE_FILE" exec -T app alembic upgrade head

# The new web front end: start the idle colour from the new image, switch Caddy to it once its
# warm-up is done, then stop the old one (scripts/web_switch.sh). If it fails, the old web
# container keeps serving and the deploy reports failure.
say "switching the web front end (waits for the new container's warm-up)..."
LOFC_REPO_ROOT="$REPO_ROOT" LOFC_COMPOSE_FILE="$COMPOSE_FILE" "$REPO_ROOT/scripts/web_switch.sh"

say "container status:"
docker compose -f "$COMPOSE_FILE" ps

say "deployed at $after"
