#!/usr/bin/env bash
# Nightly dump of OUR database (lofc) only -- not the colleague's, which shares the droplet.
#
# Why, when DigitalOcean already backs up the whole droplet: restoring a droplet backup
# rolls back EVERYTHING on it, his platform included. This dump restores our data alone.
# It lives on the same disk, so it guards against mistakes (a dropped table, a bad
# migration, a deleted volume), not against loss of the droplet -- that is what the
# DigitalOcean backups are for.
#
# Each dump is written to a .partial file, checked with `pg_restore --list` (proves it is a
# complete, readable archive), and only then renamed into place. Retention is by COUNT,
# not age, so a run of failed nights can never delete the last good backups.
#
# Restore (Server):
#   docker compose -f /opt/lofc/docker-compose.prod.yml exec -T db \
#       pg_restore -U lofc -d lofc --clean --if-exists --no-owner < /opt/lofc/backups/lofc-<stamp>.dump
#
# crontab:  30 19 * * * /opt/lofc/scripts/db_backup.sh >> /opt/lofc/backups/backup.log 2>&1
set -uo pipefail

COMPOSE="docker compose -f /opt/lofc/docker-compose.prod.yml exec -T db"
DIR="${LOFC_BACKUP_DIR:-/opt/lofc/backups}"
KEEP="${LOFC_BACKUP_KEEP:-14}"
DUMP_CMD="${LOFC_DUMP_CMD:-$COMPOSE pg_dump -U lofc -Fc lofc}"
VERIFY_CMD="${LOFC_VERIFY_CMD:-$COMPOSE pg_restore --list}"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

umask 077
mkdir -p "$DIR"
stamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
final="$DIR/lofc-$stamp.dump"
partial="$final.partial"

failed() {
    rm -f "$partial"
    echo "$(now) backup FAILED: $1"
    echo "$(now) $1" > "$DIR/last_failure"
    exit 1
}

bash -c "$DUMP_CMD" > "$partial" || failed "pg_dump exited non-zero"
[ -s "$partial" ] || failed "dump is empty"
bash -c "$VERIFY_CMD" < "$partial" > /dev/null || failed "dump did not verify"
mv "$partial" "$final"

# Keep the newest $KEEP dumps. Only reached after a verified success.
ls -1t "$DIR"/lofc-*.dump | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f "$old"; done

rm -f "$DIR/last_failure"
now > "$DIR/last_success"
echo "$(now) backup ok: $(basename "$final") ($(du -h "$final" | cut -f1))"
