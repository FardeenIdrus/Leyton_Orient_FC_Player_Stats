"""The `Player Names` tab: the controlled list behind the scout form's Player dropdown.

Pure: values in, frame out.

THIS TAB IS WHAT MAKES IDENTITY MATCHING SAFE. A scout report carries a player's NAME and
nothing else. Matching on name alone links 279 of the 350 scouted players but leaves 13
names claimed by two different people in our own `players` table -- thirteen chances to
attach one man's scout report, and his verdict, to another. This tab carries DATE OF
BIRTH, and name + date of birth links 200 with ZERO ambiguity. Fewer matches and no
landmines is the same trade `model/identity.py` made after the 54-namesake audit.

A THIRD DATE FORMAT IN ONE WORKBOOK: `Fixture Date` is DD-MM-YYYY (hyphens), `DOB` here is
DD/MM/YYYY (slashes), `Submission Date` is ISO. Each is parsed with an explicit format,
because every one of them is ambiguous under a default parse and none of them errors when
read wrongly.

The tab also carries `TrM ID`, `SB ID` and `SkillC ID` -- empty on all 4,598 rows. The club
made space to link players to Transfermarkt, StatsBomb and SkillCorner and never filled it
in. They are deliberately not stored: three always-null columns would imply a link the
platform does not have.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

LOOKUP_DATE_FORMAT = "%d/%m/%Y"

STORED_COLUMNS = ["player_name", "date_of_birth", "source_ref", "profile_url", "flagged"]


def parse_lookup_dob(value) -> dt.date | None:
    """One `DOB` cell as a date, or None. DAY-first, slash-separated.

    None for anything that is not a real date -- including the one live row holding the
    literal text "19 yrs", where someone typed an age. A tolerant parser would either
    raise on the whole column or invent a date from the number.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    stamp = pd.to_datetime(text, format=LOOKUP_DATE_FORMAT, errors="coerce")
    return None if pd.isna(stamp) else stamp.date()


def lookup_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """The tab as a storable frame, one row per dropdown entry.

    A player with no birth date is KEPT. 1,694 of 4,598 rows have none; they cannot be
    matched, but they are still entries a scout can pick, and dropping them would make
    the platform disagree with the form about which players exist.

    Deduplicated on (name, birth date). The same name with two different dates is two
    real people and both stay -- and because the key carries the date, both still match
    correctly. The same name with the SAME date is one player entered twice, and left in
    it would make its own key ambiguous, so the player would stop matching altogether.
    """
    out = pd.DataFrame(columns=STORED_COLUMNS)
    if raw.empty:
        return out

    frame = raw.copy()
    names = (frame["Player"].astype(str).str.strip()
             if "Player" in frame.columns else pd.Series(dtype=str))
    out["player_name"] = names
    out["date_of_birth"] = (frame["DOB"].map(parse_lookup_dob)
                            if "DOB" in frame.columns else None)
    out["source_ref"] = (frame["ID"].astype(str).str.strip()
                         if "ID" in frame.columns else None)
    # A face-image CDN URL, present on 1,048 rows. Kept for the interface to use later.
    out["profile_url"] = (frame["Link"].astype(str).str.strip()
                          if "Link" in frame.columns else None)
    out["flagged"] = (frame["Flagged"].astype(str).str.strip()
                      if "Flagged" in frame.columns else None)

    # Trailing blank rows are ordinary in a spreadsheet and match nothing.
    out = out[out["player_name"].ne("") & out["player_name"].ne("nan")]
    for column in ("source_ref", "profile_url", "flagged"):
        out[column] = out[column].replace({"": None, "nan": None})
    out = out.drop_duplicates(["player_name", "date_of_birth"], keep="first")
    return out[STORED_COLUMNS].reset_index(drop=True)
