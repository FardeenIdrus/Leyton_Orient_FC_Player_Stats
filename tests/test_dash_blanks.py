"""dash_blanks: the display copy of a table in which a missing value reads "—", because
st.dataframe draws every None/NaN/NaT as a grey "None"."""
import numpy as np
import pandas as pd

from lofc.dashboard.formatting import dash_blanks


def _frame():
    return pd.DataFrame({
        "Name": ["A", None, np.nan],
        "Rating": [4.5, np.nan, 3.0],
        "Mins": [900.0, np.nan, -3.0],
        "Ends": pd.to_datetime(["2027-06-30", None, "2026-01-01"]),
        "Flag": [True, False, True],
        "Styles": [["x"], None, ["y", "z"]],
    })


def test_text_missing_becomes_dash():
    out = dash_blanks(_frame())
    assert list(out["Name"]) == ["A", "—", "—"]


def test_listed_number_formatted_with_dash():
    out = dash_blanks(_frame(), {"Rating": "{:.2f}"})
    assert list(out["Rating"]) == ["4.50", "—", "3.00"]


def test_listed_date_formatted_with_dash():
    out = dash_blanks(_frame(), {"Ends": "%b %Y"})
    assert list(out["Ends"]) == ["Jun 2027", "—", "Jan 2026"]


def test_unlisted_numeric_untouched_and_list_cells_kept():
    frame = _frame()
    out = dash_blanks(frame, {"Rating": "{:.2f}"})
    assert out["Mins"].isna().sum() == 1 and out["Mins"].dtype == frame["Mins"].dtype
    assert out["Flag"].dtype == bool
    assert out["Styles"].iloc[0] == ["x"] and out["Styles"].iloc[1] == "—"


def test_input_not_mutated_and_index_kept():
    frame = _frame()
    frame.index = [5, 6, 7]
    dash_blanks(frame, {"Rating": "{:.2f}"})
    assert frame["Rating"].isna().sum() == 1 and frame["Name"].isna().sum() == 2
    assert list(dash_blanks(frame).index) == [5, 6, 7]


def test_nullable_string_dtype_and_none_in_date_only_frame():
    frame = pd.DataFrame({"S": pd.array(["a", None], dtype="string")})
    assert list(dash_blanks(frame)["S"]) == ["a", "—"]


def test_squad_display_has_no_blank_in_converted_columns():
    from lofc.dashboard.tabs import squads
    t = pd.DataFrame({c: [None, None] for c in squads.DISPLAY_COLUMNS}, dtype=object)
    t["Age"] = [26.78, np.nan]
    t["This season"] = [4.1, np.nan]
    t["Minutes"] = [90.0, np.nan]
    out = squads.squad_display(t)
    assert list(out["Age"]) == ["26.8", "—"]
    for c in squads.DISPLAY_COLUMNS:
        if c not in ("Minutes", "Months left", "Contract to", "Loan ends"):
            assert not out[c].isna().any(), c
    assert out["Minutes"].isna().sum() == 1


def test_scout_report_display_has_no_blank():
    import datetime as dt
    from lofc.dashboard.tabs import scout_reports as sr
    t = pd.DataFrame({
        "Watched": [dt.date(2026, 8, 18), pd.NaT], "Player": ["A", "B"],
        "Club": [None, "X"], "Rating": [3.456, np.nan], "This season": [np.nan, 4.0],
        sr.MODEL_VIEW: ["Agrees", None]})
    out = sr.report_display(t)
    assert list(out["Watched"]) == ["2026-08-18", "—"]
    assert list(out["Rating"]) == ["3.46", "—"]
    assert list(out["This season"]) == ["—", "4.00"]
    assert not out.isna().any().any()


def test_ranked_table_text_cells_have_no_blank():
    from lofc.dashboard.tabs import players
    t = pd.DataFrame({"Player": ["A", "B"], "Club": ["X", None], "Mins": [90.0, np.nan],
                      "Composite": [4.0, np.nan]})
    shown = players.styled_ratings(t, ["Composite"]).data
    assert list(shown["Club"]) == ["X", "—"] and list(shown["Composite"]) == ["4.00", "—"]


def test_injury_table_ongoing_spell_reads_dash():
    from lofc.dashboard import evidence
    f = pd.DataFrame({"season_label": ["25/26"], "injury_type_raw": ["Knock"],
                      "injury_category": [None], "date_from": [pd.Timestamp("2026-01-02")],
                      "date_until": [pd.NaT], "days_out": [3.0], "games_missed": [1.0],
                      "source": ["transfermarkt"]})
    out = evidence._format_table(f)
    assert out["Until"].iloc[0] == "—" and out["From"].iloc[0] == "2026-01-02"
    assert out["Category"].iloc[0] == "—"


def test_squad_dates_stay_dates_so_they_sort_by_date():
    # prepare() gives python date objects (.dt.date). Formatting them as text showed the
    # literal "%b %Y" and would sort alphabetically; they must stay dates (DateColumn).
    import datetime as dt
    from lofc.dashboard.tabs import squads
    t = pd.DataFrame({c: [None, None] for c in squads.DISPLAY_COLUMNS}, dtype=object)
    t["Contract to"] = [dt.date(2027, 6, 30), None]
    t["Loan ends"] = [dt.date(2026, 5, 31), None]
    out = squads.squad_display(t)
    for c in ("Contract to", "Loan ends"):
        assert "%b %Y" not in out[c].astype(str).tolist(), c
        assert isinstance(out[c].iloc[0], dt.date), c


def test_date_spec_applies_to_python_date_objects():
    import datetime as dt
    frame = pd.DataFrame({"D": [dt.date(2026, 5, 31), None]}, dtype=object)
    assert list(dash_blanks(frame, {"D": "%Y-%m-%d"})["D"]) == ["2026-05-31", "—"]
