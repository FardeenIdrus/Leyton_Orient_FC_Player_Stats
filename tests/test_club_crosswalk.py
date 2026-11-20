"""Transfermarkt club name -> Impect squad (`model/club_crosswalk.py`, the list in
`reference/club_crosswalk.csv`). 41 of 149 Transfermarkt clubs carry a different name in
Impect ("Reading FC" / "FC Reading", "Rangers FC" / "Glasgow Rangers"). The file holds only
those; an exact name needs no row. A clash fails loudly; the real-data test lists any
Transfermarkt club left unmatched."""
import pandas as pd
import pytest

from lofc.model import club_crosswalk as cw

SQUADS = {958: "Oxford United", 966: "Leyton Orient", 1001: "FC Reading", 1002: "AFC Wrexham",
          1003: "Glasgow Rangers", 1004: "FC Everton U21", 1005: "Atlético Ottawa"}


def _cw(*rows):
    return pd.DataFrame([dict(zip(cw.COLUMNS, r)) for r in rows], columns=cw.COLUMNS)


@pytest.mark.parametrize("name,key", [
    ("Reading FC", "reading"), ("FC Reading", "reading"), ("AFC Wrexham", "wrexham"),
    ("Wrexham AFC", "wrexham"), ("Everton FC U21", "everton u21"),
    ("Atlético Ottawa", "atletico ottawa"), ("Brighton & Hove Albion", "brighton hove albion"),
    ("CF Montréal", "montreal")])
def test_normalise_drops_fc_afc_cf_and_folds_accents(name, key):
    assert cw.normalise(name) == key


def test_seed_matches_by_normalised_name_and_skips_exact_names():
    out = cw.seed(["Reading FC", "Wrexham AFC", "Oxford United", "Everton FC U21", "Rangers FC"],
                  SQUADS)
    got = {r.tm_club_name: (r.impect_squad_id, r.impect_team_name, r.match)
           for r in out.itertuples()}
    assert got == {"Reading FC": (1001, "FC Reading", "normalised"),
                   "Wrexham AFC": (1002, "AFC Wrexham", "normalised"),
                   "Everton FC U21": (1004, "FC Everton U21", "normalised")}
    # Rangers FC != Glasgow Rangers by any rule: left for a hand-made row, reported unmatched
    assert cw.unmatched(["Rangers FC", "Oxford United"], SQUADS, out) == ["Rangers FC"]


def test_seed_keeps_hand_made_rows():
    manual = _cw(("Rangers FC", 1003, "Glasgow Rangers", "manual", "Impect: Glasgow Rangers"))
    out = cw.seed(["Rangers FC", "Reading FC"], SQUADS, existing=manual)
    assert set(out["tm_club_name"]) == {"Rangers FC", "Reading FC"}
    assert out.set_index("tm_club_name").loc["Rangers FC", "match"] == "manual"


def test_seed_never_guesses_between_two_squads_with_one_normalised_name():
    squads = {1: "FC Reading", 2: "Reading AFC"}
    assert cw.seed(["Reading FC"], squads).empty


def test_resolve_gives_the_impect_name_exact_or_by_the_list():
    walk = _cw(("Reading FC", 1001, "FC Reading", "normalised", ""))
    got = cw.resolve(["Reading FC", "Leyton Orient", "Nowhere Town"], SQUADS.values(), walk)
    assert got == {"Reading FC": "FC Reading", "Leyton Orient": "Leyton Orient"}


@pytest.mark.parametrize("rows,msg", [
    ([("Reading FC", 1001, "FC Reading", "normalised", ""),
      ("Reading FC", 1002, "AFC Wrexham", "manual", "")], "more than once"),
    ([("Reading FC", 1001, "FC Reading", "normalised", ""),
      ("Reading", 1001, "FC Reading", "manual", "")], "two Transfermarkt clubs"),
    ([("Reading FC", None, "", "manual", "")], "impect_team_name"),
])
def test_a_bad_list_fails_loudly(tmp_path, rows, msg):
    path = tmp_path / "x.csv"
    _cw(*rows).to_csv(path, index=False)
    with pytest.raises(ValueError, match=msg):
        cw.load(path)


def test_a_row_that_clashes_with_an_exact_name_fails_loudly():
    walk = _cw(("Oxford Utd", 958, "Oxford United", "manual", ""))
    with pytest.raises(ValueError, match="two Transfermarkt clubs"):
        cw.resolve(["Oxford Utd", "Oxford United"], SQUADS.values(), walk)


def test_the_committed_list_loads():
    walk = cw.load()
    assert len(walk) >= 39
    assert walk.set_index("tm_club_name").loc["Reading FC", "impect_team_name"] == "FC Reading"
    assert walk.set_index("tm_club_name").loc["Rangers FC", "impect_team_name"] == "Glasgow Rangers"
    assert walk.set_index("tm_club_name").loc["Celtic FC", "impect_team_name"] == "Celtic Glasgow"


# --- real data: every Transfermarkt club resolves (skipped without a database) -----------
def test_every_transfermarkt_club_is_matched_on_the_real_data():
    try:
        from lofc.store.load import get_engine
        engine = get_engine()
        tm = pd.read_sql("SELECT DISTINCT club_name FROM transfermarkt_squads", engine)
        names = cw.impect_names(engine)
    except Exception:
        pytest.skip("no database")
    if tm.empty or not names:
        pytest.skip("no Transfermarkt or Impect clubs")
    left = cw.unmatched(tm["club_name"].tolist(), {i: n for i, n in enumerate(names)}, cw.load())
    assert left == [], f"Transfermarkt clubs with no Impect squad: {left}"
