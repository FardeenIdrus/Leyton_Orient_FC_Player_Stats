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
