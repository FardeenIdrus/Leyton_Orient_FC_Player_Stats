# Deployment

The platform is one Docker stack, so deploying means running it on a machine that's online.
This covers two cases: a **permanent URL on a server** (Option A), and a **quick shareable link
from your laptop** for a demo (Option B).

---

## Option A — Permanent deployment on a server (a real URL)

You need: a Linux server/VM with Docker installed (the club's server, or a cloud VM such as
DigitalOcean, Hetzner or AWS — ~4-8 GB RAM is plenty), and a **domain name pointed at the
server's IP** (an A record). Caddy then issues HTTPS automatically.

The production stack (`docker-compose.prod.yml`) publishes **only the dashboard**, behind Caddy
with HTTPS and a login. The database, the app container and the admin tools (pgAdmin, Metabase)
are not exposed to the internet.

### Steps
1. **Put the code on the server** and `cd` into it:
   ```bash
   git clone <repo-url> && cd Leyton_Orient_FC_Player_Stats
   ```
2. **Create a dashboard password hash:**
   ```bash
   docker run --rm caddy:2.8-alpine caddy hash-password --plaintext 'choose-a-password'
   ```
   Copy the `$2a$...` hash it prints.
3. **Create `.env`** with production values:
   ```bash
   POSTGRES_USER=lofc
   POSTGRES_PASSWORD=a-strong-password-here
   POSTGRES_DB=lofc
   DATABASE_URL=postgresql+psycopg2://lofc:a-strong-password-here@db:5432/lofc
   # StatsBomb (leave blank for open data, or fill in for the paid API):
   USE_OPEN_DATA=true
   SB_USERNAME=
   SB_PASSWORD=
   # Public dashboard:
   DASHBOARD_DOMAIN=recruitment.yourclub.com
   DASHBOARD_USER=recruiter
   DASHBOARD_PASSWORD_HASH=$2a$...the hash from step 2...
   ```
4. **Start the stack** (builds the lean image, brings up db + app + dashboard + Caddy):
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
5. **Populate the database** (first run downloads data; ~20-40 min):
   ```bash
   docker compose -f docker-compose.prod.yml exec app python -m lofc.pipeline
   ```
6. **Open `https://recruitment.yourclub.com`**, log in — the dashboard is live, on any device.

### Notes
- **Admin tools** (pgAdmin/Metabase) aren't exposed publicly in prod. Reach them over an SSH
  tunnel, e.g. `ssh -L 3000:localhost:3000 user@server` then open `localhost:3000`. (Add them to
  the Caddyfile on their own subdomain if you want them public — each already has its own login.)
- **Backups:** the `pgdata` Docker volume holds everything. Snapshot it (or `pg_dump`) regularly.
- **Updates:** `git pull` then re-run step 4; the schema migrates via the pipeline's first step.

---

## Option B — Quick shareable link from your laptop (no server, for a demo)

Run the app locally as usual, then expose `localhost:8501` through a tunnel. The link works on
any device (phone, the interviewer's laptop) **while your machine is running it**.

```bash
docker compose up -d                 # the normal local stack
# (populate once if you haven't: docker compose exec app python -m lofc.pipeline)
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
