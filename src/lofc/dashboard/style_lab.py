"""Style lab: a workstation-only page to test and tune the playing-style rules before they
go live (owner, 2026-10-23). Shown only when SHOW_STYLE_LAB=true.

Thresholds move with sliders and the labels update at once; the checks that decided every
signal -- correlation with the rating (style must not be quality), quality metrics flagged --
are recomputed live, so a tweak cannot quietly undo them. Signal or style changes are made in
`model/styles.py` and need `python -m lofc.model.style_run` (about a minute).

The pure functions take a frame of rated players with their raw signals; `render` reads it.
"""

from __future__ import annotations

import pandas as pd

from lofc.model import styles as st


def _group_rows(frame: pd.DataFrame, group: str) -> pd.DataFrame:
    return frame[frame["position_group"].map(st.style_group) == group]


def build_lab(frame: pd.DataFrame, group: str, strong: float, floor: float) -> pd.DataFrame:
    """Every rated player in `group`: his label, tier and fit for every style."""
    rows = _group_rows(frame, group)
    rows = rows[rows["rankable"].astype(bool)] if "rankable" in rows.columns else rows
    if rows.empty:
        return pd.DataFrame()
    labels = st.assign_styles(st.signal_percentiles(rows), strong=strong, floor=floor)
    out = rows[st.KEY + ["player_name", "team_name", "objective_composite"]].merge(
        labels, on=st.KEY)
    return out.rename(columns={"player_name": "Player", "team_name": "Club",
                               "objective_composite": "Rating", "style_label": "Style"})


def summary(lab: pd.DataFrame) -> dict[str, int]:
    """Counts that always add up to every player in the lab."""
    style = lab["Style"] if not lab.empty else pd.Series(dtype=object)
    tier = lab["tier"] if not lab.empty else pd.Series(dtype=object)
    return {"Players": len(lab),
            "Strong": int((tier == "Strong").sum()),
            "Leans": int((tier == "Leans").sum()),
            st.NO_STYLE: int((style == st.NO_STYLE).sum()),
            st.NOT_ENOUGH: int((style == st.NOT_ENOUGH).sum())}


def signal_checks(frame: pd.DataFrame, group: str) -> pd.DataFrame:
    """One row per style signal: its correlation with the Performance rating (Spearman), and
    whether it is a declared quality metric. Style should sit near zero."""
    rows = _group_rows(frame, group)
    rows = rows[rows["rankable"].astype(bool)] if "rankable" in rows.columns else rows
    out = []
    for groups in [st.STYLES[group]]:
        for styles in groups.values():
            for style, sigs in styles.items():
                for sig in sigs:
                    r = (rows[sig].corr(rows["performance_band"], method="spearman")
                         if sig in rows.columns and len(rows) > 2 else float("nan"))
                    out.append({"Style": style, "Signal": st.SIGNAL_LABELS[sig],
                                "Correlation with rating": round(float(r), 2) if pd.notna(r) else None,
                                "Quality metric": "yes" if sig in st.QUALITY_SIGNALS else ""})
    return pd.DataFrame(out)


def render(frame: pd.DataFrame, league_names: dict, season_label: str) -> None:
    import streamlit as st_

    st_.subheader("Style lab")
    st_.caption(f"{season_label} · not visible to recruiters · rules in model/styles.py")
    c1, c2, c3, c4 = st_.columns([2, 2, 1, 1])
    group = c1.selectbox("Position", list(st.STYLES), key="lab_group")
    leagues = sorted({league_names.get(c, str(c)) for c in frame["competition_id"].unique()})
    league = c2.selectbox("League", ["All"] + leagues, key="lab_league")
    strong = c3.slider("Strong at", 50, 95, int(st.STRONG), 5, key="lab_strong")
    floor = c4.slider("Leans at", 30, 70, int(st.FLOOR), 5, key="lab_floor")

    lab = build_lab(frame, group, float(strong), float(floor))
    if lab.empty:
        st_.info("No rated players in this group.")
        return
    lab["League"] = lab["competition_id"].map(league_names)
    view = lab if league == "All" else lab[lab["League"] == league]

    s = summary(view)
    cols = st_.columns(len(s))
    for col, (name, n) in zip(cols, s.items()):
        col.metric(name, f"{n:,}" if name == "Players" else f"{n / max(s['Players'], 1):.0%}")

    styles = [x for g in st.STYLES[group].values() for x in g]
    pick = st_.selectbox("Show", ["Everyone"] + styles, key="lab_style")
    if pick != "Everyone":
        view = view[view["Style"].fillna("").str.contains(rf"(?:^|· |Leans ){pick}(?: ·|$)",
                                                          regex=True)]
    fit_cols = [f"fit.{x}" for x in styles]
    table = view[["Player", "Club", "League", "Rating", "Style"] + fit_cols].rename(
        columns={f"fit.{x}": x for x in styles}).sort_values("Rating", ascending=False)
    st_.dataframe(table, hide_index=True, width="stretch", height=520,
                  column_config={"Rating": st_.column_config.NumberColumn(format="%.2f"),
                                 **{x: st_.column_config.ProgressColumn(
                                     x, min_value=0, max_value=100, format="%.0f")
                                    for x in styles}})

    st_.markdown("##### Checks: style should not be quality")
    st_.dataframe(signal_checks(frame, group), hide_index=True, width="stretch")
