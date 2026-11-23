"""Production set-up for the new web front end (owner 2026-11-09): two web containers
(blue/green) so a deploy never serves a cold one; Caddy's main domain follows the active one
(an imported upstream file); the old Streamlit dashboard was retired on 2026-11-23 (owner);
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


def test_caddy_reads_the_upstream_file_and_no_fallback_domain():
    """Owner 2026-11-23: the old Streamlit site is retired -- no fallback domain, no service."""
    compose = _compose()
    caddy = compose["services"]["caddy"]
    assert "./caddy:/etc/caddy/site:ro" in caddy["volumes"]
    env = caddy["environment"]
    assert "DASHBOARD_DOMAIN" in env and "OLD_DASHBOARD_DOMAIN" not in env
    assert "dashboard" not in compose["services"] and "depends_on" not in caddy


def test_caddyfile_routes_main_domain_to_web_and_has_no_streamlit():
    from test_caddyfile import _blocks
    t = _blocks()
    assert "{$DASHBOARD_DOMAIN} {\n\timport /etc/caddy/site/web_upstream.caddy\n}" in t
    assert "OLD_DASHBOARD_DOMAIN" not in t and "dashboard:8501" not in t


def test_deploy_no_longer_starts_the_streamlit_dashboard():
    text = (ROOT / "scripts" / "deploy.sh").read_text()
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    assert "up -d db app caddy" in body and "dashboard" not in body
    assert 'echo "reverse_proxy web-blue:8600"' in body


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


def _deploy_env(tmp_path):
    """A throwaway server: a bare origin, a clone holding the real deploy.sh, a stub `docker`
    that only logs its calls and a stub web_switch.sh."""
    import os
    real = (ROOT / "scripts" / "deploy.sh").read_text()
    origin, work, srv = tmp_path / "origin.git", tmp_path / "work", tmp_path / "srv"
    git = lambda *a, cwd: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("clone", "-q", str(origin), str(work), cwd=tmp_path)
    (work / "scripts").mkdir()
    (work / "scripts" / "deploy.sh").write_text(real)
    (work / "scripts" / "web_switch.sh").write_text("#!/usr/bin/env bash\necho switched >> \"$LOG\"\n")
    for f in ("deploy.sh", "web_switch.sh"):
        (work / "scripts" / f).chmod(0o755)
    (work / ".gitignore").write_text("caddy/\n.deployed_commit\n")
    for a in (("add", "-A"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one"), ("push", "-q", "origin", "main")):
        git(*a, cwd=work)
    git("clone", "-q", str(origin), str(srv), cwd=tmp_path)
    bin_ = tmp_path / "bin"; bin_.mkdir()
    (bin_ / "docker").write_text("#!/usr/bin/env bash\necho \"docker $*\" >> \"$LOG\"\n"); (bin_ / "docker").chmod(0o755)
    log = tmp_path / "log"
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "LOG": str(log),
           "LOFC_REPO_ROOT": str(srv), "LOFC_COMPOSE_FILE": "x.yml"}

    def run(*args):
        log.write_text("")
        r = subprocess.run(["bash", str(srv / "scripts" / "deploy.sh"), *args], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        return "build" in log.read_text().split(), r.stdout

    def push(name, change_script=False):
        if change_script:
            s = work / "scripts" / "deploy.sh"; s.write_text(s.read_text() + "\n# changed\n")
        (work / name).write_text(name)
        for a in (("add", "-A"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", name), ("push", "-q", "origin", "main")):
            git(*a, cwd=work)
    return run, push, srv


@pytest.mark.skipif(__import__("shutil").which("git") is None, reason="needs git (run on the Mac)")
def test_deploy_skips_only_when_the_running_build_is_current(tmp_path):
    """Owner 2026-11-23 (N20): the skip compares HEAD with the commit that was last DEPLOYED in
    full, not with what `git pull` found -- the code on disk being current does not mean the
    site is (the live chart fix sat on disk unbuilt)."""
    run, push, srv = _deploy_env(tmp_path)
    built, _ = run()                                       # never deployed: builds
    assert built and (srv / ".deployed_commit").exists()
    built, out = run()                                     # nothing new: stops at once
    assert not built and "nothing new" in out
    push("a.txt")
    subprocess.run(["git", "pull", "-q", "--ff-only"], cwd=srv, check=True, capture_output=True)
    built, _ = run()                                       # pulled by hand, never built: builds
    assert built
    built, _ = run("--force")                              # --force always builds
    assert built


@pytest.mark.skipif(__import__("shutil").which("git") is None, reason="needs git (run on the Mac)")
def test_deploy_builds_when_it_restarts_itself(tmp_path):
    """A pull that changes deploy.sh re-runs the new script; that re-run must still build."""
    run, push, srv = _deploy_env(tmp_path)
    run()
    push("b.txt", change_script=True)
    built, out = run()
    assert built and "restarting with the new version" in out
