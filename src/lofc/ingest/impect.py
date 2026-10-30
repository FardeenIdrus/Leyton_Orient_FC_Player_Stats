"""Pull player-season data from the Impect customer API.

Impect is the club's second event-data provider (and per the recruitment team the
intended future primary). This module lands one file per configured iteration
(an iteration = one league season) containing every player's season averages
across Impect's full KPI set, exactly as the API returns them. Nothing is
filtered here: curation to a modelling subset happens downstream, so the landed
file is the full-fidelity record.

Semantics that matter (verified empirically against known season totals):
  - The frame holds one row per player PER POSITION played, not one per player.
  - KPI columns are averages per full-match-equivalent. A season total is
    average * matchShare, summed over the player's position rows (e.g. Ballard,
    League One 25/26: 0.6131 * 37.52 = 23.00 goals, his real golden-boot total).

Idempotent: an iteration whose file exists is skipped; --force re-pulls.
Credentials come from IMPECT_USERNAME / IMPECT_PASSWORD in the environment
(.env), mirroring the StatsBomb setup. Rate limiting is handled by impectPy.

Run with:  python -m lofc.ingest.impect [--force] [--iteration N]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from lofc.config import ImpectTarget, settings
from lofc.ingest import landing
from lofc.ingest.retry import with_retries


def impect_root() -> Path:
    return landing.raw_root() / "impect"


def iterations_catalogue_path() -> Path:
    return impect_root() / "iterations.json"


def averages_path(iteration_id: int) -> Path:
    return impect_root() / f"player_iteration_averages_{iteration_id}.parquet"


def write_parquet(path: Path, frame: pd.DataFrame, force: bool = False) -> bool:
    """Write a frame as parquet. Return True if written, False if skipped.

    Temp-file + rename, like landing.write_json: an interrupted write can never
    leave a half-written file that the skip check mistakes for complete.
    """
    if landing.exists(path) and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)
    return True


def _token() -> str:
    """Authenticate against the Impect API, failing loudly if unconfigured."""
    if not settings.impect_authenticated:
        raise SystemExit(
            "Impect credentials missing: set IMPECT_USERNAME and IMPECT_PASSWORD "
            "in .env (containers read .env at start: `docker compose up -d`)."
        )
    import impectPy as ip
    return with_retries(
        lambda: ip.getAccessToken(settings.impect_username, settings.impect_password),
        what="Impect token")


def is_live(target: ImpectTarget) -> bool:
    """True if this target is the season currently being played (config.LIVE_SEASON_ID)."""
    return settings.live_season_id is not None and target.season_id == settings.live_season_id


FINISHED_REFRESH_DAYS = 30


def scores_path(iteration_id: int) -> Path:
    return impect_root() / f"player_iteration_scores_{iteration_id}.parquet"


def _pull(target: ImpectTarget, path: Path, fetch, what: str, force: bool = False) -> bool:
    """Land one iteration-level frame. Return True if pulled, False if skipped.

    Skip-if-exists is right for a FINISHED season (its data can never change), but wrong for
    the season being played: Impect returns season-to-date aggregates, so a landed file is
    stale as soon as the next round is played. The live season therefore always re-pulls --
    without this, the first in-season pull would silently be the only one.
    """
    live = is_live(target)
    # Live seasons always overwrite. Finished ones refresh monthly: Impect revises them
    # (National League 25/26: 34 players changed July -> October, median 0.3%).
    refresh = force or live or landing.older_than(path, FINISHED_REFRESH_DAYS)
    if landing.exists(path) and not refresh:
        return False

    try:
        frame = with_retries(fetch, what=f"Impect {what} [{target.label}]")
    except Exception as exc:
        # A live season configured before kick-off legitimately has nothing yet: skip it
        # quietly and try again next run. Any other failure -- and any failure on a season
        # that should already have data -- still raises loudly.
        if live and not landing.exists(path):
            print(f"  [{target.label}] no {what} yet (season not started): {exc}")
            return False
        raise

    if frame.empty:
        # A transient API hiccup must not land an empty file that a re-run
        # would then skip forever (the same guard the StatsBomb ingest has).
        if live and not landing.exists(path):
            print(f"  [{target.label}] no {what} yet (season not started); nothing landed")
            return False
        raise RuntimeError(f"Impect returned no {what} for {target.label} "
                           f"(iteration {target.iteration_id}); not persisting.")
    write_parquet(path, frame, force=refresh)
    return True


def pull_iteration(target: ImpectTarget, token: str, force: bool = False) -> bool:
    """Land one iteration's player averages (the scoring input)."""
    import impectPy as ip
    return _pull(target, averages_path(target.iteration_id),
                 lambda: ip.getPlayerIterationAverages(target.iteration_id, token),
                 "averages", force)


def pull_scores(target: ImpectTarget, token: str, force: bool = False) -> bool:
    """Land one iteration's Impect player scores (IMPECT, offensive, defensive, ...).
    Display only -- never read by scoring."""
    import impectPy as ip
    return _pull(target, scores_path(target.iteration_id),
                 lambda: ip.getPlayerIterationScores(target.iteration_id, token),
                 "scores", force)


def players_path(iteration_id: int) -> Path:
    return impect_root() / f"players_{iteration_id}.parquet"


def squad_names_path() -> Path:
    return impect_root() / "squad_names.json"


_API = "https://api.impect.com/v5/customerapi"


def _api_frame(path: str, token: str, endpoint: str) -> pd.DataFrame:
    """One Impect API list as a frame, through impectPy's rate-limited session."""
    from impectPy.helpers import ImpectSession, RateLimitedAPI
    conn = RateLimitedAPI(ImpectSession())
    conn.session.headers.update({"Authorization": f"Bearer {token}"})
    return conn.make_api_request_limited(url=f"{_API}{path}", method="GET") \
        .process_response(endpoint=endpoint)


def fetch_iteration_players(iteration_id: int, token: str) -> pd.DataFrame:
    """Impect's player list for one season: his id and `currentSquadId` -- the club he is at
    NOW, not the club of that season (verified for Eoin Kenny, 2026-10-30)."""
    frame = _api_frame(f"/iterations/{iteration_id}/players", token, "Players")
    return frame[["id", "currentSquadId"]]


def pull_players(target: ImpectTarget, token: str, force: bool = False) -> bool:
    """Land one season's player list (current clubs). Display only -- never scoring."""
    return _pull(target, players_path(target.iteration_id),
                 lambda: fetch_iteration_players(target.iteration_id, token), "players", force)


def fetch_squad_names(iteration_ids, token: str) -> dict[int, str]:
    """Club id -> Impect's club name, from every season the licence can see. Impect has no
    look-up of a single club, so a current club is named only if it plays in one of them.
    A season that fails is skipped: a missing name shows nothing, never a wrong one."""
    names: dict[int, str] = {}
    for it in iteration_ids:
        try:
            squads = _api_frame(f"/iterations/{int(it)}/squads", token, "Squads")
        except Exception as exc:                              # noqa: BLE001 -- see docstring
            print(f"  club names for iteration {it} skipped: {type(exc).__name__}")
            continue
        names.update({int(i): str(n) for i, n in zip(squads["id"], squads["name"])})
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-pull even if files exist")
    parser.add_argument("--iteration", type=int, default=None,
                        help="pull one iteration id only (must be a configured target)")
    args = parser.parse_args()

    token = _token()

    # Land the licence's iteration catalogue FIRST: the targets are derived from it
    # (lofc/leagues.py via settings.impect_targets), so a new season -- or a competition just
    # added to the registry -- is pulled on the run that first sees it, not a week later.
    import impectPy as ip
    catalogue = with_retries(lambda: ip.getIterations(token), what="Impect iteration catalogue")
    landing.write_json(iterations_catalogue_path(),
                       catalogue.to_dict(orient="records"), force=True)

    targets = settings.impect_targets
    if args.iteration is not None:
        targets = [t for t in targets if t.iteration_id == args.iteration]
        if not targets:
            raise SystemExit(f"iteration {args.iteration} is not a configured Impect target")

    from lofc.store import runs
    counts = {"pulled": 0, "skipped": 0}

    def one(target) -> int | None:
        rows = None
        if pull_iteration(target, token, force=args.force):
            counts["pulled"] += 1
            frame = pd.read_parquet(averages_path(target.iteration_id))
            rows = len(frame)
            print(f"  [{target.label}] pulled: {frame['playerId'].nunique()} players, "
                  f"{len(frame)} position rows, {len(frame.columns)} columns")
        else:
            counts["skipped"] += 1
            if not is_live(target):
                print(f"  [{target.label}] already present, skipped")
        if pull_scores(target, token, force=args.force):
            print(f"  [{target.label}] scores pulled")
        if pull_players(target, token, force=args.force):
            print(f"  [{target.label}] player list pulled (current clubs)")
        return rows

    # One league failing (e.g. Impect has no data for it) must not stop the others.
    failures = runs.for_each_league("Pull Impect", targets, label=lambda t: t.label,
                                    keys=lambda t: (t.competition_id, t.season_id), fn=one)
    pulled, skipped = counts["pulled"], counts["skipped"]
    live_ids = sorted({t.season_id for t in targets if is_live(t)})
    note = (f" | live season {settings.live_season_id} always re-pulled" if live_ids
            else " | no live season configured (all skip-if-exists)")
    print(f"Done: {pulled} pulled, {skipped} skipped "
          f"({len(targets)} iterations under {impect_root()}/){note}")
    # Club names for the current-club label, from every season the licence can see. A
    # failure here must not fail the pull: the last landed names stay in use.
    try:
        names = fetch_squad_names(catalogue["id"].tolist(), token)
        if names:
            landing.write_json(squad_names_path(), {str(k): v for k, v in names.items()},
                               force=True)
            print(f"  club names: {len(names):,}")
    except Exception as exc:                                  # noqa: BLE001
        print(f"  club names not refreshed: {type(exc).__name__}: {exc}")
    runs.finish_step("Pull Impect", failures)


if __name__ == "__main__":
    main()
