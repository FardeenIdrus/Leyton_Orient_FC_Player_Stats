"""Pull current Transfermarkt market values for the EFL target leagues.

The maintained dcaribou dataset (lofc.ingest.transfermarkt) covers first divisions
only, so for the Championship, League One, League Two and the National League we
read the club squad pages directly: one page per league plus one per club, about
100 requests in total, rate-limited to one request every 2.5 seconds.

Values are the current snapshot, so they are era-matched to the season just played
(2025/26) and only that season's metrics should train the valuation model.

Output: data/reference/transfermarkt/efl_values.csv with one row per player
(league, club, Transfermarkt id, name, date of birth, position, market value).
Idempotent: skipped when the output exists, --force re-pulls.

Run with:  python -m lofc.ingest.transfermarkt_efl
"""

from __future__ import annotations

import argparse
import csv
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

from lofc.config import settings

BASE = "https://www.transfermarkt.com"
# TM league code -> (URL slug, our StatsBomb competition_id).
LEAGUES = {
    "GB2": ("championship", 3),
    "GB3": ("league-one", 4),
    "GB4": ("league-two", 5),
    "CNAT": ("national-league", 65),
}
# TM labels seasons by their starting year: 2025 = the 2025/26 season.
TM_SEASON = 2025
REQUEST_DELAY_S = 2.5
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

_last_request = 0.0


def _fetch(url: str, retries: int = 3) -> str:
    """Polite GET: rate-limited, browser user agent, exponential backoff."""
    global _last_request
    wait = REQUEST_DELAY_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                _last_request = time.monotonic()
                return response.read().decode("utf-8", "ignore")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


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


def club_pages(league_slug: str, league_code: str) -> list[tuple[str, str]]:
    """(club name, squad page URL) for every club in the league season."""
    url = f"{BASE}/{league_slug}/startseite/wettbewerb/{league_code}/saison_id/{TM_SEASON}"
    soup = BeautifulSoup(_fetch(url), "lxml")
    clubs: dict[str, tuple[str, str]] = {}
    for a in soup.select("td.hauptlink a[href*='/startseite/verein/']"):
        href = a["href"].split("?")[0]
        name = a.get_text(strip=True)
        if name and href not in clubs:
            # The detailed squad view (kader, plus=1) carries height, foot and the
            # contract date on top of the basic page's name/DOB/value.
            base = href.split("/saison_id")[0].replace("/startseite/", "/kader/")
            clubs[href] = (name, f"{BASE}{base}/saison_id/{TM_SEASON}/plus/1")
    return list(clubs.values())


def squad_rows(club_name: str, squad_url: str, league_code: str, competition_id: int) -> list[dict]:
    """One row per player on a club's detailed squad page (kader, plus view)."""
    soup = BeautifulSoup(_fetch(squad_url), "lxml")
    table = soup.select_one("table.items")
    if table is None:
        return []
    rows = []
    for tr in table.select("tbody > tr.odd, tbody > tr.even"):
        link = tr.select_one("td.hauptlink a[href*='/profil/spieler/']")
        if link is None:
            continue
        player_id_match = re.search(r"/spieler/(\d+)", link["href"])
        cells = tr.find_all("td", recursive=False)
        # Detailed layout: # | player block | birth date | nat | height | foot |
        # joined | signed from | contract until | market value.
        position = None
        inline = tr.select_one("table.inline-table tr + tr td")
        if inline is not None:
            position = inline.get_text(strip=True)

        def cell(i: int) -> str:
            return cells[i].get_text(" ", strip=True) if len(cells) > i else ""

        value_cell = tr.select_one("td.rechts.hauptlink")
        rows.append({
            "league_code": league_code,
            "competition_id": competition_id,
            "club_name": club_name,
            "tm_player_id": player_id_match.group(1) if player_id_match else None,
            "player_name": link.get_text(strip=True),
            "date_of_birth": parse_birth_date(cell(2)),
            "position": position,
            "height_cm": parse_height_cm(cell(4)),
            "foot": parse_foot(cell(5)),
            "contract_until": parse_birth_date(cell(8)),  # same date formats as DOB
            "market_value_eur": parse_value(value_cell.get_text(strip=True)) if value_cell else None,
        })
    return rows


def output_path() -> Path:
    return Path(settings.reference_data_dir) / "transfermarkt" / "efl_values.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull EFL market values from Transfermarkt")
    parser.add_argument("--force", action="store_true", help="re-pull even if the output exists")
    args = parser.parse_args()

    out = output_path()
    if out.exists() and not args.force:
        print(f"{out} already present, skipping (use --force to re-pull)")
        return
    out.parent.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    for league_code, (slug, competition_id) in LEAGUES.items():
        clubs = club_pages(slug, league_code)
        print(f"[{league_code}] {len(clubs)} clubs")
        for i, (club_name, squad_url) in enumerate(clubs, start=1):
            rows = squad_rows(club_name, squad_url, league_code, competition_id)
            all_rows.extend(rows)
            print(f"  [{league_code}] {i}/{len(clubs)} {club_name}: {len(rows)} players")

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
