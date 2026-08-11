"""Pull current Transfermarkt market values for the EFL target leagues.

The maintained dcaribou dataset (lofc.ingest.transfermarkt) covers first divisions
only, so for the Championship, League One, League Two and the National League we
read the club squad pages directly: one page per league plus one per club, about
100 requests in total, rate-limited to one request every 2.5 seconds.

Values are the current snapshot, so they are era-matched to the current season and
only that season's metrics should train the valuation model.

Output: data/reference/transfermarkt/efl_values.csv with one row per player
(league, club, Transfermarkt id, name, date of birth, position, market value).
Idempotent: skipped when the output exists, --force re-pulls.

Three safeguards exist because a stale season constant once produced a silent
data loss (11 Aug 2026: 4,014 rows written with zero contract dates, which then
nulled 1,381 stored contract dates downstream):
  - the season is DERIVED from today's date, never frozen (--season to pin it);
  - every field is read by COLUMN HEADER NAME, and a missing required header
    raises rather than silently yielding blanks;
  - a pull that loses a field aborts before the CSV is written (--allow-degraded
    to override deliberately), and the previous CSV is backed up on success.

Run with:  python -m lofc.ingest.transfermarkt_efl
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

from lofc.config import settings
from lofc.ingest.transfermarkt_common import fetch as _fetch

BASE = "https://www.transfermarkt.com"
# TM league code -> (URL slug, our StatsBomb competition_id).
LEAGUES = {
    "GB2": ("championship", 3),
    "GB3": ("league-one", 4),
    "GB4": ("league-two", 5),
    "CNAT": ("national-league", 65),
}
# Squad-page columns we must find by name. Transfermarkt drops `Contract` (and adds
# `Current club`) once a season has ended, so its absence means we are on the wrong
# season or the layout has changed -- either way, stop rather than write blanks.
REQUIRED_HEADERS = ("Player", "Date of birth/Age", "Height", "Foot", "Contract",
                    "Market value")
# Bio fields whose fill rate is checked before the CSV is written, and the floor.
GUARDED_FIELDS = ("contract_until", "height_cm", "foot")
MIN_FILL_RATE = 0.20
# A pull must also be big enough: every configured league has to return at least one
# club, and the row count has to stay within this fraction of the CSV being replaced.
# Squads churn between runs, so the floor is loose enough not to cry wolf.
MIN_ROW_RATIO = 0.70


def current_tm_season(today: date | None = None) -> int:
    """The Transfermarkt season id for `today` (default: now).

    Transfermarkt labels a season by its starting year and English seasons start in
    August, so 2026 means 2026/27 and runs from July 2026 to June 2027.
    """
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def parse_value(text: str) -> float | None:
    """'€1.50m' -> 1_500_000, '€900k' -> 900_000, '-' -> None."""
    text = text.strip().replace("€", "").lower()
    match = re.fullmatch(r"([\d.]+)\s*(m|k)?", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    return number * (1_000_000 if unit == "m" else 1_000 if unit == "k" else 1)


def parse_height_cm(text: str) -> int | None:
    """'1,91m' -> 191, '1.85 m' -> 185, '-' -> None."""
    match = re.search(r"(\d)[,.](\d{2})\s*m", text)
    return int(match.group(1) + match.group(2)) if match else None


def parse_foot(text: str) -> str | None:
    """Transfermarkt foot cell: 'left' / 'right' / 'both', anything else -> None."""
    text = text.strip().lower()
    return text if text in ("left", "right", "both") else None


def parse_birth_date(text: str) -> str | None:
    """'17/05/2003 (23)' or 'May 17, 2003 (23)' -> '2003-05-17'.

    Transfermarkt serves either format depending on locale negotiation.
    """
    numeric = re.search(r"(\d{2}/\d{2}/\d{4})", text)
    if numeric:
        return datetime.strptime(numeric.group(1), "%d/%m/%Y").date().isoformat()
    text_form = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", text)
    if text_form:
        return datetime.strptime(text_form.group(1), "%b %d, %Y").date().isoformat()
    return None


def club_pages(league_slug: str, league_code: str, season: int) -> list[tuple[str, str]]:
    """(club name, squad page URL) for every club in the league season."""
    url = f"{BASE}/{league_slug}/startseite/wettbewerb/{league_code}/saison_id/{season}"
    soup = BeautifulSoup(_fetch(url), "lxml")
    clubs: dict[str, tuple[str, str]] = {}
    for a in soup.select("td.hauptlink a[href*='/startseite/verein/']"):
        href = a["href"].split("?")[0]
        name = a.get_text(strip=True)
        if name and href not in clubs:
            # The detailed squad view (kader, plus=1) carries height, foot and the
            # contract date on top of the basic page's name/DOB/value.
            base = href.split("/saison_id")[0].replace("/startseite/", "/kader/")
            clubs[href] = (name, f"{BASE}{base}/saison_id/{season}/plus/1")
    return list(clubs.values())


def _normalise_header(text: str) -> str:
    """Fold case and collapse whitespace so header matching survives cosmetic edits."""
    return " ".join(text.split()).lower()


def _colspan(cell) -> int:
    """A cell's column span. Anything unparseable counts as 1, as browsers do."""
    try:
        return max(int(str(cell.get("colspan", 1)).strip()), 1)
    except (TypeError, ValueError):
        return 1


def header_index(table) -> tuple[dict[str, int], int]:
    """(normalised column header -> its position in the row, number of columns).

    Reading by name is what makes a Transfermarkt layout change fail LOUDLY. The
    11 Aug 2026 incident happened because the fields were read at fixed indices: an
    extra column shifted every later one and the parser quietly returned blanks.

    Names only help if header cell N really is body cell N, so the width is returned
    for the body rows to be checked against, and a header that does not span exactly
    one column per cell -- or that has more than one row -- is rejected outright.
    Either would shift every later index and put us straight back in the incident.
    """
    heads = table.select("thead tr")
    if len(heads) != 1:
        raise ValueError(
            f"Transfermarkt squad table has {len(heads)} header rows, expected exactly 1. "
            "This parser maps header cells to body cells one for one, which a multi-row "
            "header breaks. The page layout has changed -- fix the parser.")
    cells = heads[0].find_all(["th", "td"], recursive=False)

    spans = sum(_colspan(cell) for cell in cells)
    if spans != len(cells):
        raise ValueError(
            f"Transfermarkt squad header spans {spans} columns across {len(cells)} cells "
            "(a colspan is present), so header positions no longer match body positions. "
            "The page layout has changed -- fix the parser.")

    columns: dict[str, int] = {}
    for i, cell in enumerate(cells):
        name = _normalise_header(cell.get_text(" ", strip=True))
        if name and name not in columns:
            columns[name] = i

    missing = [h for h in REQUIRED_HEADERS if _normalise_header(h) not in columns]
    if missing:
        found = [cell.get_text(" ", strip=True) for cell in cells]
        raise ValueError(
            f"Transfermarkt squad table is missing required column(s) "
            f"{', '.join(missing)}. Headers found: {found or '(no header row)'}. "
            "The page layout or the season is wrong -- fix the parser or the "
            "--season argument; do NOT fall back to reading columns by position.")
    return columns, len(cells)


def parse_squad(html: str, club_name: str, league_code: str, competition_id: int) -> list[dict]:
    """One row per player in a club's detailed squad page (kader, plus view) HTML."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.items")
    if table is None:
        return []
    columns, width = header_index(table)

    rows = []
    for tr in table.select("tbody > tr.odd, tbody > tr.even"):
        # Summary rows (total market value) carry no player link and a different cell
        # count by design, so they are dropped before the width check, not by it.
        link = tr.select_one("td.hauptlink a[href*='/profil/spieler/']")
        if link is None:
            continue
        player_id_match = re.search(r"/spieler/(\d+)", link["href"])
        cells = tr.find_all("td", recursive=False)
        name = link.get_text(strip=True)
        if len(cells) != width:
            # Never fall back to a blank here: a short row silently mis-reads every
            # later column, and at one row in ten it would never trip the fill floor.
            raise ValueError(
                f"Transfermarkt squad row for {name} at {club_name} has {len(cells)} "
                f"cells but the header has {width}. The page layout has changed -- "
                "fix the parser; do NOT read the missing cells as blank.")
        position = None
        inline = tr.select_one("table.inline-table tr + tr td")
        if inline is not None:
            position = inline.get_text(strip=True)

        def cell(header: str) -> str:
            return cells[columns[_normalise_header(header)]].get_text(" ", strip=True)

        # Market value stays on its CSS selector: it was the one field the incident
        # did NOT lose, precisely because it was never found by position.
        value_cell = tr.select_one("td.rechts.hauptlink")
        rows.append({
            "league_code": league_code,
            "competition_id": competition_id,
            "club_name": club_name,
            "tm_player_id": player_id_match.group(1) if player_id_match else None,
            "player_name": name,
            "date_of_birth": parse_birth_date(cell("Date of birth/Age")),
            "position": position,
            "height_cm": parse_height_cm(cell("Height")),
            "foot": parse_foot(cell("Foot")),
            "contract_until": parse_birth_date(cell("Contract")),  # same date formats as DOB
            "market_value_eur": parse_value(value_cell.get_text(strip=True)) if value_cell else None,
        })
    return rows


def squad_rows(club_name: str, squad_url: str, league_code: str, competition_id: int) -> list[dict]:
    """Fetch a club's detailed squad page and parse it."""
    return parse_squad(_fetch(squad_url), club_name, league_code, competition_id)


def fill_rates(rows: list[dict]) -> dict[str, float]:
    """Share of scraped rows carrying each guarded bio field (0.0 when there are none)."""
    if not rows:
        return {field: 0.0 for field in GUARDED_FIELDS}
    return {field: sum(1 for r in rows if r.get(field) not in (None, "")) / len(rows)
            for field in GUARDED_FIELDS}


def degraded_fields(rows: list[dict],
                    minimum: float = MIN_FILL_RATE) -> list[tuple[str, float]]:
    """(field, fill rate) for every guarded field below the floor. Empty = healthy."""
    return [(field, rate) for field, rate in fill_rates(rows).items() if rate < minimum]


def existing_row_count(out: Path) -> int:
    """Data rows in the CSV we are about to replace. 0 when there is none."""
    if not out.exists():
        return 0
    with open(out, newline="") as f:
        return max(sum(1 for _ in csv.reader(f)) - 1, 0)


def volume_problems(rows: list[dict], clubs_per_league: dict[str, int],
                    previous_rows: int,
                    minimum_ratio: float = MIN_ROW_RATIO) -> list[str]:
    """Complaints about how MUCH was scraped, as opposed to how complete each row is.

    A fill rate is a ratio over the rows that survived, so it is blind to rows that
    never arrived: `club_pages` returns [] whenever its selector matches nothing, and
    the league page is the one request in the flow with no header guard. Three leagues
    at 95% fill would sail through the fill check while a whole division went missing,
    and valuation.main() deletes every valuation before rewriting -- so the dropped
    league would lose all of its valuations.
    """
    problems = []
    empty = sorted(code for code, count in clubs_per_league.items() if count == 0)
    if empty:
        problems.append(
            f"no clubs found for league(s) {', '.join(empty)} -- the league page layout "
            "or the season is wrong, or the request was blocked")
    if previous_rows and len(rows) < previous_rows * minimum_ratio:
        problems.append(
            f"only {len(rows)} rows scraped against {previous_rows} in the existing CSV "
            f"({len(rows) / previous_rows:.0%}, minimum {minimum_ratio:.0%})")
    return problems


def output_path() -> Path:
    return Path(settings.reference_data_dir) / "transfermarkt" / "efl_values.csv"


def backup_dir() -> Path:
    """data/backups, alongside data/reference -- where a file about to be overwritten goes."""
    return Path(settings.reference_data_dir).parent / "backups"


def backup_existing_csv(out: Path, now: datetime | None = None) -> Path | None:
    """Copy the CSV about to be overwritten to data/backups/. None if there is none."""
    if not out.exists():
        return None
    destination = backup_dir() / f"efl_values-{(now or datetime.now()):%Y%m%d-%H%M%S}.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, destination)
    return destination


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Pull EFL market values from Transfermarkt")
    parser.add_argument("--force", action="store_true", help="re-pull even if the output exists")
    parser.add_argument("--season", type=int, default=None,
                        help="Transfermarkt season id (its starting year); "
                             "defaults to the current season")
    parser.add_argument("--allow-degraded", action="store_true",
                        help="write the CSV even if a bio field is largely empty, a "
                             "league returned no clubs, or the row count has collapsed "
                             "(only when a human has decided a partial pull is fine)")
    args = parser.parse_args(argv)

    season = args.season if args.season is not None else current_tm_season()
    print(f"Transfermarkt season {season} ({season}/{(season + 1) % 100:02d})"
          f"{'' if args.season is not None else ' (derived from today)'}")

    out = output_path()
    if out.exists() and not args.force:
        print(f"{out} already present, skipping (use --force to re-pull)")
        return
    out.parent.mkdir(parents=True, exist_ok=True)

    previous_rows = existing_row_count(out)
    all_rows: list[dict] = []
    clubs_per_league: dict[str, int] = {}
    for league_code, (slug, competition_id) in LEAGUES.items():
        clubs = club_pages(slug, league_code, season)
        clubs_per_league[league_code] = len(clubs)
        print(f"[{league_code}] {len(clubs)} clubs")
        for i, (club_name, squad_url) in enumerate(clubs, start=1):
            rows = squad_rows(club_name, squad_url, league_code, competition_id)
            all_rows.extend(rows)
            print(f"  [{league_code}] {i}/{len(clubs)} {club_name}: {len(rows)} players")

    if not all_rows:
        raise SystemExit(f"No players scraped at all: refusing to touch {out}. "
                         "Check the season and that Transfermarkt is reachable.")

    # A pull that has lost a field, or a division, must never be published over a good
    # one. Completeness per row and volume across rows are different failures: neither
    # check sees the other's.
    problems = [f"{field} is filled on only {rate:.1%} of {len(all_rows)} rows "
                f"(minimum {MIN_FILL_RATE:.0%})"
                for field, rate in degraded_fields(all_rows)]
    problems += volume_problems(all_rows, clubs_per_league, previous_rows)
    if problems:
        for problem in problems:
            print(f"{'WARNING' if args.allow_degraded else 'ERROR'}: {problem}")
        if not args.allow_degraded:
            raise SystemExit(
                f"Refusing to overwrite {out}: the pull above is degraded and the existing "
                "file is unchanged. Check the season and the squad-page column headers. "
                "Pass --allow-degraded to write it anyway.")
        print("--allow-degraded was passed: writing the degraded pull anyway")

    saved = backup_existing_csv(out)
    if saved is not None:
        print(f"Backed up the previous CSV to {saved}")

    # Atomic write so an interrupted run never leaves a half-file behind.
    tmp = out.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    tmp.rename(out)
    valued = sum(1 for r in all_rows if r["market_value_eur"])
    print(f"\nWrote {len(all_rows)} players ({valued} with a market value) to {out}")


if __name__ == "__main__":
    main()
