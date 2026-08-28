#!/usr/bin/env bash
#
# scripts/test_weekly_refresh.sh — exercises weekly_refresh.sh's logic (locking,
# logging, failure handling, exit codes, log rotation, stale-lock reclaim) WITHOUT
# touching Docker, the pipeline, or any scraper. Every scenario runs against a fresh
# temp directory and uses LOFC_REFRESH_CMD to stand in for "the refresh".
#
# Run:  bash scripts/test_weekly_refresh.sh
#
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/weekly_refresh.sh"
FAILURES=0
TESTS=0

pass() { TESTS=$((TESTS + 1)); echo "  ok   - $1"; }
fail() { TESTS=$((TESTS + 1)); FAILURES=$((FAILURES + 1)); echo "  FAIL - $1"; }

assert_eq() {
    local desc="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then pass "$desc"; else
        fail "$desc (expected [$expected], got [$actual])"
    fi
}

assert_file_exists() {
    local desc="$1" path="$2"
    if [ -e "$path" ]; then pass "$desc"; else fail "$desc (missing: $path)"; fi
}

assert_file_absent() {
    local desc="$1" path="$2"
    if [ ! -e "$path" ]; then pass "$desc"; else fail "$desc (should not exist: $path)"; fi
}

fresh_state_dir() {
    mktemp -d "${TMPDIR:-/tmp}/lofc_refresh_test.XXXXXX"
}

echo "== Test 1: success path =="
STATE="$(fresh_state_dir)"
LOFC_STATE_DIR="$STATE" LOFC_REFRESH_CMD="true" "$WRAPPER"
rc=$?
assert_eq  "exits 0 on success" "0" "$rc"
assert_file_exists "last_success written" "$STATE/last_success"
assert_file_absent "no last_failure on success" "$STATE/last_failure"
log_count=$(ls "$STATE"/logs/refresh-*.log 2>/dev/null | wc -l | tr -d ' ')
assert_eq "one log file written" "1" "$log_count"
grep -q "SUCCEEDED" "$STATE"/logs/refresh-*.log && pass "log contains SUCCEEDED banner" || fail "log missing SUCCEEDED banner"
grep -Eq '^\[[0-9]{4}-[0-9]{2}-[0-9]{2}T' "$STATE"/logs/refresh-*.log && pass "log lines are timestamped" || fail "log lines not timestamped"
assert_file_absent "lock released after run" "$STATE/refresh.lock"
rm -rf "$STATE"

echo "== Test 2: failure path leaves last_success untouched, writes last_failure =="
STATE="$(fresh_state_dir)"
LOFC_STATE_DIR="$STATE" LOFC_REFRESH_CMD="true" "$WRAPPER" >/dev/null   # seed a prior success
prior_success="$(cat "$STATE/last_success")"
sleep 1
LOFC_STATE_DIR="$STATE" LOFC_REFRESH_CMD="exit 7" "$WRAPPER"
rc=$?
assert_eq "exits 1 on pipeline failure" "1" "$rc"
assert_file_exists "last_failure written" "$STATE/last_failure"
grep -q "exit code 7" "$STATE/last_failure" && pass "last_failure records the exit code" || fail "last_failure missing exit code"
assert_eq "last_success NOT overwritten by a failed run" "$prior_success" "$(cat "$STATE/last_success")"
grep -q "WEEKLY REFRESH FAILED" "$STATE"/logs/refresh-*.log && pass "log contains a clearly-marked failure banner" || fail "log missing failure banner"
assert_file_absent "lock released after failed run" "$STATE/refresh.lock"
rm -rf "$STATE"

echo "== Test 3: a genuinely running lock is refused (exit 2), does not touch markers =="
STATE="$(fresh_state_dir)"
mkdir -p "$STATE"
mkdir "$STATE/refresh.lock"
echo $$ > "$STATE/refresh.lock/pid"          # this test process is definitely alive
date -u +%Y-%m-%dT%H:%M:%SZ > "$STATE/refresh.lock/started_at"
LOFC_STATE_DIR="$STATE" LOFC_REFRESH_CMD="true" "$WRAPPER"
rc=$?
assert_eq "exits 2 when locked by a live process" "2" "$rc"
assert_file_absent "no last_success from a skipped run" "$STATE/last_success"
assert_file_absent "no last_failure from a skipped run" "$STATE/last_failure"
assert_file_exists "the other process's lock is left alone" "$STATE/refresh.lock/pid"
rm -rf "$STATE"

echo "== Test 4: a stale lock (dead pid) is reclaimed, run proceeds and succeeds =="
STATE="$(fresh_state_dir)"
mkdir -p "$STATE"
mkdir "$STATE/refresh.lock"
echo 999999 > "$STATE/refresh.lock/pid"       # a pid essentially guaranteed not to exist
date -u +%Y-%m-%dT%H:%M:%SZ > "$STATE/refresh.lock/started_at"
LOFC_STATE_DIR="$STATE" LOFC_REFRESH_CMD="true" "$WRAPPER"
rc=$?
assert_eq "stale lock does not block the run" "0" "$rc"
grep -q "stale lock" "$STATE"/logs/refresh-*.log && pass "reclaiming a stale lock is logged" || fail "stale-lock reclaim not logged"
assert_file_exists "last_success written after reclaiming a stale lock" "$STATE/last_success"
rm -rf "$STATE"

echo "== Test 5: two overlapping runs -- the second is skipped while the first holds the lock =="
STATE="$(fresh_state_dir)"
LOFC_STATE_DIR="$STATE" LOFC_REFRESH_CMD="sleep 2 && true" "$WRAPPER" >/dev/null 2>&1 &
first_pid=$!
sleep 0.5   # let the first run acquire the lock before the second starts
LOFC_STATE_DIR="$STATE" LOFC_REFRESH_CMD="true" "$WRAPPER"
second_rc=$?
wait "$first_pid"
first_rc=$?
assert_eq "the overlapping second run is skipped" "2" "$second_rc"
assert_eq "the first (still-running) refresh completes successfully" "0" "$first_rc"
assert_file_exists "last_success reflects the first run's completion" "$STATE/last_success"
rm -rf "$STATE"

echo "== Test 6: log rotation caps the number of retained logs =="
STATE="$(fresh_state_dir)"
for i in 1 2 3 4; do
    LOFC_STATE_DIR="$STATE" LOFC_LOG_KEEP=2 LOFC_REFRESH_CMD="true" "$WRAPPER" >/dev/null
    sleep 1.1   # RUN_STAMP has 1-second resolution; force distinct filenames
done
kept=$(ls "$STATE"/logs/refresh-*.log 2>/dev/null | wc -l | tr -d ' ')
assert_eq "only LOG_KEEP=2 most recent logs are retained" "2" "$kept"
rm -rf "$STATE"

echo
echo "== Test 7: never invokes docker unless LOFC_REFRESH_CMD is unset =="
STATE="$(fresh_state_dir)"
FAKE_BIN="$(mktemp -d "${TMPDIR:-/tmp}/lofc_fakebin.XXXXXX")"
cat > "$FAKE_BIN/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker was invoked with: $*" >&2
exit 99
EOF
chmod +x "$FAKE_BIN/docker"
PATH="$FAKE_BIN:$PATH" LOFC_STATE_DIR="$STATE" LOFC_REFRESH_CMD="true" "$WRAPPER"
rc=$?
assert_eq "docker is never called when LOFC_REFRESH_CMD is set" "0" "$rc"
rm -rf "$STATE" "$FAKE_BIN"

echo
echo "-----------------------------------------------------------"
echo "$TESTS checks run, $FAILURES failed"
[ "$FAILURES" -eq 0 ]
