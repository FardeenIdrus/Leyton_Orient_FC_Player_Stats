"""The league registry: one line per COMPETITION; seasons, ids and names derived from it.

Before (to 2026-10-26) every league-season was typed out by hand in config.py -- 21 entries,
each with a hand-picked id -- and league names and season labels were repeated in four more
modules. Adding 25+ competitions that way meant ~75 hand-typed entries and many places to
miss. Here:

  * a competition is ONE `Competition` line (its name, Impect's competition id, our id);
  * its seasons come from Impect's own licence catalogue (`getIterations`), so a new season
    -- or a newly licensed competition once listed here -- needs no other code change;
  * season ids follow one rule (2024/25 = 317, +1 a year) and new competition ids another
    (NEW_ID_BASE + Impect's competition id);
  * names and season labels are read from here by the pipeline, the dashboard and the report.

The seven competitions that existed before keep their ids (the EFL's are the old StatsBomb
ids, the Impect-only leagues the hand-minted 900s), so no stored row changes:
tests/test_leagues.py reproduces the previous 21 targets exactly.

Pure: no database, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# Season ids keep the convention the database already uses: 317 = 2024/25 (inherited from the
# StatsBomb era), one more per season after it.
SEASON_ID_2024 = 317
# Only seasons from here on are ingested. Impect's catalogue reaches back to 2018/19 for some
# competitions; pulling all of it would multiply storage for seasons nobody scouts from.
FIRST_SEASON_ID = 317
# Ids for competitions added from 2026-10-26 on: NEW_ID_BASE + Impect's competition id. Clear of
# every id in use (3, 4, 5, 65, 901-903) and stable, because Impect's id never changes.
NEW_ID_BASE = 10_000

_SPLIT_SEASON = re.compile(r"^(\d{2})/(\d{2})$")
_CALENDAR_SEASON = re.compile(r"^(20\d{2})$")


def season_id_for(label: str) -> int:
    """Our season id for an Impect season label: "25/26" -> 318.

    A calendar-year season ("2025": Scandinavia, Ireland, Japan, Korea, USA) files under the
    season STARTING that year (owner, 2026-10-26): "2026" -> 2026/27 (319). The 2026 season is
    being played now, so it lines up with the live season, and Japan's switch from "2025" to
    "26/27" stays consistent. Anything else is refused."""
    cal = _CALENDAR_SEASON.match(str(label).strip())
    if cal:
        return SEASON_ID_2024 + (int(cal.group(1)) - 2024)
    m = _SPLIT_SEASON.match(str(label).strip())
    if not m or (int(m.group(1)) + 1) % 100 != int(m.group(2)):
        raise ValueError(f"Season {label!r} is neither 'YY/YY' nor 'YYYY'; add a rule for it "
                         f"in lofc/leagues.py before ingesting this competition.")
    return SEASON_ID_2024 + (2000 + int(m.group(1)) - 2024)


def season_midpoint(season_id: int):
    """1 January of the season's second year -- the date a finished season's ages are
    measured at (2025/26 -> 2026-01-01)."""
    import pandas as pd
    return pd.Timestamp(f"{2024 + int(season_id) - SEASON_ID_2024 + 1}-01-01")


def is_season_id(season_id) -> bool:
    """True for an id the rule maps to a real season (starting 2000-2099)."""
    try:
        return 2000 <= 2024 + int(season_id) - SEASON_ID_2024 <= 2099
    except (TypeError, ValueError):
        return False


def season_label(season_id: int, short: bool = False) -> str:
    """'2025/26' (or '25/26' with short=True) for a season id."""
    start = 2024 + int(season_id) - SEASON_ID_2024
    return f"{start % 100:02d}/{(start + 1) % 100:02d}" if short else f"{start}/{(start + 1) % 100:02d}"


@dataclass(frozen=True)
class Competition:
    """One competition we ingest.

    statsbomb_seasons: the seasons whose player identity comes from the legacy StatsBomb-era
    table (the four EFL leagues, 2024/25 and 2025/26 only). Every other season of every
    competition takes its identity from Impect.
    """
    name: str
    impect_competition_id: int
    competition_id: int
    statsbomb_seasons: frozenset[int] = field(default_factory=frozenset)
    include: bool = True


_EFL_SB = frozenset({317, 318})

LEAGUES: list[Competition] = [
    Competition("Championship", 41, 3, _EFL_SB),
    Competition("League One", 133, 4, _EFL_SB),
    Competition("League Two", 180, 5, _EFL_SB),
    Competition("National League", 341, 65, _EFL_SB),
    Competition("Scottish Premiership", 35, 901),
    Competition("Scottish Championship", 281, 902),
    Competition("Premier League 2", 52, 903),
    # Added 2026-10-26 (licence upgrade; ids by rule). Names are Impect's, with the country
    # where the name does not say it. Impect data only: no SkillCorner or Transfermarkt yet,
    # so these are rated on Performance alone, with no contracts or market values.
    # The EFL Cup is licensed but left out: a cup gives too few minutes for a rating.
    Competition("A-League Men (Australia)", 348, NEW_ID_BASE + 348),
    Competition("Challenger Pro League (Belgium)", 239, NEW_ID_BASE + 239),
    Competition("Fortuna Liga (Czechia)", 91, NEW_ID_BASE + 91),
    Competition("Superligaen (Denmark)", 15, NEW_ID_BASE + 15),
    Competition("Ligue 2 (France)", 66, NEW_ID_BASE + 66),
    Competition("Ligue 3 (France)", 439, NEW_ID_BASE + 439),
    Competition("Nemzeti Bajnokság (Hungary)", 233, NEW_ID_BASE + 233),
    Competition("NIFL Premiership (Northern Ireland)", 305, NEW_ID_BASE + 305),
    Competition("Niké Liga (Slovakia)", 93, NEW_ID_BASE + 93),
    Competition("South African Premier Division", 168, NEW_ID_BASE + 168),
    Competition("Veikkausliiga (Finland)", 243, NEW_ID_BASE + 243),
    Competition("Irish Premier Division", 189, NEW_ID_BASE + 189),
    Competition("J1 League (Japan)", 97, NEW_ID_BASE + 97),
    Competition("J2 League (Japan)", 262, NEW_ID_BASE + 262),
    Competition("K League 1 (South Korea)", 96, NEW_ID_BASE + 96),
    Competition("Eliteserien (Norway)", 62, NEW_ID_BASE + 62),
    Competition("Allsvenskan (Sweden)", 47, NEW_ID_BASE + 47),
    Competition("USL Championship (USA)", 56, NEW_ID_BASE + 56),
]


def new_competition_id(impect_competition_id: int) -> int:
    """Our id for a competition added from 2026-10-26 on."""
    return NEW_ID_BASE + int(impect_competition_id)


def league_name(competition_id: int, leagues: list[Competition] | None = None) -> str:
    for c in leagues or LEAGUES:
        if c.competition_id == int(competition_id):
            return c.name
    return f"Competition {int(competition_id)}"


def league_names(leagues: list[Competition] | None = None) -> dict[int, str]:
    return {c.competition_id: c.name for c in leagues or LEAGUES}


def targets_from_catalogue(catalogue: list[dict], leagues: list[Competition] | None = None,
                           first_season_id: int = FIRST_SEASON_ID) -> list[ImpectTarget]:
    """The Impect iterations to ingest: every catalogue entry of an INCLUDED registry
    competition, from `first_season_id` on. Entries of other competitions are ignored."""
    from lofc.config import ImpectTarget          # here, so config can import this module
    by_impect = {c.impect_competition_id: c for c in (leagues or LEAGUES) if c.include}
    targets = []
    for row in catalogue:
        comp = by_impect.get(int(row["competitionId"]))
        if comp is None:
            continue
        try:
            sid = season_id_for(row["season"])
        except ValueError as exc:
            # One competition's unusual season label must not stop every other league's
            # run: skip it, loudly. (Calendar-year seasons need an agreed rule first.)
            print(f"  [catalogue] skipped {comp.name} {row['season']!r} "
                  f"(iteration {row['id']}): {exc}")
            continue
        if sid < first_season_id:
            continue
        label = f"{comp.name} {season_label(sid)}"
        if sid in comp.statsbomb_seasons:
            targets.append(ImpectTarget(iteration_id=int(row["id"]), label=label,
                                        sb_competition_id=comp.competition_id,
                                        sb_season_id=sid))
        else:
            targets.append(ImpectTarget(iteration_id=int(row["id"]), label=label,
                                        competition_id=comp.competition_id, season_id=sid,
                                        spine_source="impect"))
    # Two iterations of one competition landing on one season (a calendar "2026" beside a split
    # "26/27") would write two leagues' worth of rows under one key: keep the newer iteration.
    chosen: dict[tuple[int, int], ImpectTarget] = {}
    for t in targets:
        key = (t.competition_id, t.season_id)
        if key in chosen:
            keep, drop = sorted([chosen[key], t], key=lambda x: x.iteration_id, reverse=True)
            print(f"  [catalogue] {keep.label}: two iterations ({drop.iteration_id}, "
                  f"{keep.iteration_id}) map to one season; keeping {keep.iteration_id}")
            chosen[key] = keep
        else:
            chosen[key] = t
    return sorted(chosen.values(), key=lambda t: (t.season_id, t.competition_id))
