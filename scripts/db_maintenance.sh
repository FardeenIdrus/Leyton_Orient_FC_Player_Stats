#!/usr/bin/env bash
# Weekly VACUUM (ANALYZE) of the big tables the pipeline rewrites, on OUR database (lofc).
#
# Why: the Monday refresh rebuilds several tables with delete-then-insert. Postgres does not
# hand the space of deleted rows back to the disk; it marks them dead and reuses the space
# only for later inserts into the same table. Left alone, the tables keep their peak size
# and the planner works from stale statistics. VACUUM (ANALYZE) reclaims the dead space for
# reuse and refreshes the planner's row counts. It does not shrink files on disk, and it
# takes no lock that blocks reads or writes, so it is safe to run on a live droplet.
#
# Each table gets one timestamped line: its total size before and after. A table whose
# VACUUM fails is reported and the rest still run; the script then exits 1 and writes
# last_failure, so a broken run cannot pass for a clean one. Success writes last_success.
#
# Runs on Sundays, after the build-cache prune (03:30 UTC) and before the Monday weekly
# refresh (04:15 UTC), so the tables are tidy before the pipeline rewrites them again.
#
# Logs: data/ops/maintenance.log (stdout and stderr of this script, via the crontab line).
#
# Overrides, for tests: LOFC_MAINT_DIR (marker directory), LOFC_PSQL_CMD (the psql command,
# word-split and run without a shell, so keep it free of quoting).
#
# crontab:  0 4 * * 0 /opt/lofc/scripts/db_maintenance.sh >> /opt/lofc/data/ops/maintenance.log 2>&1
set -uo pipefail

COMPOSE="docker compose -f /opt/lofc/docker-compose.prod.yml exec -T db"
DIR="${LOFC_MAINT_DIR:-/opt/lofc/data/ops}"
PSQL_CMD="${LOFC_PSQL_CMD:-$COMPOSE psql -U lofc -d lofc -v ON_ERROR_STOP=1}"

# The tables the weekly pipeline rewrites with delete-then-insert.
TABLES="player_detail_metrics player_style_signals player_metrics_neutral player_scorecards player_percentiles player_position_shares"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

size_of() {  # size_of <table> -> e.g. "3.7 GB", or "unknown" if the query fails
    local out
    out="$($PSQL_CMD -tA -c "SELECT pg_size_pretty(pg_total_relation_size('$1'))" 2>/dev/null)" \
        && [ -n "$out" ] && echo "$out" || echo "unknown"
}

mkdir -p "$DIR"
failed_tables=""

for table in $TABLES; do
    before="$(size_of "$table")"
    if $PSQL_CMD -c "VACUUM (ANALYZE) $table;" > /dev/null 2>&1; then
        status="vacuum ok"
    else
        status="vacuum FAILED"
        failed_tables="$failed_tables $table"
    fi
    after="$(size_of "$table")"
    echo "$(now) $table: $before -> $after ($status)"
done

if [ -n "$failed_tables" ]; then
    echo "$(now) maintenance FAILED:$failed_tables"
    echo "$(now) VACUUM failed for:$failed_tables" > "$DIR/last_failure"
    exit 1
fi

rm -f "$DIR/last_failure"
now > "$DIR/last_success"
echo "$(now) maintenance ok: $(echo $TABLES | wc -w | tr -d ' ') tables vacuumed"
