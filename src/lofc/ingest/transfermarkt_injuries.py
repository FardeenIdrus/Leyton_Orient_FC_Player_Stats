"""Transfermarkt injury history: the objective input to the club's Medical dimension.

ONE page per player -- /verletzungen/spieler/<id> -- a stable six-column table:
    Season | Injury | from | until | Days | Games missed

The appearance page was evaluated and rejected: its columns shift between competition
types and its header row is a sort link rather than labels. Games missed is all the
availability rule needs (see the design spec, section 4).
"""

from __future__ import annotations

import re

# Data rows start with a season in "25/26" form; the header row does not.
_SEASON_RE = re.compile(r"^\d{2}/\d{2}$")
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)


def _cell_text(fragment: str) -> str:
    """Strip tags and normalise whitespace, including Transfermarkt's &nbsp; padding."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_tm_date(text: str) -> str | None:
    """'18/08/2025' -> '2025-08-18'. A dash (ongoing injury) or junk -> None."""
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", text or "")
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def parse_days(text: str) -> int:
    """'9 days' -> 9. Absent or '-' -> 0."""
    match = re.search(r"\d+", text or "")
    return int(match.group(0)) if match else 0


def parse_games_missed(text: str) -> int:
    """'2' -> 2. A dash means the injury cost no matches -> 0."""
    match = re.fullmatch(r"\d+", (text or "").strip())
    return int(match.group(0)) if match else 0


def parse_injury_rows(html: str) -> list[dict]:
    """Every injury on the page. A player with no injuries yields an empty list."""
    rows: list[dict] = []
    for row_html in _ROW_RE.findall(html):
        cells = [_cell_text(c) for c in _CELL_RE.findall(row_html)]
        if len(cells) < 6:
            continue
        season, injury, date_from, date_until, days, games = cells[:6]
        if not _SEASON_RE.match(season):
            continue
        rows.append({
            "season_label": season,
            "injury_type_raw": injury,
            "date_from": parse_tm_date(date_from),
            "date_until": parse_tm_date(date_until),
            "days_out": parse_days(days),
            "games_missed": parse_games_missed(games),
        })
    return rows


# The categories the club names in its Medical & Durability requirements. Order matters:
# a specific joint is checked before the generic ligament/muscle rules, so that
# "ankle ligament tear" is an ankle injury and not a knee one.
INJURY_CATEGORIES: dict[str, tuple[str, ...]] = {
    "hamstring": ("hamstring",),
    "calf": ("calf",),
    "groin": ("groin", "adductor", "pubitis"),
    "ankle": ("ankle",),
    "hip": ("hip",),
    "knee_ligament": ("cruciate", "acl", "knee", "meniscus", "ligament"),
    "muscular": ("muscular", "muscle", "thigh", "quadriceps"),
}


def categorise_injury(raw: str) -> str:
    """Normalise Transfermarkt's free text. Unmapped phrasing returns 'other'.

    Callers should log 'other' results so new phrasings surface rather than vanish.
    """
    text = (raw or "").lower()
    for category, needles in INJURY_CATEGORIES.items():
        if any(needle in text for needle in needles):
            return category
    return "other"


import argparse
import csv
import shutil
from pathlib import Path

from lofc.config import settings
from lofc.ingest.transfermarkt_common import fetch

BASE_URL = "https://www.transfermarkt.co.uk"
FIELDNAMES = ["tm_player_id", "season_label", "injury_type_raw", "injury_category",
              "date_from", "date_until", "days_out", "games_missed"]


def injury_url(tm_player_id: int) -> str:
    """The slug is cosmetic -- Transfermarkt resolves the player from the id alone."""
    return f"{BASE_URL}/player/verletzungen/spieler/{tm_player_id}"


def _tm_dir() -> Path:
    return Path(settings.reference_data_dir) / "transfermarkt"


def output_path() -> Path:
    return _tm_dir() / "injuries.csv"


def partial_path() -> Path:
    return _tm_dir() / "injuries.csv.partial"


def progress_path() -> Path:
    """Ids already fetched. Needed because a player with no injuries writes no rows."""
    return _tm_dir() / "injuries.progress"


def load_progress() -> set[int]:
    path = progress_path()
    if not path.exists():
        return set()
    return {int(line) for line in path.read_text().split() if line.strip()}


def player_ids() -> list[int]:
    """Distinct Transfermarkt ids from the EFL market-value scrape."""
    path = _tm_dir() / "efl_values.csv"
    with open(path) as handle:
        ids = {int(row["tm_player_id"]) for row in csv.DictReader(handle)
               if row.get("tm_player_id")}
    return sorted(ids)


def scrape(ids: list[int]) -> int:
    """Fetch each player's injury page, appending as we go. Returns rows written.

    Resumable: ids already in the progress file are skipped, and a player whose page
    fails is logged but NOT marked done, so a later run retries him.
    """
    partial, progress, out = partial_path(), progress_path(), output_path()
    partial.parent.mkdir(parents=True, exist_ok=True)
    done = load_progress()
    written = 0

    with open(partial, "a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        if handle.tell() == 0:
            writer.writeheader()
        for index, tm_id in enumerate(ids, start=1):
            if tm_id in done:
                continue
            try:
                html = fetch(injury_url(tm_id))
            except Exception as exc:               # one bad page must not end the run
                print(f"  [skip] {tm_id}: {exc}", flush=True)
                continue
            for row in parse_injury_rows(html):
                row["tm_player_id"] = tm_id
                row["injury_category"] = categorise_injury(row["injury_type_raw"])
                if row["injury_category"] == "other":
                    print(f"  [uncategorised] {row['injury_type_raw']!r}", flush=True)
                writer.writerow(row)
                written += 1
            handle.flush()
            with open(progress, "a") as marker:    # only after the page succeeded
                marker.write(f"{tm_id}\n")
            if index % 50 == 0:
                print(f"  {index}/{len(ids)} players", flush=True)

    # Publish: copy (not move) the accumulated partial file to the public output
    # path. partial and progress both persist so a later scrape() call -- whether
    # a resume after interruption or a fresh invocation over the same id list --
    # can append further rows and correctly skip ids already marked done. Deleting
    # either here would defeat resumability, which is the entire point of this file.
    shutil.copy2(partial, out)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull Transfermarkt injury histories for EFL players")
    parser.add_argument("--force", action="store_true",
                        help="re-pull even if injuries.csv already exists")
    parser.add_argument("--limit", type=int, default=None,
                        help="only the first N players (for a smoke test)")
    args = parser.parse_args()

    out = output_path()
    if out.exists() and not args.force and not progress_path().exists():
        print(f"{out} already present, skipping (use --force to re-pull)")
        return

    ids = player_ids()
    if args.limit:
        ids = ids[:args.limit]
    print(f"{len(ids)} players to fetch (~{len(ids) * 2.5 / 3600:.1f} hours)")
    written = scrape(ids)
    print(f"\nWrote {written} injury rows to {out}")


if __name__ == "__main__":
    main()
