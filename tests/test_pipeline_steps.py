"""With `impect_only`, the pipeline must not run the StatsBomb stages at all.

Three stages exist only to rebuild `player_season_metrics` from 21 GB of raw StatsBomb
events: the ingest, the aggregation, and the load that writes the result to Postgres. Under
`impect_only` every league -- the EFL included -- is built from Impect instead
(`build_neutral`: "so StatsBomb is not needed at all"), and all 40 metrics the composite uses
come from Impect and SkillCorner. The stages are vestigial.

They were invisible locally, because the raw files are already on disk and the ingest is
skip-if-exists. On a machine without them they would attempt ~8,900 paid StatsBomb API calls
for 4,456 matches, and the pipeline halts at the aggregation if they are absent -- so no
Impect pull, no scrape and no scorecard rebuild would run on a fresh server.
"""

import pytest

from lofc.pipeline import build_steps

SB_INGEST = "lofc.ingest.run"
SB_AGGREGATE = "lofc.aggregate.run"
SB_LOAD = "lofc.store.load"


def _modules(steps):
    """The -m module of every step, so assertions read against what actually runs."""
    out = []
    for _label, command in steps:
        if "-m" in command:
            out.append(command[command.index("-m") + 1])
    return out


@pytest.fixture
def impect_only(monkeypatch):
    from lofc import config
    monkeypatch.setattr(config.settings, "impect_only", True, raising=False)
    return config.settings


@pytest.fixture
def statsbomb_era(monkeypatch):
    from lofc import config
    monkeypatch.setattr(config.settings, "impect_only", False, raising=False)
    return config.settings


def test_the_statsbomb_stages_are_skipped(impect_only):
    modules = _modules(build_steps())
    for module in (SB_INGEST, SB_AGGREGATE, SB_LOAD):
        assert module not in modules, f"{module} still runs under impect_only"


def test_the_work_that_matters_still_runs(impect_only):
    """Skipping StatsBomb must not skip the pipeline's actual job."""
    modules = _modules(build_steps())
    for module in ("lofc.model.build_neutral", "lofc.model.scorecard_run",
                   "lofc.constrain.run"):
        assert module in modules, f"{module} was dropped"


def test_migrations_still_run(impect_only):
    """The server applies the schema on every deploy; this must never be skipped."""
    assert any("alembic" in command for _label, command in build_steps())


def test_the_statsbomb_era_is_unchanged(statsbomb_era):
    """A database still spined on StatsBomb must behave exactly as before."""
    modules = _modules(build_steps())
    for module in (SB_INGEST, SB_AGGREGATE, SB_LOAD):
        assert module in modules, f"{module} was dropped from the StatsBomb path"


# --- the Transfermarkt scrape cannot run from a datacentre IP --------------------------
#
# Confirmed on the DigitalOcean droplet, 2026-09-12: Transfermarkt sits behind AWS WAF Bot
# Control and answers a server IP with HTTP 202 and a JavaScript challenge page
# (`awsWafCookieDomainList`, `gokuProps`) instead of content. The same request from a home
# connection returns the real page. Passing the challenge would mean executing their JS to
# mint a WAF token -- deliberate circumvention of bot protection, which this project does not
# do. So the SCRAPE stages run on a workstation and the server consumes what they produce.

SKIP_ENV = "skip_transfermarkt_scrape"
TM_SQUADS = "lofc.ingest.transfermarkt_efl"
TM_LOANS = "lofc.ingest.transfermarkt_loans"
SQUAD_LOADER = "lofc.store.squads"
INJURY_LOADER = "lofc.store.injuries"


@pytest.fixture
def no_scraping(monkeypatch):
    from lofc import config
    monkeypatch.setattr(config.settings, "impect_only", True, raising=False)
    monkeypatch.setattr(config.settings, SKIP_ENV, True, raising=False)
    return config.settings


def test_the_transfermarkt_scrapes_are_skipped(no_scraping):
    modules = _modules(build_steps())
    assert TM_SQUADS not in modules
    assert TM_LOANS not in modules


def test_the_loaders_that_read_those_files_still_run(no_scraping):
    """The server must still INGEST Transfermarkt data pushed from a workstation -- it just
    cannot fetch it itself. Skipping the loaders too would silently freeze contracts, loans
    and injuries at whatever the last dump held."""
    modules = _modules(build_steps())
    assert SQUAD_LOADER in modules
    assert INJURY_LOADER in modules


def test_scraping_still_runs_by_default(impect_only):
    """A workstation must be unaffected: the flag is opt-in, set only on the server."""
    modules = _modules(build_steps())
    assert TM_SQUADS in modules
    assert TM_LOANS in modules
