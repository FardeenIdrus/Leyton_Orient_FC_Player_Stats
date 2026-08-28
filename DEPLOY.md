# Deployment

The platform is one Docker stack, so deploying means running it on a machine that's online.
This covers two cases: a **permanent URL on a server** (Option A), and a **quick shareable link
from your laptop** for a demo (Option B).

---

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
The scoring data goes stale as the season progresses. `scripts/weekly_refresh.sh` wraps
`python -m lofc.pipeline` with a lock, timestamped/rotated logs, and success/failure markers
in `data/ops/` — written and tested, but **not installed anywhere** by default. Add it to the
server's crontab once the platform is actually live (see the "WEEKLY REFRESH, unattended"
section of `cli_commands.txt` for the exact line and what each safeguard does). Check
`data/ops/last_success` / `data/ops/last_failure` to see whether the last scheduled run
actually worked.

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
- **Backups:** the `pgdata` Docker volume holds everything. Snapshot it (or `pg_dump`) regularly.
- **Updates:** `git pull` then re-run step 3; the schema migrates via the pipeline's first step.
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
