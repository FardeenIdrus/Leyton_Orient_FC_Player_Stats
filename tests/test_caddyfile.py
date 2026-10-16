"""Our Caddy is the only thing on ports 80/443, so it also routes the colleague's platform
(owner, 2026-10-16). His container joins `lofc_default` with the fixed alias `match-analysis`
and serves on 5050; Caddy obtains and renews his HTTPS certificate like ours."""

from pathlib import Path

CADDYFILE = Path(__file__).resolve().parents[1] / "Caddyfile"


def _blocks():
    text = "\n".join(l for l in CADDYFILE.read_text().splitlines() if not l.strip().startswith("#"))
    return text


def test_our_site_is_unchanged():
    assert "{$DASHBOARD_DOMAIN} {\n\treverse_proxy dashboard:8501\n}" in _blocks()


def test_colleague_site_routes_to_his_alias_and_port():
    assert "orient-matchanalysis.duckdns.org {\n\treverse_proxy match-analysis:5050\n}" in _blocks()


def test_braces_balance():
    t = _blocks()
    assert t.count("{") == t.count("}")
