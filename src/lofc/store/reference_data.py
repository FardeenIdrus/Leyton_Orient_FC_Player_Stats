"""Build the two club reference files in data/reference/.

These are constructed, documented stand-ins, not official Leyton Orient documents.
Provenance:
  - Wage ceilings: the SHAPE is anchored in facts (the EFL rule that League One wages
    are capped at 50% of turnover, and LOFC's ~£7.7m turnover from published accounts,
    giving a ~£3.5-4m wage pool). The TOP figure (~£6.5k/week) matches LOFC top-earner
    estimates from Capology / SalarySport (2024/25-2025/26). The position and age shape
    is a reasoned assumption (no public EFL positional wage data exists).
  - Identity profiles: entirely a football-reasoning construction (a hard-working,
    progressive, press-resistant identity). Not a club document.
Both are clearly labelled and swappable for the club's real files. See
data/reference/README.md for the full provenance.

Run with:  python -m lofc.store.reference_data
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from lofc.config import settings

AGE_BANDS = ["U21", "21-24", "25-29", "30-32", "33+"]

# Weekly wage ceiling (GBP) per position group and age band. Peaks at 25-29,
# attackers highest, goalkeepers/full-backs lowest, whole grid under the cap.
WAGE_CEILINGS: dict[str, dict[str, int]] = {
    "Goalkeeper":     {"U21": 1500, "21-24": 3000, "25-29": 4500, "30-32": 4000, "33+": 2750},
    "Centre Back":    {"U21": 1750, "21-24": 3250, "25-29": 5000, "30-32": 4500, "33+": 3000},
    "Full Back":      {"U21": 1750, "21-24": 3000, "25-29": 4500, "30-32": 4000, "33+": 2750},
    "Defensive Mid":  {"U21": 1750, "21-24": 3250, "25-29": 5000, "30-32": 4500, "33+": 3000},
    "Central Mid":    {"U21": 2000, "21-24": 3750, "25-29": 5500, "30-32": 5000, "33+": 3250},
    "Winger":         {"U21": 2250, "21-24": 4250, "25-29": 6000, "30-32": 5250, "33+": 3500},
    "Attacking Mid":  {"U21": 2250, "21-24": 4250, "25-29": 6000, "30-32": 5250, "33+": 3500},
    "Centre Forward": {"U21": 2500, "21-24": 4750, "25-29": 6500, "30-32": 5750, "33+": 3750},
}

BAND_NOTES = {
    "U21": "U21 academy graduates are EFL wage-cap exempt (cheaper and outside the budget).",
    "21-24": "Pre-peak, rising value.",
    "25-29": "Prime years; ceiling anchored to LOFC top earners ~£6.5k/week (estimate).",
    "30-32": "Just past peak.",
    "33+": "Veteran; reduced ceiling.",
}

# Per position: (metric column, weight, minimum percentile floor or None).
# Weights sum to 1.0 per position. min floor drives the Phase 7 on-profile filter;
# weight drives the Phase 4 composite score. Identity: progressive and hard-working.
IDENTITY_PROFILES: dict[str, list[tuple[str, float, float | None]]] = {
    "Goalkeeper": [
        ("save_pct", 0.45, 0.50), ("gk_saves_p90", 0.20, None),
        ("pass_completion_pct", 0.20, 0.40), ("passes_p90", 0.15, None),
    ],
    "Centre Back": [
        ("interceptions_p90", 0.20, 0.45), ("clearances_p90", 0.15, None),
        ("blocks_p90", 0.10, None), ("ball_recoveries_p90", 0.10, None),
        ("tackles_p90", 0.15, None), ("pass_completion_pct", 0.15, 0.50),
        ("progressive_passes_p90", 0.15, None),
    ],
    "Full Back": [
        ("progressive_passes_p90", 0.18, None), ("passes_into_final_third_p90", 0.15, None),
        ("passes_into_box_p90", 0.15, None), ("progressive_carries_p90", 0.15, None),
        ("tackles_p90", 0.15, 0.40), ("interceptions_p90", 0.12, None),
        ("pressures_p90", 0.10, None),
    ],
    "Defensive Mid": [
        ("interceptions_p90", 0.18, 0.45), ("tackles_p90", 0.15, 0.45),
        ("ball_recoveries_p90", 0.15, None), ("pressures_p90", 0.15, None),
        ("pass_completion_pct", 0.17, 0.50), ("progressive_passes_p90", 0.20, None),
    ],
    "Central Mid": [
        ("progressive_passes_p90", 0.18, None), ("passes_into_final_third_p90", 0.15, None),
        ("xa_p90", 0.12, None), ("key_passes_p90", 0.12, None),
        ("progressive_carries_p90", 0.13, None), ("pressures_p90", 0.15, None),
        ("pass_completion_pct", 0.15, None),
    ],
    "Winger": [
        ("xa_p90", 0.18, None), ("key_passes_p90", 0.15, None),
        ("dribbles_completed_p90", 0.17, 0.50), ("progressive_carries_p90", 0.15, None),
        ("passes_into_box_p90", 0.13, None), ("np_xg_p90", 0.12, None),
        ("pressures_p90", 0.10, None),
    ],
    "Attacking Mid": [
        ("xa_p90", 0.20, None), ("key_passes_p90", 0.18, None),
        ("np_xg_p90", 0.15, None), ("passes_into_box_p90", 0.15, None),
        ("progressive_passes_p90", 0.12, None), ("dribbles_completed_p90", 0.10, None),
        ("pressures_p90", 0.10, None),
    ],
    "Centre Forward": [
        ("np_xg_p90", 0.28, 0.55), ("np_goals_p90", 0.20, None),
        ("shots_p90", 0.15, None), ("xa_p90", 0.10, None),
        ("passes_into_box_p90", 0.10, None), ("pressures_p90", 0.17, None),
    ],
}


# --- Modelled player wage estimates (for the Phase 7 wage gate) ----------------------
# A player's estimated weekly wage = league tier anchor (top / mid / squad, prime age)
# x position shape x age multiplier, with a low/high band expressing uncertainty.
# Anchored per league to published wage reporting; every league cites its sources.
# This is a MODELLED stand-in, never derived from market value, and is replaced
# wholesale when real wage data arrives (the gate is a screening prior: actual asking
# wages come from agents). Performance tier = terciles of performance score within
# position and league.
PERFORMANCE_TIERS = ["Top", "Mid", "Squad"]

# Per-league weekly GBP anchors for a PRIME-AGE (25-29) player at each tier.
# "Mid" is the reported league average scaled to its prime-age equivalent (the
# all-age average sits ~25% below a prime-age one under our age curve).
WAGE_LEAGUE_ANCHORS: dict[int, dict] = {
    # Demo trio: top-flight 2024 levels (Capology/SalarySport orders of magnitude).
    2:  {"label": "Premier League (demo)", "Top": 95000, "Mid": 40000, "Squad": 15000,
         "source": "modelled (Capology/SalarySport anchored, top-flight 2024 levels)"},
    11: {"label": "La Liga (demo)", "Top": 90000, "Mid": 38000, "Squad": 14000,
         "source": "modelled (Capology/SalarySport anchored, top-flight 2024 levels)"},
    12: {"label": "Serie A (demo)", "Top": 85000, "Mid": 36000, "Squad": 13500,
         "source": "modelled (Capology/SalarySport anchored, top-flight 2024 levels)"},
    # EFL targets: anchored to 2025/26 reporting.
    # Championship: average ~GBP 10.5-11k/wk (William Hill / Capology 2025/26); the
    # lowest squads average ~GBP 4k; top earners reach GBP 40-90k (the extreme tail).
    # Re-anchored down 30% after the wage_check reconciliation flagged +57% vs
    # payroll totals: the published average reflects recorded regulars more than
    # squad-wide pay at this tier, so the prime-age uplift over-corrected.
    3:  {"label": "Championship", "Top": 32000, "Mid": 10000, "Squad": 3500,
         "source": "modelled (Capology/William Hill 2025/26 Championship reporting, reconciled)"},
    # League One: average GBP 4.1k/wk over 640 recorded salaries (Capology via
    # 888sport, 2025/26); the top-50 earners all clear GBP 8.4k/wk.
    4:  {"label": "League One", "Top": 12000, "Mid": 5500, "Squad": 2400,
         "source": "modelled (Capology/888sport 2025/26 League One reporting)"},
    # League Two: average ~GBP 2k/wk; the top-100 earners average ~GBP 3.3k/wk
    # (888sport/FootyStats 2025/26).
    5:  {"label": "League Two", "Top": 5000, "Mid": 2700, "Squad": 1200,
         "source": "modelled (888sport/FootyStats 2025/26 League Two reporting)"},
    # National League: mostly professional; averages ~GBP 1-1.5k/wk with the
    # better-paid full-time squads higher (William Hill 2025/26).
    65: {"label": "National League", "Top": 3500, "Mid": 1700, "Squad": 650,
         "source": "modelled (William Hill 2025/26 National League reporting)"},
}

# Positional differentials, mean ~1.0. The top-flight spread (attackers paid ~2x
# keepers) is compressed for this grid: lower leagues show flatter pay by position.
# The shape itself is an assumption: no public positional wage data exists below
# the top flight.
WAGE_POSITION_SHAPE = {
    "Centre Forward": 1.20, "Winger": 1.11, "Attacking Mid": 1.08, "Central Mid": 1.00,
    "Defensive Mid": 0.95, "Centre Back": 0.92, "Full Back": 0.85, "Goalkeeper": 0.82,
}
WAGE_AGE_MULTIPLIER = {"U21": 0.45, "21-24": 0.75, "25-29": 1.0, "30-32": 0.90, "33+": 0.65}
# Uncertainty band around the central estimate. Asymmetric: real asks overshoot the
# model (signing-on fees, agent demands) more often than they undershoot.
WAGE_BAND = (0.70, 1.40)


def _round_wage(value: float) -> int:
    """Round to a sensible quote: GBP 50 steps below 10k/wk, 500 above."""
    step = 50 if value < 10_000 else 500
    return int(round(value / step) * step)


def build_wage_estimates() -> pd.DataFrame:
    rows = []
    for comp_id, anchors in WAGE_LEAGUE_ANCHORS.items():
        for position, shape in WAGE_POSITION_SHAPE.items():
            for band in AGE_BANDS:
                for tier in PERFORMANCE_TIERS:
                    wage = anchors[tier] * shape * WAGE_AGE_MULTIPLIER[band]
                    rows.append({
                        "competition_id": comp_id,
                        "position_group": position,
                        "age_band": band,
                        "performance_tier": tier,
                        "estimated_weekly_wage_gbp": _round_wage(wage),
                        "wage_low_gbp": _round_wage(wage * WAGE_BAND[0]),
                        "wage_high_gbp": _round_wage(wage * WAGE_BAND[1]),
                        "source": anchors["source"],
                    })
    return pd.DataFrame(rows)


def build_wage_framework() -> pd.DataFrame:
    rows = []
    for position, by_band in WAGE_CEILINGS.items():
        for band in AGE_BANDS:
            rows.append({
                "position_group": position,
                "age_band": band,
                "weekly_wage_ceiling_gbp": by_band[band],
                "notes": BAND_NOTES[band],
            })
    return pd.DataFrame(rows)


def build_identity_profiles() -> pd.DataFrame:
    rows = []
    for position, metrics in IDENTITY_PROFILES.items():
        top_weight = max(w for _, w, _ in metrics)
        for metric, weight, floor in metrics:
            if floor is not None:
                note = "Must-have floor for an on-profile player."
            elif weight == top_weight:
                note = "Primary attribute for this position."
            else:
                note = ""
            rows.append({
                "position_group": position,
                "metric": metric,
                # Stored on the 0-100 percentile scale (0.55 -> 55) to match player_percentiles.
                "min_percentile": round(floor * 100, 1) if floor is not None else None,
                "weight": weight,
                "notes": note,
            })
    return pd.DataFrame(rows)


def main() -> None:
    out = Path(settings.reference_data_dir)
    out.mkdir(parents=True, exist_ok=True)

    wage = build_wage_framework()
    identity = build_identity_profiles()
    wage_estimates = build_wage_estimates()
    wage.to_csv(out / "wage_framework.csv", index=False)
    identity.to_csv(out / "identity_profiles.csv", index=False)
    wage_estimates.to_csv(out / "wage_estimates.csv", index=False)

    # Weights must sum to 1.0 per position, or the Phase 4 score is mis-scaled.
    sums = identity.groupby("position_group")["weight"].sum().round(3)
    assert (sums == 1.0).all(), f"identity weights must sum to 1.0 per position: {sums.to_dict()}"

    print(f"Wrote wage_framework.csv ({len(wage)} rows), identity_profiles.csv "
          f"({len(identity)} rows), wage_estimates.csv ({len(wage_estimates)} rows) to {out}/")
    print("Identity weights per position all sum to 1.0:", sums.to_dict())


if __name__ == "__main__":
    main()
