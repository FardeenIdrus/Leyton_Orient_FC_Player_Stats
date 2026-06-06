"""Tests for valuation: name matching and the undervaluation signal. No database."""

import numpy as np
import pandas as pd

from lofc.model.valuation import _build_index, _match_one, _norm, value_players


def test_norm_strips_accents_and_punctuation():
    # Punctuation becomes a space (applied to both sides, so matching stays consistent).
    assert _norm("N'Golo Kanté") == "n golo kante"
    assert _norm("Sergio Agüero") == "sergio aguero"


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
