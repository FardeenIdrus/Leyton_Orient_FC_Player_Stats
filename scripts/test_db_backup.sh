#!/usr/bin/env bash
#
# scripts/test_db_backup.sh — exercises db_backup.sh's logic (atomic write, verification,
# count-based retention, failure markers) WITHOUT Docker or Postgres. LOFC_DUMP_CMD and
# LOFC_VERIFY_CMD stand in for pg_dump and pg_restore --list.
#
# Run:  bash scripts/test_db_backup.sh
#
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/db_backup.sh"
FAILURES=0
TESTS=0

pass() { TESTS=$((TESTS + 1)); echo "  ok   - $1"; }
fail() { TESTS=$((TESTS + 1)); FAILURES=$((FAILURES + 1)); echo "  FAIL - $1"; }
assert_eq() {
    if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (expected [$2], got [$3])"; fi
}
count_dumps() { ls "$1"/lofc-*.dump 2>/dev/null | wc -l | tr -d ' '; }
fresh() { mktemp -d "${TMPDIR:-/tmp}/lofc_backup_test.XXXXXX"; }
run() {  # run <dir> <dump cmd> <verify cmd> [keep]
    LOFC_BACKUP_DIR="$1" LOFC_DUMP_CMD="$2" LOFC_VERIFY_CMD="$3" LOFC_BACKUP_KEEP="${4:-14}" \
        "$SCRIPT" >/dev/null 2>&1
}

echo "== Test 1: success writes one dump, a success marker, no partial file =="
D="$(fresh)"
run "$D" "echo PGDMP-data" "cat >/dev/null"
assert_eq "exits 0" "0" "$?"
assert_eq "one dump written" "1" "$(count_dumps "$D")"
assert_eq "dump holds what pg_dump produced" "PGDMP-data" "$(cat "$D"/lofc-*.dump)"
[ -f "$D/last_success" ] && pass "last_success written" || fail "last_success missing"
[ ! -f "$D/last_failure" ] && pass "no last_failure" || fail "last_failure written on success"
assert_eq "no partial file left" "0" "$(ls "$D"/*.partial 2>/dev/null | wc -l | tr -d ' ')"
rm -rf "$D"

echo "== Test 2: a failed pg_dump keeps no dump and writes last_failure =="
D="$(fresh)"
run "$D" "exit 3" "cat >/dev/null"
assert_eq "exits 1" "1" "$?"
assert_eq "no dump kept" "0" "$(count_dumps "$D")"
[ -f "$D/last_failure" ] && pass "last_failure written" || fail "last_failure missing"
assert_eq "no partial file left" "0" "$(ls "$D"/*.partial 2>/dev/null | wc -l | tr -d ' ')"
rm -rf "$D"

echo "== Test 3: an empty dump is rejected =="
D="$(fresh)"
run "$D" "true" "cat >/dev/null"
assert_eq "exits 1" "1" "$?"
assert_eq "no dump kept" "0" "$(count_dumps "$D")"
rm -rf "$D"

echo "== Test 4: a dump that fails verification is rejected =="
D="$(fresh)"
run "$D" "echo garbage" "exit 1"
assert_eq "exits 1" "1" "$?"
assert_eq "no dump kept" "0" "$(count_dumps "$D")"
rm -rf "$D"

echo "== Test 5: retention keeps the newest N, oldest removed =="
D="$(fresh)"
for i in 01 02 03 04 05; do
    echo old > "$D/lofc-2026-01-${i}T000000Z.dump"
    touch -t "2026010${i#0}0000" "$D/lofc-2026-01-${i}T000000Z.dump"
done
run "$D" "echo PGDMP-new" "cat >/dev/null" 3
assert_eq "exits 0" "0" "$?"
assert_eq "three dumps kept" "3" "$(count_dumps "$D")"
[ ! -f "$D/lofc-2026-01-01T000000Z.dump" ] && pass "oldest removed" || fail "oldest kept"
grep -l PGDMP-new "$D"/lofc-*.dump >/dev/null && pass "new dump kept" || fail "new dump removed"
rm -rf "$D"

echo "== Test 6: a failed run never deletes existing backups =="
D="$(fresh)"
for i in 1 2 3 4 5; do echo old > "$D/lofc-2026-01-0${i}T000000Z.dump"; done
run "$D" "exit 3" "cat >/dev/null" 2
assert_eq "all five old dumps still there" "5" "$(count_dumps "$D")"
rm -rf "$D"

echo "== Test 7: dumps are readable by the owner only =="
D="$(fresh)"
run "$D" "echo PGDMP-data" "cat >/dev/null"
perms="$(ls -l "$D"/lofc-*.dump | cut -c1-10)"
assert_eq "mode -rw-------" "-rw-------" "$perms"
rm -rf "$D"

echo
echo "$TESTS tests, $FAILURES failures"
[ "$FAILURES" -eq 0 ]
