"""Generate the default shortlists and write them to the shortlists table.

The shortlist logic in filters.py is parameterised (budget, wage ceiling), so the Phase 8
dashboard calls it live with slider values. This writes a default snapshot.

Run with:  python -m lofc.constrain.run
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import delete

from lofc.constrain.filters import DEFAULT_TRANSFER_BUDGET_EUR, generate
from lofc.store.load import _records, _upsert, get_engine
from lofc.store.models import Shortlist

COLUMNS = [
    "player_id", "competition_id", "season_id", "position_group", "rank",
    "affordable_fee", "affordable_wage", "wage_marginal", "on_profile", "is_near_miss",
    "performance_score", "fit_score", "undervaluation_pct", "market_value_eur",
    "estimated_weekly_wage_gbp", "wage_low_gbp", "wage_high_gbp",
    "wage_ceiling_gbp", "transfer_budget_eur",
]


def main() -> None:
    engine = get_engine()
    shortlists = generate(engine, DEFAULT_TRANSFER_BUDGET_EUR)

    # Integer wage columns must not carry floats into the integer DB columns.
    for col in ["estimated_weekly_wage_gbp", "wage_low_gbp", "wage_high_gbp", "wage_ceiling_gbp"]:
        shortlists[col] = shortlists[col].round().astype("Int64")

    with engine.begin() as conn:
        conn.execute(delete(Shortlist.__table__))  # fully derived; clear then insert
    n = _upsert(engine, Shortlist.__table__, _records(shortlists[COLUMNS]),
                ["player_id", "competition_id", "season_id"])

    qualifying = int((~shortlists["is_near_miss"]).sum())
    print(f"shortlists: wrote {n} rows ({qualifying} qualifying, {n - qualifying} near-miss) "
          f"at transfer budget EUR {DEFAULT_TRANSFER_BUDGET_EUR:,}")
    _spot_check(shortlists)


def _spot_check(shortlists: pd.DataFrame) -> None:
    # build_candidates already attached player_name / team_name.
    for position in ["Centre Forward", "Defensive Mid"]:
        rows = shortlists[shortlists["position_group"] == position].sort_values("rank").head(5)
        tag = "near-misses (nobody passed both gates at this budget)" if rows["is_near_miss"].all() else "shortlist"
        print(f"\n{position} - {tag}:")
        print(rows[["rank", "player_name", "team_name", "fit_score", "market_value_eur",
                    "estimated_weekly_wage_gbp", "wage_ceiling_gbp", "on_profile"]].to_string(index=False))


if __name__ == "__main__":
    main()
