# Deployment

The platform is one Docker stack, so deploying means running it on a machine that's online.
This covers two cases: a **permanent URL on a server** (Option A), and a **quick shareable link
from your laptop** for a demo (Option B).

---

## The live server — what runs where (verified 2026-10-16 to 10-22)

| | |
|---|---|
| URL | https://lofc-recruitment.duckdns.org (a `leytonorient.com` name is pending with club IT) |
| Host | DigitalOcean droplet `lofc-platform`, London, Ubuntu 24.04, **2 vCPU / 3.8 GB RAM / 77 GB disk**, IP 165.22.122.157 |
| Code | `/opt/lofc`, branch `main`, `docker-compose.prod.yml` (db, app, dashboard, caddy) |
| Network | DigitalOcean Cloud Firewall `lofc-platform-fw`: inbound TCP 22/80/443 only. Postgres is not exposed |
| Docker logs | Capped in `/etc/docker/daemon.json` (json-file, 10 MB × 3 per container) |
| OS upgrade | Ubuntu offers 26.04 — **not planned**; do not run `do-release-upgrade` without a snapshot and a plan |

**Scheduled jobs** (root crontab; times UTC):

| When | Job | Does |
|---|---|---|
| Every minute | `scripts/scout_sync.sh` | Reads the club's scouting Google Sheet (read-only); writes only changes |
| Daily 19:30 | `scripts/db_backup.sh` | Dumps OUR database to `/opt/lofc/backups` (14 kept, each verified) |
| Sunday 03:30 | `docker builder prune -f --filter until=168h` | Clears Docker build cache (it grew 22 GB from deploys) |
| Sunday 04:00 | `scripts/db_maintenance.sh` | `VACUUM (ANALYZE)` on the tables the pipeline rewrites weekly (reclaims dead rows) |
| Monday 04:15 | `scripts/weekly_refresh.sh` | Impect + SkillCorner pull, rebuild, re-score. Result in `data/ops/last_success` / `last_failure` |

**Backups — two layers:**

| | Nightly dump | DigitalOcean backup |
|---|---|---|
| Copies | Our database only | The whole server |
| Stored | On the server, `/opt/lofc/backups` | Off the server, in DigitalOcean |
| Schedule / kept | 19:30 UTC, 14 | Daily, window 21:00–01:00 UK time, 7 |
| Use it for | Undoing a data mistake without touching anything else | Losing the server |

Restore our database from a dump (overwrites it):
```bash
docker compose -f /opt/lofc/docker-compose.prod.yml exec -T db \
    pg_restore -U lofc -d lofc --clean --if-exists --no-owner < /opt/lofc/backups/lofc-<stamp>.dump
```

**A second platform shares this droplet** (a colleague's match-analysis app, since
2026-10-16): Linux user `matchanalysis` (in the `docker` group — effectively root), code in
`/opt/match-analysis`, its own Compose project and Postgres. Its web container joins our
`lofc_default` network with the alias `match-analysis` on port 5050 and publishes no ports; our
Caddy routes `orient-matchanalysis.duckdns.org` to it (see `Caddyfile`). Our `.env` is
`chmod 600` so it is not readable without Docker access.

### Two machines, two jobs

| | Server | Workstation (Mac) |
|---|---|---|
| Role | Authoritative; the data staff use | Development; **all Transfermarkt scraping** |
| Refreshes itself | Weekly (above) | Never |
| `.env` | has `SKIP_TRANSFERMARKT_SCRAPE=true` | does not |

The server's database drifts ahead of the workstation's. **Before any data work on the
workstation, resync it from the server:**
```bash
ssh root@SERVER "docker compose -f /opt/lofc/docker-compose.prod.yml exec -T db pg_dump -U lofc -Fc lofc" > /tmp/prod.dump
docker compose exec -T db psql -U lofc -d lofc -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec -T db pg_restore -U lofc -d lofc --no-owner < /tmp/prod.dump
```

### Lessons that cost real time

- **`.env` changes need a recreate, not a restart.** Compose injects `env_file` values when a
  container is CREATED; `restart` keeps the old values, and they override the file. Use
  `docker compose -f docker-compose.prod.yml up -d --force-recreate app dashboard` (and
  `caddy` for `DASHBOARD_DOMAIN` or `Caddyfile` changes), then check with
  `docker compose ... exec -T app printenv <NAME>`.
- **`--force-recreate` does not rebuild.** It reuses the existing image; code or dependency
  changes need `deploy.sh`.
- **`deploy.sh` does not re-score.** It ships code and runs migrations. A change to stored
  scores needs the relevant pipeline step afterwards — only when data must be rebuilt.
- **After a manual `docker compose stop`, containers do NOT come back on reboot**
  (`restart: unless-stopped` honours the stop). Start them with `up -d`.
- **`secrets/` never travels with a deploy** (gitignored). Copy the Google service-account key
  by hand into `/opt/lofc/secrets/`, owned by UID 1000 (the container user).

---

## ⚠️ Two constraints that decide how a server is set up (read before deploying)

### 1. Transfermarkt cannot be scraped from a server

Verified on a DigitalOcean droplet, 2026-09-12. Transfermarkt is behind **AWS WAF Bot Control**.
A datacentre IP receives HTTP **202 with a JavaScript challenge page** (`awsWafCookieDomainList`,
`gokuProps`, ~2.4 KB) instead of the ~200 KB squad page the same request returns from a home
connection. A full browser header set does not change the outcome.

**Do not attempt to bypass it.** Passing the challenge requires executing their JavaScript to mint
a WAF token — circumventing bot protection, which this project does not do.

**Set on the server:**

```
SKIP_TRANSFERMARKT_SCRAPE=true
```

This omits `ingest.transfermarkt_efl` and `ingest.transfermarkt_loans`. **Without it the pipeline
halts at that stage and scoring, scorecards and shortlists never run.** The loaders
(`store.squads`, `store.loans`, `store.injuries`) still run, so data pushed from a workstation is still ingested.

**Refreshing registration data** (contracts, squads, loans, injuries) — on a workstation:

```bash
python -m lofc.ingest.transfermarkt_efl --force
python -m lofc.ingest.transfermarkt_loans
python -m lofc.ingest.transfermarkt_injuries
rsync -avz data/reference/transfermarkt/ root@SERVER:/opt/lofc/data/reference/transfermarkt/
```

then on the server, copy into the app volume and re-run the loaders (see below).

Loans travel the same way since 2026-11-02: `transfermarkt_loans` also writes
`reference/transfermarkt/loans.csv`, the rsync carries it, and `python -m lofc.store.loans` loads
it (every weekly run does this too). A file far smaller than what is stored is refused and the
stored loans kept; at the end of May, when most loans end, load with `--allow-shrink`.

### 2. `data/` lives in a Docker VOLUME, not on the host

`docker-compose.prod.yml` mounts `appdata:/app/data` for the `app` service. Files placed in
`/opt/lofc/data` on the host are **invisible** to the container. Load them with `docker cp`:

```bash
APP=$(docker compose -f docker-compose.prod.yml ps -q app)
docker compose -f docker-compose.prod.yml exec -u root app mkdir -p /app/data/raw /app/data/reference
docker cp /opt/lofc/data/raw/impect      "$APP":/app/data/raw/
docker cp /opt/lofc/data/raw/skillcorner "$APP":/app/data/raw/
docker cp /opt/lofc/data/reference/.     "$APP":/app/data/reference/
docker compose -f docker-compose.prod.yml exec -u root app chown -R appuser:appuser /app/data
```

The final `chown` is required: the image runs as `appuser`, and `docker cp` lands files as root.

The `dashboard` service mounts no data at all — it runs entirely from Postgres.


### 3. Deploying code changes — always manual

Nothing reaches the server on its own. `scripts/weekly_refresh.sh` (the Monday cron) runs the
PIPELINE; it never runs `git pull`. Pushing to GitHub deploys nothing.

`git pull` on its own is also not enough: the image bakes the source in at build time, so without
`--build` the running containers keep serving the OLD code while `git log` shows the new commit.

```bash
ssh root@SERVER
/opt/lofc/scripts/deploy.sh      # pull, rebuild, migrate, report status
```

About 3 minutes, most of it the rebuild. The site stays up until the new containers swap in.


### 4. The repository is PRIVATE — the server needs a deploy key

It was public when the droplet was first provisioned, so `git pull` worked anonymously over
HTTPS. Once it was made private that stopped, and `scripts/deploy.sh` failed at the pull with
*"Password authentication is not supported for Git operations"*.

**On a new or rebuilt server:**

```bash
ssh-keygen -t ed25519 -f /root/.ssh/id_ed25519 -N "" -C "lofc-platform-deploy"
cat /root/.ssh/id_ed25519.pub
```

Add that key at **GitHub → repo → Settings → Deploy keys → Add deploy key**, titled after the
machine (e.g. `lofc-platform (DigitalOcean)`). **Leave "Allow write access" unticked** — the
server only ever pulls.

Then switch the remote to SSH and confirm:

```bash
cd /opt/lofc
git remote set-url origin git@github.com:FardeenIdrus/Leyton_Orient_FC_Player_Stats.git
ssh -o StrictHostKeyChecking=accept-new -T git@github.com
```

`"Hi <repo>! You've successfully authenticated, but GitHub does not provide shell access."` is
success, not an error.

### 5. Production runs `main`

Changed 2026-09-18. The deployed branch was previously `r3a0-injury-scrape`, which had become
the trunk in practice while `main` sat weeks behind — a trap, since cloning `main` produced an
old platform. Branch for a piece of work, merge to `main`, deploy `main`. Nothing else is
deployed.

```bash
cd /opt/lofc && git checkout main
```

### What to copy to a new server (~400 MB, never 21 GB)

| Item | Size |
|---|---|
| `pg_dump` of the database | ~8 MB compressed |
| `data/raw/impect` | 218 MB |
| `data/reference` | 183 MB |
| `data/raw/skillcorner` | 1.1 MB |

**Not** `data/raw/{3,4,5,65}` — 21 GB of StatsBomb events that nothing reads under `impect_only`
(`ingest.run`, `aggregate.run` and `store.load` are skipped; the spine comes from the dump).


## Option A — Permanent deployment on a server (a real URL)

You need: a Linux server/VM with Docker installed, reachable **from the public internet, not
only a club LAN** (a cloud VM such as DigitalOcean, Hetzner or AWS gets you this by default —
~4-8 GB RAM is plenty; the club's own server works too, but only if its ports 80/443 are
forwarded from the internet, not just visible on the local network), and a **domain name
pointed at the server's IP** (an A record). Caddy then issues HTTPS automatically.

The production stack (`docker-compose.prod.yml`) publishes **only the dashboard**, behind Caddy
for automatic HTTPS. The database, the app container and the admin tools (pgAdmin, Metabase)
are not exposed to the internet. Access control is the platform's **own login** — real
accounts, scrypt-hashed passwords, lockout after 5 failed attempts, 12-hour sessions — not a
separate Caddy password. (Older versions of this doc had Caddy issue its own basic-auth
password on top of that; that predated the platform having any login of its own and has been
removed — see "Why no Caddy basic-auth" below.)

### Steps
1. **Put the code on the server** and `cd` into it:
   ```bash
   git clone <repo-url> && cd Leyton_Orient_FC_Player_Stats
   ```
2. **Create `.env`** with production values:
   ```bash
   POSTGRES_USER=lofc
   POSTGRES_PASSWORD=a-strong-password-here
   POSTGRES_DB=lofc
   DATABASE_URL=postgresql+psycopg2://lofc:a-strong-password-here@db:5432/lofc

   # StatsBomb (leave blank for open data, or fill in for the paid API):
   USE_OPEN_DATA=true
   SB_USERNAME=
   SB_PASSWORD=

   # Impect / SkillCorner (leave blank to skip either provider):
   IMPECT_USERNAME=
   IMPECT_PASSWORD=
   SKILLCORNER_USERNAME=
   SKILLCORNER_PASSWORD=

   # Public dashboard domain (Caddy issues HTTPS for this automatically):
   DASHBOARD_DOMAIN=recruitment.yourclub.com

   # Signs the "remembered session" cookie so a browser refresh doesn't sign staff out.
   # REQUIRED for login to persist across a refresh -- leaving it blank does not error,
   # it just silently drops back to a session that dies on every reconnect. Generate one:
   #   python3 -c "import secrets; print(secrets.token_hex(32))"
   SESSION_SECRET=
   ```
   See `.env.example` for the full list of optional variables (target competitions,
   Impect/SkillCorner iteration overrides, `IMPECT_ONLY`).
3. **Start the stack** (builds the lean image, brings up db + app + dashboard + Caddy):
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
4. **Populate the database** (first run downloads data; ~20-40 min):
   ```bash
   docker compose -f docker-compose.prod.yml exec app python -m lofc.pipeline
   ```
5. **Create the first admin account.** There is no self-service sign-up — every account,
   including the first one, is created from a shell on the server. Run this interactively (not
   `-T`) so the password prompt works, and keep it off any shared screen:
   ```bash
   docker compose -f docker-compose.prod.yml exec app \
     python -m lofc.admin create-user --username <you> --name "Your Name" --role admin
   ```
   It prompts for a password (minimum 12 characters) without echoing it. Create further
   accounts the same way, with `--role` one of `scout`, `medical`, `head_of_recruitment`,
   `admin` — an admin can also do this later from the dashboard's Users page. A forgotten
   password is reset the same way, in person, with `python -m lofc.admin set-password
   --username <name>` (there is no email/self-service reset — the users table holds no email
   address at all).
6. **Open `https://recruitment.yourclub.com`** and sign in with the account from step 5 — the
   dashboard is live, on any device, from anywhere.

### Keeping data fresh (weekly refresh)
`scripts/weekly_refresh.sh` wraps `python -m lofc.pipeline` with a lock, rotated logs and
success/failure markers in `data/ops/`. On a new server, install the cron lines listed under
"The live server" above. Check `data/ops/last_success` / `data/ops/last_failure` to see
whether the last run worked.

### Why no Caddy basic-auth
Caddy used to also gate the dashboard behind its own shared basic-auth password
(`DASHBOARD_USER` / `DASHBOARD_PASSWORD_HASH`), because at the time it was the *only*
protection the app had. That is no longer true: the platform now has real per-user accounts
(scrypt-hashed passwords, a 12-character minimum, lockout after 5 failed attempts, 12-hour
sessions, cookie-persisted logins, roles) with an admin Users page. Keeping the Caddy layer on
top would mean every visitor types a second, club-wide shared password before ever reaching
their own login — a password that has to be told to everyone, never expires, isn't tied to a
person, and (being shared) is exactly the kind of credential people write down or forward
around. That's friction with no real security upside once the app-level login covers the same
ground properly, so it has been removed: **one login, the platform's own.** `Caddyfile` now
only terminates HTTPS and reverse-proxies to the dashboard.
(If you want a second layer anyway — e.g. to keep the platform off search engines and casual
drive-bys entirely — put IP allowlisting or a VPN in front of Caddy instead of basic-auth; it
doesn't collide with the app's own login the way a second password does.)

### Notes
- **Admin tools** (pgAdmin/Metabase) aren't exposed publicly in prod. Reach them over an SSH
  tunnel, e.g. `ssh -L 3000:localhost:3000 user@server` then open `localhost:3000`. (Add them to
  the Caddyfile on their own subdomain if you want them public — each already has its own login.)
- **Backups:** see "The live server" above (nightly dump + DigitalOcean backups).
- **Updates:** `scripts/deploy.sh` (pull, rebuild, migrate) — see section 3 above.
- **Login-spray throttling:** the app throttles a burst of failed logins across many DIFFERENT
  usernames (`dashboard/login_throttle.py`), not by source address — behind a bare `cloudflared`
  quick tunnel or Caddy's default `reverse_proxy` (neither normalises a trusted client address
  today) there is no dependable, non-spoofable IP to key a limiter on. It's process-wide
  in-memory state, correct for the single `dashboard` container this stack runs today. If this
  is ever scaled to multiple dashboard replicas behind a real load balancer, move rate-limiting
  there instead (where a trusted client address is more likely available) rather than relying on
  this throttle, which would then only see a fraction of the traffic per replica.

---

## Option B — Quick shareable link from your laptop (no server, for a demo)

Run the app locally as usual, then expose `localhost:8501` through a tunnel. The link works on
any device (phone, the interviewer's laptop) **while your machine is running it**. The
platform's own login gate applies here too; set `SESSION_SECRET` in your local `.env` (see
Option A step 2) if you want a signed-in session to survive a page refresh during the demo.

```bash
docker compose up -d                 # the normal local stack
# (populate once if you haven't: docker compose exec app python -m lofc.pipeline)
# (create an account once if you haven't: docker compose exec app python -m lofc.admin create-user --username <you> --name "Your Name" --role admin)
```
Then, in another terminal, one of:

- **Cloudflare (no signup):**
  ```bash
  brew install cloudflared        # or download it
  cloudflared tunnel --url http://localhost:8501
  ```
  It prints a temporary `https://<random>.trycloudflare.com` URL. Share that.

- **ngrok (free account):**
  ```bash
  brew install ngrok
  ngrok http 8501
  ```
  It prints a public `https://<random>.ngrok-free.app` URL.

This is the fastest way to "open it on my phone" for an interview. It is a tunnel to your laptop,
not a real deployment — close the terminal and the link dies.

---

## Which to use
- **Interview demo:** Option B (or just run locally and screen-share).
- **Something the club actually uses day to day:** Option A on their server, which is exactly the
  "lift onto the LOFC server as one reproducible unit" the brief describes.
