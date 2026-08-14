"""Tests for valuation: name matching and the undervaluation signal. No database."""

import numpy as np
import pandas as pd

from lofc.model.valuation import (_build_index, _match_one, _norm,
                                  match_players_efl, value_players)


def test_norm_strips_accents_and_punctuation():
    # Apostrophes are DROPPED (not spaced); other punctuation becomes a space.
    assert _norm("N'Golo Kanté") == "ngolo kante"
    assert _norm("Sergio Agüero") == "sergio aguero"


def test_norm_apostrophe_glyphs_normalise_identically():
    # The bug this fixes: curly (U+2019) and straight (U+0027) apostrophes must
    # produce the SAME normalised name, or real players fail to match on it.
    assert _norm("Mark O’Mahony") == _norm("Mark O'Mahony") == "mark omahony"
    assert _norm("Max O’Leary") == _norm("Max O'Leary") == "max oleary"


def _tm(names):
    tm = pd.DataFrame({"nname": [_norm(n) for n in names], "value_eur": [1e7] * len(names)})
    tm["tokens"] = tm["nname"].str.split().map(set)
    return tm


def test_match_exact_token_and_miss():
    tm = _tm(["Neymar Jr", "Lionel Messi", "Francis Coquelin"])
    exact, token_index = _build_index(tm)

    assert _match_one("Lionel Messi", tm, exact, token_index) == 1   # exact
    assert _match_one("Neymar", tm, exact, token_index) == 0         # short name -> token subset
    assert _match_one("Coquelin", tm, exact, token_index) == 2       # surname token subset
    assert _match_one("Zlatan Ibrahimovic", tm, exact, token_index) is None  # no match


def test_collision_keeps_higher_value_player():
    tm = _tm(["Juanfran", "Juanfran"])
    tm.loc[1, "value_eur"] = 5e7   # the more valuable namesake
    exact, _ = _build_index(tm)
    assert exact["juanfran"] == 1


def _efl_metrics_row(**overrides):
    row = {"player_id": 1, "competition_id": 4, "season_id": 318,
           "player_name": "Josh Stokes", "birth_date": "2004-04-29",
           "position_group": "Attacking Mid", "minutes": 1500,
           "competition_name": "League One", "rankable": True}
    row.update(overrides)
    return row


def _efl_scrape(rows):
    efl = pd.DataFrame(rows).rename(columns={"market_value_eur": "value_eur"})
    efl["nname"] = efl["player_name"].map(_norm)
    efl["tokens"] = efl["nname"].str.split().map(set)
    efl["birth_date"] = pd.to_datetime(efl["date_of_birth"])
    return efl.reset_index(drop=True)


def test_efl_cross_league_dob_match_catches_loanee():
    # The player appears in League One (comp 4) but his Transfermarkt value is
    # listed under the parent club in the Championship (comp 3) — the Josh
    # Stokes case. Exact birth date + name across leagues must still match.
    metrics = pd.DataFrame([_efl_metrics_row()])
    efl = _efl_scrape([{"player_name": "Josh Stokes", "competition_id": 3,
                        "date_of_birth": "2004-04-29", "market_value_eur": 400_000.0}])

    matched, unmatched = match_players_efl(metrics, efl)

    assert unmatched == []
    assert len(matched) == 1
    assert matched.at[0, "player_id"] == 1
    assert matched.at[0, "market_value_eur"] == 400_000.0


def test_efl_cross_league_requires_name_agreement():
    # Same birth date in another league but a completely different name must
    # NOT match: birth-date coincidences across four leagues are real.
    metrics = pd.DataFrame([_efl_metrics_row()])
    efl = _efl_scrape([{"player_name": "Kwame Boateng", "competition_id": 3,
                        "date_of_birth": "2004-04-29", "market_value_eur": 900_000.0}])

    matched, unmatched = match_players_efl(metrics, efl)

    assert len(matched) == 0
    assert unmatched == ["Josh Stokes (League One)"]


def test_efl_in_league_match_still_wins_over_cross_league():
    # A same-league entry takes priority: the cross-league pass only fires when
    # the in-league passes found nothing.
    metrics = pd.DataFrame([_efl_metrics_row()])
    efl = _efl_scrape([
        {"player_name": "Josh Stokes", "competition_id": 4,   # own league
         "date_of_birth": "2004-04-29", "market_value_eur": 350_000.0},
        {"player_name": "Josh Stokes", "competition_id": 3,   # other league namesake
         "date_of_birth": "2004-04-29", "market_value_eur": 400_000.0},
    ])

    matched, _ = match_players_efl(metrics, efl)

    assert matched.at[0, "market_value_eur"] == 350_000.0


def test_underpriced_player_is_flagged_as_undervalued():
    # 60 players whose value rises with one performance feature, plus one deliberately
    # underpriced star: high performance, but priced like a weak player.
    x = np.linspace(10, 100, 60)
    log_value = 12.0 + 0.03 * x          # clean performance -> value relationship
    underpriced = 55                      # high performance (x ~ 92)...
    log_value[underpriced] = 12.0 + 0.03 * 15   # ...but priced like a low performer

    features = pd.DataFrame({"perf": x, "perf2": x * 0.5})
    fair_value, report = value_players(features, log_value)

    actual = np.expm1(log_value)
    # The model should price the underpriced player well above their actual value.
    assert fair_value[underpriced] > 2 * actual[underpriced]
    assert report["r2_log"] > 0.6   # the clean signal fits well despite the outlier
