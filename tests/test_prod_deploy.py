"""Production set-up for the new web front end (owner 2026-11-09): two web containers
(blue/green) so a deploy never serves a cold one; Caddy's main domain follows the active one
(an imported upstream file), the old Streamlit dashboard stays on a second domain as a fallback;
deploy.sh builds first and switches only once the new container is warm (scripts/web_switch.sh)."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
yaml = pytest.importorskip("yaml")


def _compose():
    return yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text())


@pytest.mark.parametrize("name", ["web-blue", "web-green"])
def test_web_containers_run_production_uvicorn(name):
    svc = _compose()["services"][name]
    cmd = svc["command"]
    assert cmd[:2] == ["uvicorn", "lofc.web.app:app"]
    assert "--reload" not in cmd and cmd[cmd.index("--workers") + 1] == "1"
    assert "--proxy-headers" in cmd and cmd[cmd.index("--port") + 1] == "8600"
    assert svc["mem_limit"] and float(str(svc["cpus"])) <= 2.0
    assert "ports" not in svc                      # only Caddy is public
    assert "/readyz" in " ".join(svc["healthcheck"]["test"])
    assert any(v.endswith(":/app/data:ro") for v in svc["volumes"])
    assert any(v.startswith("./secrets:/app/secrets:ro") for v in svc["volumes"])
    assert svc["restart"] == "unless-stopped"


def test_caddy_reads_the_upstream_file_and_the_fallback_domain():
    caddy = _compose()["services"]["caddy"]
    assert "./caddy:/etc/caddy/site:ro" in caddy["volumes"]
    env = caddy["environment"]
    assert "OLD_DASHBOARD_DOMAIN" in env and "DASHBOARD_DOMAIN" in env


def test_caddyfile_routes_main_domain_to_web_and_old_domain_to_streamlit():
    from test_caddyfile import _blocks
    t = _blocks()
    assert "{$DASHBOARD_DOMAIN} {\n\timport /etc/caddy/site/web_upstream.caddy\n}" in t
    assert "{$OLD_DASHBOARD_DOMAIN} {\n\treverse_proxy dashboard:8501\n}" in t


def test_upstream_file_is_not_committed():
    assert "caddy/web_upstream.caddy" in (ROOT / ".gitignore").read_text()


def test_deploy_builds_first_then_switches_and_never_recreates_both_web_containers():
    text = (ROOT / "scripts" / "deploy.sh").read_text()
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    assert "build" in body and "web_switch.sh" in body
    assert body.index(" build") < body.index("web_switch.sh")
    assert "up -d --build\n" not in body             # would recreate the serving container cold
    assert "alembic upgrade head" in body


def test_deploy_restarts_itself_when_the_pull_changed_it():
    """Owner, 2026-11-10: the first deploy of the new site ran the OLD deploy.sh to the end
    (bash keeps reading the file it started, even after git pull replaces it), so Caddy was
    started without its upstream file and every domain went down. After pulling, a changed
    deploy.sh must re-run itself -- once (guard variable) -- before building anything."""
    text = (ROOT / "scripts" / "deploy.sh").read_text()
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    assert "LOFC_DEPLOY_REEXEC" in body
    assert 'git diff --quiet "$before" "$after" -- scripts/deploy.sh' in body
    assert 'LOFC_DEPLOY_REEXEC=1 exec "$REPO_ROOT/scripts/deploy.sh"' in body
    assert body.index("git pull --ff-only") < body.index("LOFC_DEPLOY_REEXEC") < body.index(" build")


@pytest.mark.skipif(not (ROOT / "scripts" / "test_web_switch.sh").exists(), reason="scripts/ not mounted")
def test_switch_script_behaviour():
    r = subprocess.run(["bash", str(ROOT / "scripts" / "test_web_switch.sh")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
