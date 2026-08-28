#!/usr/bin/env bash
#
# scripts/weekly_refresh.sh — unattended weekly data refresh wrapper.
#
# WHY WEEKLY, NOT PER-MATCH: Impect returns season-to-date aggregates, not per-match
# deltas, so pulling after every fixture would just re-download the same cumulative
# totals several times a week for no new signal. One Monday-morning run picks up
# everything from the weekend AND any midweek round in a single pull. See the "WEEKLY
# IN-SEASON REFRESH" section of cli_commands.txt for the manual version of this same
# refresh.
#
# WHAT THIS WRAPS: `python -m lofc.pipeline`, completely unmodified, run inside the
# `app` service of the production compose stack. That command already: applies
# migrations, re-pulls the live season from Impect/SkillCorner (finished seasons and
# not-yet-started leagues are skipped, not an error), rebuilds the combined neutral
# metric table, re-scrapes EFL market values and re-loads injury history, and rebuilds
# the club composite + shortlists. Every stage is idempotent, and pipeline.py's own
# main() already stops the WHOLE run at the first stage that fails.
#
# This wrapper deliberately never adds --force / --allow-degraded / --allow-shrink to
# any stage. Those flags exist so that a human who has checked a scrape can knowingly
# overwrite what looks like a bad pull (see ingest/transfermarkt_efl.py's fill-rate
# guard and store/injuries.py's shrink guard — both exist because a bad scrape once
# destroyed 1,381 contract dates). An unattended cron job is exactly the situation
# those guards are designed to stop: if a stage judges its pull too degraded to
# publish, the correct unattended outcome is a FAILED, loudly-reported refresh that
# leaves the previous good data in place — never a silent, forced overwrite.
#
# WHAT THIS WRAPPER ADDS on top of a bare cron line calling the pipeline:
#   1. Refuses to start a second run while one is still in progress (a directory-based
#      lock — atomic on any POSIX filesystem, no extra binary required).
#   2. Logs every run, every line timestamped (UTC), to its own dated file, and prunes
#      old logs so they cannot fill the disk.
#   3. On failure: exits non-zero, writes a clearly-marked FAILURE banner into the log,
#      and drops a marker file (data/ops/last_failure) a human or a monitoring check
#      can `test -f` for.
#   4. On success: exits 0 and stamps data/ops/last_success with a UTC timestamp, so
#      staleness is detectable at a glance even without reading a single log line.
#
# EXIT CODES:
#   0  success
#   1  the pipeline itself failed — see the log and data/ops/last_failure
#   2  skipped — a previous run's lock is still held. NOT a pipeline failure; it means
#      last week's run had not finished when this one was triggered. last_success and
#      last_failure are left exactly as they were.
#
# CONFIGURATION (env vars, all optional):
#   LOFC_COMPOSE_FILE   compose file to use          (default: docker-compose.prod.yml)
#   LOFC_STATE_DIR      where lock/logs/markers live  (default: <repo>/data/ops)
#   LOFC_LOG_KEEP       how many past run logs to keep (default: 12, ~3 months weekly)
#   LOFC_REFRESH_CMD    override the command that IS "the refresh" — for tests only.
#                       Never set this in the real cron job; it exists so the wrapper's
#                       locking/logging/failure-handling can be exercised without
#                       touching Docker or the real pipeline.
#
# NOT enabled anywhere yet. This script is not installed in any crontab — see
# cli_commands.txt for the line to add once the platform is actually deployed.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${LOFC_COMPOSE_FILE:-$REPO_ROOT/docker-compose.prod.yml}"
STATE_DIR="${LOFC_STATE_DIR:-$REPO_ROOT/data/ops}"
LOG_DIR="$STATE_DIR/logs"
LOCK_DIR="$STATE_DIR/refresh.lock"
LAST_SUCCESS_FILE="$STATE_DIR/last_success"
LAST_FAILURE_FILE="$STATE_DIR/last_failure"
LOG_KEEP="${LOFC_LOG_KEEP:-12}"
RUN_STAMP="$(date -u +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/refresh-$RUN_STAMP.log"

mkdir -p "$LOG_DIR"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG_FILE"
}

# Runs "$@", timestamping every line of its combined stdout/stderr into the log file,
# and returns the command's own exit code (not the timestamping pipeline's).
run_logged() {
    "$@" 2>&1 | while IFS= read -r line; do
        printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$line"
    done >> "$LOG_FILE"
    return "${PIPESTATUS[0]}"
}

# ---- log rotation: keep only the LOG_KEEP most recent run logs, oldest first out -------
# Runs at exit (via the cleanup trap below), AFTER this run's own log file has been
# written, so "keep the LOG_KEEP most recent logs" includes the run that just happened
# rather than always leaving LOG_KEEP+1 on disk.
rotate_logs() {
    local n=0 f
    while IFS= read -r f; do
        n=$((n + 1))
        if [ "$n" -gt "$LOG_KEEP" ]; then
            rm -f -- "$f"
        fi
    done < <(ls -1t "$LOG_DIR"/refresh-*.log 2>/dev/null)
}

# ---- single-instance lock: a directory, whose creation is atomic on any POSIX fs -------
acquire_lock() {
    mkdir -p "$STATE_DIR"
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        echo "$$" > "$LOCK_DIR/pid"
        date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCK_DIR/started_at"
        return 0
    fi

    # The lock directory already exists. If its owning pid is still alive, a run is
    # genuinely in progress. If not, a previous run was killed rather than exiting
    # cleanly, and the lock is stale — left forever it would silently block every
    # future weekly run, which is worse than no lock at all, so it is reclaimed.
    local held_pid
    held_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [ -n "$held_pid" ] && kill -0 "$held_pid" 2>/dev/null; then
        return 1
    fi

    log "WARNING: found a stale lock (pid ${held_pid:-unknown} is not running, started" \
        "$(cat "$LOCK_DIR/started_at" 2>/dev/null || echo unknown)) -- reclaiming it."
    rm -rf "$LOCK_DIR"
    mkdir "$LOCK_DIR"
    echo "$$" > "$LOCK_DIR/pid"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCK_DIR/started_at"
    return 0
}

release_lock() {
    rm -rf "$LOCK_DIR"
}

# Single EXIT handler for the whole script: always prunes old logs (so rotation happens
# whether this run succeeded, failed, or was skipped for a held lock), and releases the
# lock only if THIS invocation is the one holding it (a skipped run never touches a lock
# it does not own).
LOCK_OWNED=0
cleanup() {
    rotate_logs
    if [ "$LOCK_OWNED" = "1" ]; then
        release_lock
    fi
}
trap cleanup EXIT

main() {
    log "===== weekly refresh starting (pid $$) ====="

    if ! acquire_lock; then
        log "SKIPPED: a previous run is still in progress (pid $(cat "$LOCK_DIR/pid" 2>/dev/null)). Not starting a second one."
        exit 2
    fi
    LOCK_OWNED=1

    local rc
    if [ -n "${LOFC_REFRESH_CMD:-}" ]; then
        log "Using LOFC_REFRESH_CMD override (TEST MODE — never set this in the real cron job): $LOFC_REFRESH_CMD"
        run_logged bash -c "$LOFC_REFRESH_CMD"
        rc=$?
    else
        log "Running: docker compose -f $COMPOSE_FILE exec -T app python -m lofc.pipeline"
        run_logged docker compose -f "$COMPOSE_FILE" exec -T app python -m lofc.pipeline
        rc=$?
    fi

    if [ "$rc" -eq 0 ]; then
        date -u +%Y-%m-%dT%H:%M:%SZ > "$LAST_SUCCESS_FILE"
        rm -f "$LAST_FAILURE_FILE"
        log "===== weekly refresh SUCCEEDED ====="
        exit 0
    fi

    {
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) refresh failed, exit code $rc"
        echo "log: $LOG_FILE"
    } > "$LAST_FAILURE_FILE"
    log "!!!!! WEEKLY REFRESH FAILED (exit $rc) !!!!! -- data is stale as of $(cat "$LAST_SUCCESS_FILE" 2>/dev/null || echo 'no prior success recorded'); investigate before the next run."
    exit 1
}

main "$@"
