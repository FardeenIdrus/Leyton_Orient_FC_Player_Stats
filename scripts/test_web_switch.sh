#!/usr/bin/env bash
#
# scripts/test_web_switch.sh — exercises web_switch.sh (the zero-downtime switch of the public
# site to a freshly built web container) WITHOUT Docker: LOFC_DOCKER points at a fake `docker`
# that logs every call, reports the new container ready after N checks, and can fail the
# Caddy reload on request.
#
# Run:  bash scripts/test_web_switch.sh
#
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/web_switch.sh"
FAILURES=0
TESTS=0
pass() { TESTS=$((TESTS + 1)); echo "  ok   - $1"; }
fail() { TESTS=$((TESTS + 1)); FAILURES=$((FAILURES + 1)); echo "  FAIL - $1"; }
assert_eq() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (expected [$2], got [$3])"; fi; }
fresh() { mktemp -d "${TMPDIR:-/tmp}/lofc_switch_test.XXXXXX"; }

make_fake_docker() {  # make_fake_docker <dir>
    cat > "$1/docker" <<'FAKE'
#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
case "$*" in
    *readyz*)
        n=$(cat "$FAKE_COUNT" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$FAKE_COUNT"
        [ "$n" -ge "${FAKE_READY_AFTER:-1}" ] && exit 0 || exit 1 ;;
    *"caddy reload"*) [ -n "${FAKE_RELOAD_FAIL:-}" ] && exit 1 || exit 0 ;;
esac
exit 0
FAKE
    chmod +x "$1/docker"
}
run() {  # run <dir> ; extra env passed by the caller
    FAKE_LOG="$1/docker.log" FAKE_COUNT="$1/count" LOFC_DOCKER="$1/docker" \
        LOFC_REPO_ROOT="$1" LOFC_COMPOSE_FILE="$1/compose.yml" \
        LOFC_WEB_READY_TRIES="${TRIES:-5}" LOFC_WEB_READY_INTERVAL=0 \
        bash "$SCRIPT" > "$1/out.log" 2>&1
}
line_of() { grep -n -- "$2" "$1/docker.log" | head -1 | cut -d: -f1; }

echo "== Test 1: first deploy — Streamlit holds the site until web-blue is warm =="
D="$(fresh)"; make_fake_docker "$D"
FAKE_READY_AFTER=3 run "$D"; rc=$?
assert_eq "exits 0" "0" "$rc"
grep -q "up -d --no-deps --force-recreate web-blue" "$D/docker.log" && pass "starts web-blue" || fail "web-blue not started"
assert_eq "waited for three readiness checks" "3" "$(cat "$D/count")"
assert_eq "upstream now web-blue" "reverse_proxy web-blue:8600" "$(cat "$D/caddy/web_upstream.caddy")"
grep -q "caddy reload" "$D/docker.log" && pass "Caddy reloaded" || fail "no Caddy reload"
grep -q "stop dashboard" "$D/docker.log" && fail "stopped the Streamlit dashboard" || pass "dashboard left running"

echo "== Test 2: next deploy — web-green warms, then takes over, then web-blue stops =="
D="$(fresh)"; make_fake_docker "$D"; mkdir -p "$D/caddy"
echo "reverse_proxy web-blue:8600" > "$D/caddy/web_upstream.caddy"
run "$D"; rc=$?
assert_eq "exits 0" "0" "$rc"
assert_eq "upstream now web-green" "reverse_proxy web-green:8600" "$(cat "$D/caddy/web_upstream.caddy")"
r=$(line_of "$D" "caddy reload"); s=$(line_of "$D" "stop web-blue")
[ -n "$r" ] && [ -n "$s" ] && [ "$r" -lt "$s" ] && pass "old container stopped only after the switch" \
    || fail "stop/reload order wrong (reload line $r, stop line $s)"
grep -q "force-recreate web-blue" "$D/docker.log" && fail "touched the serving container" || pass "serving container untouched until the end"

echo "== Test 3: the new container never gets warm — nothing switches, exit 1 =="
D="$(fresh)"; make_fake_docker "$D"; mkdir -p "$D/caddy"
echo "reverse_proxy web-blue:8600" > "$D/caddy/web_upstream.caddy"
FAKE_READY_AFTER=999 TRIES=3 run "$D"; rc=$?
assert_eq "exits 1" "1" "$rc"
assert_eq "upstream unchanged" "reverse_proxy web-blue:8600" "$(cat "$D/caddy/web_upstream.caddy")"
grep -q "caddy reload" "$D/docker.log" && fail "Caddy reloaded anyway" || pass "no Caddy reload"
grep -q "stop web-blue" "$D/docker.log" && fail "stopped the serving container" || pass "serving container kept"
grep -q "stop web-green" "$D/docker.log" && pass "cold container stopped" || fail "cold container left running"

echo "== Test 4: the Caddy reload fails — upstream file restored, old container kept =="
D="$(fresh)"; make_fake_docker "$D"; mkdir -p "$D/caddy"
echo "reverse_proxy web-green:8600" > "$D/caddy/web_upstream.caddy"
FAKE_RELOAD_FAIL=1 run "$D"; rc=$?
assert_eq "exits 1" "1" "$rc"
assert_eq "upstream restored" "reverse_proxy web-green:8600" "$(cat "$D/caddy/web_upstream.caddy")"
grep -q "stop web-green" "$D/docker.log" && fail "stopped the serving container" || pass "serving container kept"

echo
echo "$TESTS checks, $FAILURES failed"
[ "$FAILURES" -eq 0 ]
