"""Who is on loan at each club, from whom, and until when.

The only source. Impect is an event-data provider: 25 API endpoints, none carrying
contracts, transfers or registration status. It can say a player turned out for two clubs
in one season -- 196 did in 25/26 -- but cannot tell a loan from a permanent transfer, and
misses a season-long loan completely.

Transfermarkt publishes a per-club loan page whose columns are exactly what recruitment
needs: Player, Age, Nat., On loan from, Loan ends. `Loan ends` is the January window's
whole point -- it separates a player going back to his parent club in the summer from one
who is actually available.

Rows are loans IN, read club by club. Across the leagues we cover that yields loans OUT by
inference: a player loaned from A to B appears on B's page naming A. A player loaned to a
league we do not scrape is not captured, and this module does not pretend otherwise.

Politeness: every fetch goes through transfermarkt_common (2.5s apart, browser UA,
backoff). 147 clubs is about six minutes.
"""

from __future__ import annotations

import argparse
import datetime
import re

import pandas as pd
from bs4 import BeautifulSoup

from lofc.config import settings
from lofc.ingest.transfermarkt_common import fetch
from lofc.ingest.transfermarkt_efl import LEAGUES, club_pages, current_tm_season

BASE = "https://www.transfermarkt.co.uk"

COLUMNS = ["player_name", "tm_player_id", "club_name", "parent_club",
           "competition_id", "season_id", "loan_ends"]


def loans_url(club_id: str | int, season: int) -> str:
    """The club's loan page. `x` is a slug placeholder Transfermarkt ignores."""
    return f"{BASE}/x/leihspielerhistorie/verein/{club_id}/saison_id/{season}"


def club_id_from_url(squad_url: str) -> str | None:
    """The numeric club id inside a squad-page URL."""
    if "/verein/" not in squad_url:
        return None
    return squad_url.split("/verein/")[1].split("/")[0]


def parse_loan_end(text: str) -> datetime.date | None:
    """Loan end dates appear as '31/05/2027', 'Jun 30, 2027' or '30.06.2027'."""
    if not text:
        return None
    text = text.strip()
    for fmt in ("%d/%m/%Y", "%b %d, %Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


_DATE = re.compile(r"^\d{1,2}[/.]\d{1,2}[/.]\d{4}$|^[A-Z][a-z]{2} \d{1,2}, \d{4}$")


def parse_loans(html: str, club_name: str, competition_id: int,
                season_id: int) -> list[dict]:
    """Every loan row on one club's loan page.

    Read by SEMANTIC ANCHOR, not by column index. The header row has 6 columns but each
    body row has 9 cells -- Transfermarkt renders the player as a nested construct that
    spans several -- so mapping header position to cell position silently picks the wrong
    field. It first gave every player's POSITION as his parent club.

    So each field is found by what it IS:
      player      the /profil/spieler/ link  (also yields the Transfermarkt id)
      parent club a /verein/ link's title    (the club is a crest, with no text at all)
      loan ends   the cell matching a date

    A row with no player link, or a table with no 'on loan from' header, yields nothing
    rather than a guess. Reading this page positionally is the same mistake that destroyed
    1,381 contract dates on 11 Aug 2026.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.items")
    if table is None:
        return []

    heads = [th.get_text(" ", strip=True).lower() for th in table.select("thead th")]
    if not any("on loan from" in h for h in heads):
        return []                      # not a loan table; refuse rather than guess

    out = []
    for row in table.select("tbody > tr"):
        cells = row.select("td")
        if not cells:
            continue
        player = row.select_one("a[href*='/profil/spieler/']")
        if player is None:
            continue
        tm_id = re.search(r"/spieler/(\d+)", player.get("href", ""))

        parent = None
        for a in row.select("a[href*='/verein/']"):
            title = (a.get("title") or "").strip()
            if title:
                parent = title
                break

        ends = None
        for td in cells:
            text = td.get_text(" ", strip=True)
            if _DATE.match(text):
                ends = parse_loan_end(text)
                break

        out.append({"player_name": player.get_text(strip=True),
                    "tm_player_id": int(tm_id.group(1)) if tm_id else None,
                    "club_name": club_name, "parent_club": parent,
                    "competition_id": competition_id, "season_id": season_id,
                    "loan_ends": ends})
    return out


# Transfermarkt marks a loan on the SQUAD page, inside the player cell's club link:
#   title="On loan from Ipswich Town until 31/05/2027"
_ON_LOAN = re.compile(r"on loan from\s+(.+?)(?:\s+until\s+(\d{1,2}[/.]\d{1,2}[/.]\d{4}))?$",
                      re.IGNORECASE)


def parse_squad_loans(html: str, club_name: str, competition_id: int,
                      season_id: int) -> list[dict]:
    """Loans read from the SQUAD page rather than the dedicated loans page.

    The loans page (`leihspielerhistorie`) is INCOMPLETE: for Leyton Orient it listed four
    loanees and omitted Somto Boniface, who is on loan from Ipswich Town until 31 May 2027
    and marked as such on the squad page. Reading the squad page instead is both more
    complete and cheaper -- that page is already fetched for every club to get contracts.

    The marker is a title attribute on a club link inside the player cell, so it is read by
    matching the phrase, never by cell position.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.items")
    if table is None:
        return []
    out = []
    for row in table.select("tbody > tr"):
        player = row.select_one("a[href*='/profil/spieler/']")
        if player is None:
            continue
        parent = ends = None
        for a in row.select("a[title]"):
            m = _ON_LOAN.search((a.get("title") or "").strip())
            if m:
                parent = m.group(1).strip()
                ends = parse_loan_end(m.group(2) or "")
                break
        if parent is None:
            continue
        tm_id = re.search(r"/spieler/(\d+)", player.get("href", ""))
        out.append({"player_name": player.get_text(strip=True),
                    "tm_player_id": int(tm_id.group(1)) if tm_id else None,
                    "club_name": club_name, "parent_club": parent,
                    "competition_id": competition_id, "season_id": season_id,
                    "loan_ends": ends})
    return out


def scrape_all(season: int | None = None) -> pd.DataFrame:
    """Every loan at every club in every configured league. About six minutes."""
    season = season or current_tm_season()
    rows: list[dict] = []
    for league_code, (slug, competition_id) in LEAGUES.items():
        clubs = club_pages(slug, league_code, season)
        print(f"[{league_code}] {len(clubs)} clubs")
        for i, (club_name, squad_url) in enumerate(clubs, start=1):
            club_id = club_id_from_url(squad_url)
            if club_id is None:
                print(f"  [{league_code}] {i}/{len(clubs)} {club_name}: no club id in URL")
                continue
            try:
                # BOTH pages. The squad page is the more complete of the two (the loans
                # page omitted Somto Boniface at Leyton Orient), but the loans page carries
                # a few the squad page does not mark, so they are unioned and de-duplicated
                # on the player. The squad page wins a tie: it is the one that names the
                # parent club and the end date together.
                found = parse_squad_loans(fetch(squad_url), club_name,
                                          competition_id, season)
                seen = {r["tm_player_id"] for r in found if r["tm_player_id"]}
                for extra in parse_loans(fetch(loans_url(club_id, season)), club_name,
                                         competition_id, season):
                    if extra["tm_player_id"] not in seen:
                        found.append(extra)
            except Exception as exc:                       # one club must not kill the run
                print(f"  [{league_code}] {i}/{len(clubs)} {club_name}: FAILED {exc}")
                continue
            rows.extend(found)
            print(f"  [{league_code}] {i}/{len(clubs)} {club_name}: {len(found)} on loan")
    return pd.DataFrame(rows, columns=COLUMNS)


def csv_path():
    """The file the server loads (`lofc.store.loans`), next to the squads file, so the
    documented `rsync data/reference/transfermarkt/` carries it."""
    from pathlib import Path
    return Path(settings.reference_data_dir) / "transfermarkt" / "loans.csv"


def write_csv(frame: pd.DataFrame, season_id: int, when: datetime.datetime,
              path=None) -> None:
    """The scrape as a file, stamped with OUR season id and the scrape time. Atomic: an
    interrupted run never leaves a half-file for the server to load."""
    from pathlib import Path
    path = Path(path) if path is not None else csv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    out = frame[COLUMNS].assign(season_id=int(season_id),
                                scraped_at=when.replace(microsecond=0).isoformat())
    tmp = path.with_suffix(".csv.tmp")
    out.to_csv(tmp, index=False)
    tmp.rename(path)


def load(engine, frame: pd.DataFrame, season_id: int,
         scraped_at: datetime.datetime | None = None) -> int:
    """Clear-then-insert one season, then link to our players via tm_player_id.

    Clear-then-insert because the page is a CURRENT snapshot: a loan that ended is gone
    from the source, and carrying a stale row forward would tell a recruiter someone is
    still on loan when he is back at his parent club.
    """
    from sqlalchemy import text
    if frame.empty:
        print("no loan rows scraped; leaving the table untouched")
        return 0
    # Stamp OUR season_id over Transfermarkt's. scrape_all works in TM season numbers
    # (2026), the platform in its own (319). Without this the DELETE cleared 319 while the
    # INSERT wrote 2026, so the delete never matched and the insert collided with the
    # previous run on uq_player_loan -- the whole load rolled back and stale rows survived.
    frame = frame[COLUMNS].assign(season_id=season_id,
                                  scraped_at=scraped_at or datetime.datetime.now())
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM player_loans WHERE season_id = :s"), {"s": season_id})
        frame.to_sql("player_loans", conn, if_exists="append", index=False)
        # Link to our identities. Left unlinked where we do not hold the player: a loan we
        # cannot match is still a true fact about the club, and dropping it would hide it.
        # Correlated subquery rather than UPDATE..FROM: the latter is Postgres-only and
        # the tests run this against SQLite.
        linked = conn.execute(text(
            "UPDATE player_loans SET player_id = ("
            "  SELECT p.player_id FROM players p "
            "  WHERE p.tm_player_id = player_loans.tm_player_id LIMIT 1) "
            "WHERE season_id = :s AND player_id IS NULL "
            "AND EXISTS (SELECT 1 FROM players p2 "
            "            WHERE p2.tm_player_id = player_loans.tm_player_id)"),
            {"s": season_id}).rowcount
    print(f"player_loans: {len(frame)} rows for season {season_id}; {linked} linked to a player")
    return len(frame)


def resolve_season_id(explicit: int | None, tm_season: int,
                      live_season_id: int | None) -> int:
    """OUR season id to stamp these loans with.

    `scrape_all` works in TRANSFERMARKT season numbers (2026); the platform works in its own
    (319). This must return the platform's, or the rows land under a key nothing reads: run
    with no arguments, the default used to fall back to `tm_season`, writing 411 loans under
    season_id 2026 while every reader filters on 319. Three runs looked like silent failures.

    Refuses rather than guessing when no live season is configured -- writing under a guessed
    key is exactly how this happened.
    """
    if explicit is not None:
        return int(explicit)
    if live_season_id is None:
        raise ValueError(
            "No LIVE_SEASON_ID configured, so there is no season to stamp these loans with. "
            "Pass --season-id explicitly (the platform's id, e.g. 319 -- NOT the Transfermarkt "
            f"season {tm_season}).")
    return int(live_season_id)


def main() -> None:
    from lofc.store.load import get_engine
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=None,
                        help="Transfermarkt season id (default: the current one)")
    parser.add_argument("--season-id", type=int, default=None,
                        help="our season_id to store against (default: same as --season)")
    args = parser.parse_args()
    season = args.season or current_tm_season()
    frame = scrape_all(season)
    season_id = resolve_season_id(args.season_id, season, settings.live_season_id)
    when = datetime.datetime.now()
    # The file is what reaches the server (rsync, then `python -m lofc.store.loans`); the
    # database load is this machine's own copy.
    if not frame.empty:
        write_csv(frame, season_id, when)
        print(f"Wrote {len(frame)} loans to {csv_path()}")
    load(get_engine(), frame, season_id, scraped_at=when)


if __name__ == "__main__":
    main()
