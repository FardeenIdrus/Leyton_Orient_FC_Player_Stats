#!/usr/bin/env bash
#
# scripts/web_switch.sh — move the public site to a freshly built web container, with no cold
# moment for users (owner, 2026-11-09). Called by deploy.sh after the images are built.
#
# Two identical web services run from the same image: web-blue and web-green. Caddy's main
# domain proxies to whichever one caddy/web_upstream.caddy names. This script:
#   1. (re)creates the OTHER colour from the new image;
#   2. waits until its /readyz answers 200 -- every start-up warm-up done;
#   3. points the upstream file at it and reloads Caddy (a graceful reload: no dropped requests);
#   4. only then stops the old colour, freeing its memory.
# If the new container never gets warm, or the reload fails, nothing switches: the old one keeps
# serving and the script exits 1. On the very first run there is no colour yet: the upstream is
# the Streamlit dashboard, which keeps serving the main domain until web-blue is warm.
#
# Exit codes: 0 switched, 1 nothing switched (read the output).

set -uo pipefail

REPO_ROOT="${LOFC_REPO_ROOT:-/opt/lofc}"
COMPOSE_FILE="${LOFC_COMPOSE_FILE:-$REPO_ROOT/docker-compose.prod.yml}"
DOCKER="${LOFC_DOCKER:-docker}"
TRIES="${LOFC_WEB_READY_TRIES:-120}"          # x interval = how long a warm-up may take
INTERVAL="${LOFC_WEB_READY_INTERVAL:-10}"
UPSTREAM="$REPO_ROOT/caddy/web_upstream.caddy"

say() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
dc() { "$DOCKER" compose -f "$COMPOSE_FILE" "$@"; }

mkdir -p "$(dirname "$UPSTREAM")"
[ -f "$UPSTREAM" ] || echo "reverse_proxy dashboard:8501" > "$UPSTREAM"
previous="$(cat "$UPSTREAM")"
case "$previous" in
    *web-blue*)  current=web-blue;  next=web-green ;;
    *web-green*) current=web-green; next=web-blue ;;
    *)           current="";        next=web-blue ;;
esac
say "serving: ${current:-the Streamlit dashboard}; starting $next from the new image"
dc up -d --no-deps --force-recreate "$next"

say "waiting for $next to finish its warm-up (/readyz)..."
ready=""
for i in $(seq 1 "$TRIES"); do
    if dc exec -T "$next" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8600/readyz', timeout=5)" >/dev/null 2>&1; then
        ready=1; break
    fi
    sleep "$INTERVAL"
done
if [ -z "$ready" ]; then
    say "ERROR: $next not warm after $((TRIES * INTERVAL)) s -- nothing switched; ${current:-the dashboard} keeps serving"
    dc stop "$next"
    exit 1
fi

say "$next is warm; switching Caddy to it"
echo "reverse_proxy $next:8600" > "$UPSTREAM"
if ! dc exec -T caddy caddy reload --config /etc/caddy/Caddyfile; then
    echo "$previous" > "$UPSTREAM"
    say "ERROR: Caddy reload failed -- upstream restored; ${current:-the dashboard} keeps serving"
    exit 1
fi

if [ -n "$current" ]; then
    say "stopping the previous container $current"
    dc stop "$current"
fi
say "serving: $next"
