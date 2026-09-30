"""A scout report row from the sheet, normalised into something storable and joinable.

Pure: values in, frame out. No I/O, no database, no Google. `scout_sheets` fetches;
this decides what the values mean.

THE DATE IS THE DANGEROUS PART. `Fixture Date` is DD-MM-YYYY -- the JotForm field's own
placeholder says so. pandas defaults to MONTH-first, and 25 of the 51 distinct dates in
the live sheet have both parts under 13, so a default parse reads about half of them as
a different day and raises NOTHING. `21-07-2026` is the kind that would error, and it is
the minority. Everything here is parsed with an explicit format.

`Last Update Date` and `Submission Date` in the same sheet are ISO. Two formats, one
file; both are handled explicitly rather than guessed.
"""

from __future__ import annotations

import datetime as dt
import re

import pandas as pd

# The Player field is a dropdown built from the `Player Names` tab. This is its escape
# hatch for a player not on the list, and it is the single most "common" player in the
# sheet -- chosen 19 times. Nineteen unrelated reports about nineteen different people.
PLACEHOLDER_PLAYER = "A New Player"

SHEET_DATE_FORMAT = "%d-%m-%Y"

# Sheet heading -> stored column. The sheet's headings are prose written for a form;
# these are the names the rest of the platform joins on.
COLUMNS = {
    "Submission ID": "submission_id",
    "Scout": "scout",
    "Live or Video": "observation",
    "Report Type": "report_type",
    "Player": "player_name",
    "Playing For": "club_name",
    "Foot": "foot",
    "Home Team": "home_team",
    "Away Team": "away_team",
    "Report Comments": "comments",
    "Performance Grade": "grade",
    "Squad Role": "squad_role",
    "Overall Verdict": "verdict",
    "Submission Edit URL": "edit_url",
}

STORED_COLUMNS = list(COLUMNS.values()) + [
    "fixture_date", "positions_played", "recommended_positions",
    "submitted_at", "updated_at", "linkable", "name_from_report",
]

# A name is 2-4 capitalised words. Apostrophes and hyphens are part of real names
# (Kah'vanni Amarni Lincoln, Oscar Lewie-Bech Jorgense, Corey Adjetey-Brew, all live rows).
_NAME = re.compile(r"^([A-Z][\w\u00C0-\u024F\u2019'-]*"
                   r"(?:\s+[A-Z][\w\u00C0-\u024F\u2019'-]*){1,3})$")
# Where the name stops and the report starts. A shirt number may precede the name
# ("52. Reggie Rose - ..."); a bracketed one may follow it ("Kerriou (#25) played as").
_LEADING_NUMBER = re.compile(r"^\s*\d{1,3}\s*[.)]\s*")
_STOP = re.compile(
    r"\s+(?:is|was|has|had|played|plays|scored|started|showed|came|given|a|an|the|age|aged)"
    r"\b|[.,;:()\[\]\u2013\u2014]|\s+-\s+", re.IGNORECASE)


def parse_sheet_date(value, iso: bool = False) -> dt.date | None:
    """One sheet date as a `date`, or None. DAY-first unless `iso` is set.

    None for anything unparseable. A date that does not exist -- `32-01-2026` -- is
    absent, never quietly shifted into a neighbouring month by a fallback parse.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    stamp = (pd.to_datetime(text, errors="coerce") if iso
             else pd.to_datetime(text, format=SHEET_DATE_FORMAT, errors="coerce"))
    return None if pd.isna(stamp) else stamp.date()


def is_placeholder_player(name) -> bool:
    """True for the dropdown's "A New Player" option, and for no name at all.

    Both mean the same thing operationally: this report cannot be attached to a person.
    The report is still kept -- a scout watched a match and wrote it up -- it simply
    never links.
    """
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return True
    return str(name).strip().lower() in ("", PLACEHOLDER_PLAYER.lower())


def name_from_comment(comment, club=None) -> str | None:
    """The player's name read out of the report text, or None if it cannot be read cleanly.

    Used ONLY when the Player field holds the dropdown's "A New Player" escape hatch. The
    scout writes the real name first; four shapes appear in the live sheet:

        Connor Brooks. Age 18. WHU U21              name, full stop, biography
        Finley Hooper is 18 years old...            name, then a verb
        Raphael Borges Rodrigues (#17 played as...  name, then a shirt number
        52. Reggie Rose - A 21 year old goalkeeper  shirt number, name, dash

    REFUSES RATHER THAN GUESSES. A comment that does not open with something shaped like a
    name returns None and the row keeps reading "A New Player". Twenty rows honestly saying
    "unknown" is better than one row naming the wrong man -- and a name recovered here is
    never used to match a player (see `reports_frame`).
    """
    if comment is None or (isinstance(comment, float) and pd.isna(comment)):
        return None
    line = str(comment).strip().split("\n")[0].strip()
    if not line:
        return None
    line = _LEADING_NUMBER.sub("", line)
    candidate = _STOP.split(line, maxsplit=1)[0].strip()
    if not candidate or candidate.lower() == PLACEHOLDER_PLAYER.lower():
        return None
    match = _NAME.match(candidate)
    if not match:
        return None
    name = match.group(1)
    # A report often opens by setting the scene ("...Man City have a lot of rotations").
    # If a scout opens with the CLUB instead of the player, the club must not become the
    # player's name.
    if club and name.strip().lower() == str(club).strip().lower():
        return None
    return name


def split_positions(value) -> list[str]:
    """The form's multi-select, newline-separated, as a list. 43 of 437 rows carry more
    than one.

    The scout's vocabulary is preserved VERBATIM -- 35 codes, none of which are the
    platform's eight position groups. `RCB` means the right-sided centre back of a back
    three; mapping it to "Centre Back" would assert something the scout did not say.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [p.strip() for p in str(value).split("\n") if p.strip()]


def reports_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """The `Form responses` tab as a storable frame, one row per report.

    Keyed on `Submission ID` -- JotForm's own, unique across all 437 live rows, and
    STABLE ACROSS EDITS, which is what lets an edited report upsert instead of
    duplicating. A row without one is dropped: with no key there is nothing to upsert on,
    so it would insert afresh on every sync, once a minute, forever.
    """
    out = pd.DataFrame(columns=STORED_COLUMNS)
    if raw.empty:
        return out

    frame = raw.copy()
    for heading, column in COLUMNS.items():
        out[column] = (frame[heading].astype(object)
                       if heading in frame.columns else None)

    out["fixture_date"] = (frame["Fixture Date"].map(parse_sheet_date)
                           if "Fixture Date" in frame.columns else None)
    # Both timestamps are sparse in the live sheet -- Submission Date is blank on 22 of
    # 437 rows, Last Update on 310. Absent stays absent: neither now() nor the epoch.
    for heading, column in (("Submission Date", "submitted_at"),
                            ("Last Update Date", "updated_at")):
        out[column] = (frame[heading].map(lambda v: parse_sheet_date(v, iso=True))
                       if heading in frame.columns else None)

    out["positions_played"] = (frame["Position(s) Played"].map(split_positions)
                               if "Position(s) Played" in frame.columns else None)
    out["recommended_positions"] = (frame["Recommended Position"].map(split_positions)
                                    if "Recommended Position" in frame.columns else None)
    # Built as a list of PYTHON bools, not via ~Series: a numpy bool_ reaches the
    # database driver as an unregistered adapter on some backends, the same class of
    # problem as a NaN arriving where NULL was meant.
    placeholder = [is_placeholder_player(v) for v in out["player_name"]]
    # `linkable` is decided BEFORE any name is recovered, and is never revisited. A name
    # read out of free text is evidence of who was watched, not an identity -- matching on
    # it would attach a rating, an injury history and an assessment to a player on the
    # strength of a regular expression.
    out["linkable"] = pd.Series([not p for p in placeholder], index=out.index, dtype=object)

    # Recover the name for display only. Fires only on the placeholder, so the moment the
    # Head of Recruitment corrects the row in the sheet the real name takes over on the
    # next sync and this stops applying.
    comments = out["comments"] if "comments" in out.columns else pd.Series(
        [None] * len(out), index=out.index)
    clubs = out["club_name"] if "club_name" in out.columns else pd.Series(
        [None] * len(out), index=out.index)
    recovered = [name_from_comment(c, club=k) if p else None
                 for p, c, k in zip(placeholder, comments, clubs)]
    out["name_from_report"] = pd.Series([r is not None for r in recovered],
                                        index=out.index, dtype=object)
    out["player_name"] = [r if r else n for r, n in zip(recovered, out["player_name"])]

    out["submission_id"] = out["submission_id"].astype(str).str.strip()
    out = out[out["submission_id"].ne("") & out["submission_id"].ne("nan")]
    # The key must be unique before it reaches an upsert. `Database` is a duplicate of
    # this tab, and a pasted row would collide the same way.
    out = out.drop_duplicates("submission_id", keep="first")
    return out[STORED_COLUMNS].reset_index(drop=True)
