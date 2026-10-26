#!/usr/bin/env bash
#
# scripts/test_db_maintenance.sh — exercises db_maintenance.sh's logic (one VACUUM per table,
# one line of size before/after, failure markers, continuing past a failed table) WITHOUT
# Docker or Postgres. LOFC_PSQL_CMD is replaced by a fake psql that logs its arguments and
# fails on request.
#
# Run:  bash scripts/test_db_maintenance.sh
#
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/db_maintenance.sh"
FAILURES=0
TESTS=0

pass() { TESTS=$((TESTS + 1)); echo "  ok   - $1"; }
fail() { TESTS=$((TESTS + 1)); FAILURES=$((FAILURES + 1)); echo "  FAIL - $1"; }
assert_eq() {
    if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (expected [$2], got [$3])"; fi
}
fresh() { mktemp -d "${TMPDIR:-/tmp}/lofc_maint_test.XXXXXX"; }

# A fake psql: records every invocation, prints a fixed size for size queries, and fails a
# VACUUM when FAKE_FAIL_TABLE names a table that appears in it.
make_fake_psql() {  # make_fake_psql <dir>
    cat > "$1/fake_psql.sh" <<'FAKE'
#!/usr/bin/env bash
echo "$*" >> "$FAKE_PSQL_LOG"
case "$*" in
    *VACUUM*)
        if [ -n "${FAKE_FAIL_TABLE:-}" ] && [[ "$*" == *"$FAKE_FAIL_TABLE"* ]]; then
            echo "ERROR: vacuum failed" >&2
            exit 1
        fi
        exit 0 ;;
    *pg_size_pretty*) echo "12 MB"; exit 0 ;;
esac
exit 0
FAKE
    chmod +x "$1/fake_psql.sh"
}
run() {  # run <dir> [fail-table]
    FAKE_PSQL_LOG="$1/psql.log" FAKE_FAIL_TABLE="${2:-}" \
        LOFC_MAINT_DIR="$1/ops" LOFC_PSQL_CMD="$1/fake_psql.sh" \
        "$SCRIPT" > "$1/out.log" 2>&1
}
vacuum_count() { grep -c "VACUUM (ANALYZE)" "$1/psql.log" 2>/dev/null || echo 0; }

TABLES="player_detail_metrics player_style_signals player_metrics_neutral player_scorecards player_percentiles player_position_shares"

echo "== Test 1: every table is vacuumed, success marker written, exit 0 =="
D="$(fresh)"; make_fake_psql "$D"
run "$D"
assert_eq "exits 0" "0" "$?"
assert_eq "one VACUUM per table" "6" "$(vacuum_count "$D")"
for t in $TABLES; do
    grep -q "VACUUM (ANALYZE) $t;" "$D/psql.log" && pass "vacuumed $t" || fail "not vacuumed: $t"
done
[ -f "$D/ops/last_success" ] && pass "last_success written" || fail "last_success missing"
[ ! -f "$D/ops/last_failure" ] && pass "no last_failure" || fail "last_failure written on success"
rm -rf "$D"

echo "== Test 2: one line per table with size before and after =="
D="$(fresh)"; make_fake_psql "$D"
run "$D"
assert_eq "six report lines" "6" "$(grep -c "player_" "$D/out.log")"
grep -q "player_detail_metrics: 12 MB -> 12 MB" "$D/out.log" \
    && pass "size before and after printed" || fail "size line missing or wrong"
grep -q "pg_size_pretty(pg_total_relation_size" "$D/psql.log" \
    && pass "size read with pg_total_relation_size" || fail "size query not run"
rm -rf "$D"

echo "== Test 3: a failed VACUUM exits 1, writes last_failure, and the rest still run =="
D="$(fresh)"; make_fake_psql "$D"
run "$D" player_scorecards
assert_eq "exits 1" "1" "$?"
assert_eq "all six tables still attempted" "6" "$(vacuum_count "$D")"
[ -f "$D/ops/last_failure" ] && pass "last_failure written" || fail "last_failure missing"
grep -q "player_scorecards" "$D/ops/last_failure" \
    && pass "last_failure names the failed table" || fail "last_failure does not name it"
[ ! -f "$D/ops/last_success" ] && pass "no last_success on failure" || fail "last_success written"
rm -rf "$D"

echo "== Test 4: a later success clears an earlier last_failure =="
D="$(fresh)"; make_fake_psql "$D"
run "$D" player_scorecards
run "$D"
assert_eq "second run exits 0" "0" "$?"
[ ! -f "$D/ops/last_failure" ] && pass "last_failure cleared" || fail "last_failure kept"
[ -f "$D/ops/last_success" ] && pass "last_success written" || fail "last_success missing"
rm -rf "$D"

echo
echo "$TESTS tests, $FAILURES failures"
[ "$FAILURES" -eq 0 ]
