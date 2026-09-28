#!/usr/bin/env bash
# Sync the club's scouting sheet into Postgres. READ-ONLY: the service-account token
# carries only `spreadsheets.readonly`, so Google rejects a write with HTTP 403.
#
# Runs every minute. The overwhelmingly common outcome is "unchanged" -- the sheet moves a
# few times a day -- and the stage detects that from a content hash and exits before
# opening a database transaction. One Sheets API call per run: ~1.7% of the 60/min quota.
#
# Deliberately NOT part of weekly_refresh.sh. That rebuilds scores from the providers and
# takes minutes; this is a small, frequent read on a different cadence, and coupling them
# would mean scout reports were a week stale.
#
# crontab:  * * * * * /opt/lofc/scripts/scout_sync.sh >> /opt/lofc/data/ops/scout_sync.log 2>&1
set -euo pipefail

cd /opt/lofc
mkdir -p data/ops

# A run that overlaps the previous one would race two upserts against the same rows.
# flock makes a slow run skip the next tick rather than pile up.
exec 9>/tmp/lofc_scout_sync.lock
flock -n 9 || { echo "$(date -Is) previous sync still running; skipped"; exit 0; }

if ! docker compose -f docker-compose.prod.yml exec -T app \
        python -m lofc.store.scout_reports; then
    echo "$(date -Is) scout sync FAILED"
    date -Is > data/ops/scout_sync_failure
    exit 1
fi
date -Is > data/ops/scout_sync_success
