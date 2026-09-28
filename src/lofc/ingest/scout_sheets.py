"""Read the club's scouting sheet over the Google Sheets API. READ-ONLY, twice over.

The sheet is the club's live working document: six scouts file match reports through a
JotForm form, JotForm writes them into the sheet, and the Head of Recruitment curates ten
further tabs by hand. The platform must never alter it, and that is enforced by two
independent layers, NEITHER of which depends on this module being correct:

  1. The service-account token requests only ``spreadsheets.readonly``. A write is
     rejected by Google with HTTP 403 "Request had insufficient authentication scopes".
     Verified against the live sheet on 2026-09-28 by attempting one.
  2. The account is a VIEWER on the file, so it has no permission to write regardless of
     scope. Visible, and revocable, in the sheet's own share list.

WHY THE SHEET AND NOT JOTFORM. JotForm is the true origin and has a stabler API, but it
holds only the 437 reports. `Player Names` (4,598 rows, and the DATE OF BIRTH that makes
identity matching unambiguous), `Fixtures Schedule` and `Players of Interest` exist only
here. Reading the sheet costs a little fragility and buys the other six tables.

ONE CALL. `batchGet` fetches every range at once and counts as a SINGLE request against
the 60-reads-per-minute-per-user quota, so a 60-second poll uses 1.7% of it. Measured
2.6s for all seven ranges.

Run:  python -m lofc.ingest.scout_sheets   (prints what it can see; writes nothing)
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd

# Read-only. Widening this is a security decision, not a convenience one.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# The tabs the platform reads, and ONLY these. The sheet holds eleven; the four not
# listed are deliberate omissions, each verified against the live export 2026-09-28:
#   Database         - byte-identical to `Form responses` (DataFrame.equals -> True).
#                      Reading both would double every report.
#   Teams Watched    - a pivot of `Fixtures Schedule`, and its stored numbers are
#                      already stale for 21 of 156 clubs. Computed at read time instead,
#                      so it can never drift again.
#   Fixtures - Video - the `Type = Video` subset of `Fixtures Schedule`.
#   InputFix         - the form's dropdown options. Configuration, not data.
REQUIRED_TABS: tuple[str, ...] = (
    "Form responses",
    "Player Names",
    "Team Names",
    "Fixtures Schedule",
    "Players of Interest",
    "PlayersToFollowUpOn",
    "Teams to Cover",
)


def missing_tabs(available: list[str], required: tuple[str, ...] = REQUIRED_TABS
                 ) -> list[str]:
    """Which required tabs are absent, IN ORDER, so the caller can name them.

    A renamed tab is silent data loss: the range returns nothing, the loader stores six
    tables instead of seven, and the sync reports success. The tabs are people-named and
    the club edits this sheet daily, so a rename is a matter of when. Returning the names
    rather than a boolean is the difference between a fixable message and someone
    diffing eleven tabs by eye.
    """
    have = set(available)
    return [tab for tab in required if tab not in have]


def frame_from_values(values: list[list] | None) -> pd.DataFrame:
    """The API's ragged arrays as a DataFrame, first row as the header.

    The Sheets API omits TRAILING EMPTY CELLS, so a row is only as wide as its last
    non-empty value. Measured on the live sheet: `Player Names` returns a nine-column
    header and 4,598 rows of six columns, and
    ``pd.DataFrame(rows, columns=header)`` raises outright on that. Every row is padded
    to the header's width.

    A row LONGER than the header keeps its extra cells under positional names. Data
    appearing unexpectedly is a question to answer; data vanishing silently is a bug.

    Values are left as strings. Type coercion belongs to the parsing layer, which knows
    that `Fixture Date` is DD-MM-YYYY -- letting pandas guess here would read
    ``03-07-2026`` as 7 March.
    """
    if not values:
        return pd.DataFrame()

    header = [str(h) for h in values[0]]
    rows = values[1:]
    width = max([len(header)] + [len(r) for r in rows]) if rows else len(header)

    # Blank header cells are ordinary in a spreadsheet, and two columns both named ""
    # would collide on assignment. Name them positionally instead.
    columns = [header[i] if i < len(header) and header[i].strip() else f"_col{i}"
               for i in range(width)]
    padded = [list(r) + [""] * (width - len(r)) for r in rows]
    return pd.DataFrame(padded, columns=columns, dtype=object)


def payload_hash(payload: dict[str, list[list]]) -> str:
    """A stable digest of one whole pull, for "has anything changed?".

    Polled every 60 seconds against a source that changes a handful of times a day, so
    the overwhelmingly common answer is no. Comparing this against the stored digest lets
    the job stop before it opens a database transaction.

    One digest covers ALL tabs, so an edit to the fixtures list is not missed because the
    reports tab happened to be untouched. Keys are sorted, because `batchGet` returns
    ranges in request order and a reordered request is not new data.
    """
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --- the part that talks to Google ---------------------------------------------------

def _service(credentials_path: str):
    """A Sheets client bound to the read-only scope. Imported lazily so the pure helpers
    above -- and their tests -- need neither the libraries nor a credential."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def tab_names(spreadsheet_id: str, credentials_path: str) -> list[str]:
    """Every tab in the spreadsheet, in sheet order."""
    meta = (_service(credentials_path).spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title")
            .execute())
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def fetch(spreadsheet_id: str, credentials_path: str,
          tabs: tuple[str, ...] = REQUIRED_TABS) -> dict[str, list[list]]:
    """Every required tab in ONE batchGet. Raises if a tab has been renamed.

    Failing here is deliberate. The alternative -- carrying on with whatever came back --
    stores a partial sync that looks exactly like a complete one, which is the failure
    mode this platform has been bitten by more than once.
    """
    missing = missing_tabs(tab_names(spreadsheet_id, credentials_path), tabs)
    if missing:
        raise RuntimeError(
            "The scouting sheet is missing tabs the platform reads: "
            f"{', '.join(missing)}. They have been renamed, deleted, or this is the "
            "wrong spreadsheet. Nothing was read.")

    result = (_service(credentials_path).spreadsheets().values()
              .batchGet(spreadsheetId=spreadsheet_id, ranges=list(tabs)).execute())
    # batchGet answers in request order, so zip rather than parsing the returned range
    # string -- which quotes titles containing spaces and would need unquoting.
    return {tab: vr.get("values", [])
            for tab, vr in zip(tabs, result.get("valueRanges", []))}


def main() -> None:
    """Report what the credential can see. Reads only; writes nothing, anywhere."""
    from lofc.config import settings

    if not settings.scout_sheet_configured:
        raise SystemExit(
            "Scouting sheet not configured. Set SCOUT_SHEET_ID in .env and place the "
            f"service-account key at {settings.scout_sheet_credentials}.")

    payload = fetch(settings.scout_sheet_id, settings.scout_sheet_credentials)
    for tab, values in payload.items():
        frame = frame_from_values(values)
        print(f"  {tab:24} {len(frame):5} rows x {frame.shape[1]:2} cols")
    print(f"digest: {payload_hash(payload)[:16]}")


if __name__ == "__main__":
    main()
