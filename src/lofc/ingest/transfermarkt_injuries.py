"""Transfermarkt injury history: the objective input to the club's Medical dimension.

ONE page per player -- /verletzungen/spieler/<id> -- a stable six-column table:
    Season | Injury | from | until | Days | Games missed

The appearance page was evaluated and rejected: its columns shift between competition
types and its header row is a sort link rather than labels. Games missed is all the
availability rule needs (see the design spec, section 4).

Two safeguards exist because a truncated run once destroyed a full scrape:
  - `--limit` is a SMOKE TEST and writes to injuries.sample.csv, with its own partial
    and progress files. It cannot publish over injuries.csv, and it cannot leave
    progress markers that would make a later full run skip players;
  - the file a publish replaces is copied to data/backups/ first.
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
from datetime import datetime
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


# A truncated (--limit) run writes to its OWN trio of files. It can therefore never
# publish over the full history, and its progress markers can never make a later full
# run skip players. See `main()` for the incident this prevents. The names derive from
# output_path() so redirecting that one path (as the tests do) redirects these too.
def sample_output_path() -> Path:
    return output_path().with_name("injuries.sample.csv")


def sample_partial_path() -> Path:
    return output_path().with_name("injuries.sample.csv.partial")


def sample_progress_path() -> Path:
    return output_path().with_name("injuries.sample.progress")


def _paths(sample: bool = False) -> tuple[Path, Path, Path]:
    """(partial, progress, output) for a full run or for a --limit smoke test."""
    if sample:
        return sample_partial_path(), sample_progress_path(), sample_output_path()
    return partial_path(), progress_path(), output_path()


def backup_dir() -> Path:
    """data/backups, alongside data/reference -- where a file about to be overwritten goes."""
    return Path(settings.reference_data_dir).parent / "backups"


def backup_existing_csv(out: Path, now: datetime | None = None) -> Path | None:
    """Copy the CSV about to be overwritten to data/backups/. None if there is none.

    Mirrors `transfermarkt_efl.backup_existing_csv`: the publish below is a rename,
    which is atomic but irreversible, so the file it replaces is copied first. Recovery
    from a bad publish is then a file copy rather than a 1.8-hour re-scrape.
    """
    if not out.exists():
        return None
    destination = backup_dir() / f"{out.stem}-{(now or datetime.now()):%Y%m%d-%H%M%S}.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, destination)
    return destination


def load_progress(sample: bool = False) -> set[int]:
    path = _paths(sample)[1]
    if not path.exists():
        return set()
    return {int(line) for line in path.read_text().split() if line.strip()}


def player_ids() -> list[int]:
    """Distinct Transfermarkt ids from the EFL market-value scrape.

    A blank id is a squad row we hold no Transfermarkt identity for -- expected, and
    skipped. Anything else that is not an integer is a corrupt or shifted CSV and
    RAISES: dropping it silently would shorten the id list, and a short id list is
    exactly what publishes a truncated injuries.csv over the full one.
    """
    path = _tm_dir() / "efl_values.csv"
    ids: set[int] = set()
    with open(path) as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            raw = (row.get("tm_player_id") or "").strip()
            if not raw:
                continue
            try:
                ids.add(int(raw))
            except ValueError as exc:
                raise ValueError(
                    f"{path} line {line}: tm_player_id {raw!r} is not an integer. "
                    "The market-value CSV is corrupt or its columns have shifted -- "
                    "fix it and re-run; the injury scrape is NOT starting from a "
                    "partial id list.") from exc
    return sorted(ids)


CONSECUTIVE_FAILURE_LIMIT = 20


class ScrapeResult(int):
    """The row count `scrape()` returns. A resumability driver needs to report a
    failure count too, but the existing call sites (and tests) compare the return
    value directly against an int of rows written -- so this subclasses int rather
    than becoming a tuple/dataclass, keeping `scrape(...) == written` true while
    still carrying `.failed` for callers (namely `main()`) that want it.
    """

    failed: int = 0

    def __new__(cls, written: int, failed: int = 0):
        obj = super().__new__(cls, written)
        obj.failed = failed
        return obj


def scrape(ids: list[int], force: bool = False, sample: bool = False) -> int:
    """Fetch each player's injury page, appending as we go. Returns rows written
    (as a `ScrapeResult`, whose `.failed` attribute carries the failure count).

    Resumable across a genuine interruption: a run that dies mid-way (killed,
    crashed, `KeyboardInterrupt` -- which is deliberately NOT caught below) leaves
    `partial` and `progress` on disk exactly as they stood, and the next call with
    the same id list skips everything already marked done and retries the rest.

    A run that reaches the end of its id list, by contrast, is complete: `partial`
    is published atomically to `out` and both working files are removed. Calling
    `scrape()` again after that is a fresh refresh, not a resume -- every id,
    including ones already recorded from the previous run, is refetched. That is
    intentional: `force=True` relies on exactly this to start genuinely clean.

    `sample=True` routes the whole run -- working files and publish target -- to the
    injuries.sample.* trio, so a truncated id list cannot reach the real history.
    """
    partial, progress, out = _paths(sample)
    partial.parent.mkdir(parents=True, exist_ok=True)

    if force:
        partial.unlink(missing_ok=True)
        progress.unlink(missing_ok=True)

    done = load_progress(sample)
    written = 0
    failed = 0
    consecutive_failures = 0

    with open(partial, "a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        if handle.tell() == 0:
            writer.writeheader()
        for index, tm_id in enumerate(ids, start=1):
            if tm_id in done:
                continue
            try:
                html = fetch(injury_url(tm_id))
                rows = parse_injury_rows(html)
            except Exception as exc:               # one bad page must not end the run
                failed += 1
                consecutive_failures += 1
                print(f"  [skip] {tm_id}: {exc}", flush=True)
                if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                    raise RuntimeError(
                        f"aborting after {consecutive_failures} consecutive page "
                        f"failures (most recently id {tm_id}); Transfermarkt may be "
                        "blocking requests. Progress so far is saved -- rerun to "
                        "resume."
                    ) from exc
                continue
            consecutive_failures = 0
            for row in rows:
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

    # Atomic publish: an interrupted run never leaves a half-written injuries.csv,
    # and `replace()` is a same-filesystem rename, so `out` is either the previous
    # good file or the new complete one -- never a partial mix of both. Both working
    # files are consumed here: the next invocation with these same ids is therefore
    # a refresh (refetch everything), not a resume. Resuming only makes sense for a
    # run that never reached this line.
    saved = backup_existing_csv(out)
    if saved is not None:
        print(f"Backed up the previous CSV to {saved}", flush=True)
    partial.replace(out)
    progress.unlink(missing_ok=True)
    return ScrapeResult(written, failed)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Pull Transfermarkt injury histories for EFL players")
    parser.add_argument("--force", action="store_true",
                        help="re-pull even if injuries.csv already exists")
    parser.add_argument("--limit", type=int, default=None,
                        help="only the first N players, as a smoke test. A limited run "
                             "writes to injuries.sample.csv and can never touch the "
                             "full injuries.csv")
    args = parser.parse_args(argv)

    # A limited run is a smoke test, never a refresh. Reaching the end of a TRUNCATED
    # id list looks identical to reaching the end of the real one, so `scrape()` would
    # publish it -- which is how `--limit 5 --force` once replaced a 3,930-row
    # injuries.csv with a handful and then emptied player_injuries downstream. Rather
    # than refuse the combination (which would leave no smoke test at all), the whole
    # limited run is diverted to its own files.
    sample = args.limit is not None
    if sample and args.limit < 1:
        parser.error("--limit must be at least 1")

    out = sample_output_path() if sample else output_path()
    progress = sample_progress_path() if sample else progress_path()
    if sample:
        print(f"--limit {args.limit}: SMOKE TEST. Writing to {out}; {output_path()} "
              "is not touched. Re-run without --limit for the real scrape.")

    if out.exists() and not args.force and not progress.exists():
        print(f"{out} already present, skipping (use --force to re-pull)")
        return

    ids = player_ids()
    if sample:
        ids = ids[:args.limit]
    print(f"{len(ids)} players to fetch (~{len(ids) * 2.5 / 3600:.1f} hours)")
    written = scrape(ids, force=args.force, sample=sample)
    print(f"\nWrote {written} injury rows to {out} ({written.failed} failed)")


if __name__ == "__main__":
    main()
