"""Leyton Orient recruitment dashboard (Streamlit).

A clean, on-brand front end over the model outputs in Postgres. A recruiter picks a
position, sets a budget, and reads a ranked shortlist of affordable, on-profile players,
then drills into a profile, compares players, or reads how the pipeline works. The
sliders call the Phase 7 filter live.

Run via docker compose (the `dashboard` service) at http://localhost:8501.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine

from lofc.config import settings
from lofc.constrain.filters import apply_gates, build_candidates
from lofc.model.score import POSITION_ROLE, ROLE_METRICS

RED = "#C8102E"
DARK = "#1A1A1A"
COMPARE_COLOURS = [RED, "#2B2B2B", "#1F77B4"]
NONE_OPTION = "— none —"
LOGO = Path("assets/logo.png")

POSITION_ORDER = ["Goalkeeper", "Centre Back", "Full Back", "Defensive Mid",
                  "Central Mid", "Winger", "Attacking Mid", "Centre Forward"]

LABELS = {
    "np_xg_p90": "Non-pen xG", "np_goals_p90": "Non-pen goals", "goals_p90": "Goals",
    "xg_p90": "xG", "shots_p90": "Shots", "assists_p90": "Assists", "xa_p90": "Expected assists",
    "key_passes_p90": "Key passes", "passes_p90": "Passes", "passes_completed_p90": "Completed passes",
    "progressive_passes_p90": "Progressive passes", "passes_into_final_third_p90": "Passes into final third",
    "passes_into_box_p90": "Passes into box", "dribbles_p90": "Dribbles",
    "dribbles_completed_p90": "Dribbles completed", "carries_p90": "Carries",
    "progressive_carries_p90": "Progressive carries", "pressures_p90": "Pressures",
    "tackles_p90": "Tackles", "interceptions_p90": "Interceptions", "blocks_p90": "Blocks",
    "clearances_p90": "Clearances", "ball_recoveries_p90": "Ball recoveries", "gk_saves_p90": "Saves",
    "pass_completion_pct": "Pass accuracy", "dribble_success_pct": "Dribble success", "save_pct": "Save %",
}


# --- data access (cached) -------------------------------------------------------------
@st.cache_resource
def get_engine():
    return create_engine(settings.database_url)


@st.cache_data(ttl=600)
def load_candidates(wage_ceiling_multiplier: float) -> pd.DataFrame:
    engine = get_engine()
    candidates = build_candidates(engine, wage_ceiling_multiplier)
    archetypes = pd.read_sql("SELECT player_id, competition_id, season_id, cluster_label "
                             "FROM archetypes", engine)
    return candidates.merge(archetypes, on=["player_id", "competition_id", "season_id"], how="left")


@st.cache_data(ttl=600)
def load_percentiles() -> pd.DataFrame:
    return pd.read_sql("SELECT player_id, metric, percentile FROM player_percentiles", get_engine())


@st.cache_data(ttl=600)
def headline() -> tuple[int, int]:
    """Top-level counts for the KPI strip: players analysed and leagues covered."""
    engine = get_engine()
    players = pd.read_sql("SELECT COUNT(*) AS c FROM player_season_metrics", engine)["c"][0]
    leagues = pd.read_sql("SELECT COUNT(DISTINCT competition_id) AS c FROM player_season_metrics", engine)["c"][0]
    return int(players), int(leagues)


def percentile_vector(percentiles: pd.DataFrame, player_id: int, metrics: list[str]) -> list[float]:
    series = percentiles[percentiles["player_id"] == player_id].set_index("metric")["percentile"]
    return [float(series.get(m, 0.0)) for m in metrics]


# --- charts ---------------------------------------------------------------------------
# Charts are read-only: drag-to-zoom is disabled and the toolbar hidden (PLOTLY_CONFIG),
# so a stray mouse drag can't turn the chart into a zoom box.
PLOTLY_CONFIG = {"displayModeBar": False, "staticPlot": False}


def bar_chart(metrics: list[str], values: list[float]) -> go.Figure:
    labels = [LABELS.get(m, m) for m in metrics]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h", marker_color=RED,
        text=[f"{v:.0f}" for v in values], textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: %{x:.0f} percentile<extra></extra>",
    ))
    fig.update_layout(
        xaxis=dict(range=[0, 100], title="Percentile vs positional peers", showgrid=True, gridcolor="#ECECEC"),
        yaxis=dict(autorange="reversed"), height=max(280, 34 * len(metrics)), dragmode=False,
        margin=dict(l=10, r=30, t=10, b=10), plot_bgcolor="white", paper_bgcolor="white",
    )
    return fig


def radar_chart(traces: list[tuple[str, list[float]]], metrics: list[str]) -> go.Figure:
    labels = [LABELS.get(m, m) for m in metrics]
    fig = go.Figure()
    for i, (name, values) in enumerate(traces):
        colour = COMPARE_COLOURS[i % len(COMPARE_COLOURS)]
        fig.add_trace(go.Scatterpolar(
            r=values + [values[0]], theta=labels + [labels[0]], fill="toself", name=name,
            line_color=colour, opacity=0.55 if len(traces) > 1 else 0.8,
            hovertemplate="%{theta}: %{r:.0f} percentile<extra>" + name + "</extra>",
        ))
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 100], tickfont_size=9)),
        showlegend=len(traces) > 1, legend=dict(orientation="h", y=-0.08),
        height=470, margin=dict(l=50, r=50, t=40, b=40), dragmode=False,
    )
    return fig


# --- layout ---------------------------------------------------------------------------
def style() -> None:
    st.markdown(
        f"""
        <style>
          /* Hide only the hamburger, footer and Deploy button. Crucially, do NOT hide the
             toolbar/header: the control that re-opens a collapsed sidebar lives there. */
          #MainMenu, footer {{visibility: hidden;}}
          [data-testid="stAppDeployButton"] {{display: none;}}
          [data-testid="stSidebarCollapsedControl"] {{visibility: visible !important; opacity: 1 !important;}}
          .block-container {{padding-top: 2.5rem; max-width: 1180px;}}
          .lofc-title {{font-size: 2.1rem; font-weight: 800; color: {RED}; line-height: 1.1; margin-bottom: .15rem;}}
          .lofc-sub {{font-size: .9rem; color: #6b6b6b; letter-spacing: .1em; text-transform: uppercase;}}
          .brand-rule {{border: none; border-top: 3px solid {RED}; margin: .6rem 0 1.2rem 0;}}
          .stTabs [data-baseweb="tab"] {{font-weight: 600;}}
          .stTabs [aria-selected="true"] {{color: {RED};}}
          [data-testid="stMetricValue"] {{color: {RED}; font-weight: 700;}}
          [data-testid="stMetricLabel"] {{text-transform: uppercase; letter-spacing: .04em; font-size: .72rem; color: #6b6b6b;}}
          /* Keep dropdown menus crisp and fully opaque (some browsers render them blurred). */
          [data-baseweb="popover"], [data-baseweb="menu"], [role="listbox"] {{
            backdrop-filter: none !important; -webkit-backdrop-filter: none !important; background-color: #ffffff !important;
          }}
          html, body {{ -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def header() -> None:
    left, right = st.columns([1, 8], vertical_alignment="center")
    with left:
        if LOGO.exists():
            st.image(str(LOGO), width=84)
    with right:
        st.markdown('<div class="lofc-title">Leyton Orient FC</div>'
                    '<div class="lofc-sub">Recruitment Intelligence</div>', unsafe_allow_html=True)
    st.markdown('<hr class="brand-rule">', unsafe_allow_html=True)


def synced_budget() -> float:
    """A transfer-budget control with a slider and a number box kept in sync. Returns euros."""
    st.session_state.setdefault("budget_slider", 5.0)
    st.session_state.setdefault("budget_number", 5.0)

    def from_slider():
        st.session_state.budget_number = st.session_state.budget_slider

    def from_number():
        st.session_state.budget_slider = st.session_state.budget_number

    st.sidebar.slider("Transfer budget (€m)", 0.0, 150.0, step=0.5,
                      key="budget_slider", on_change=from_slider)
    st.sidebar.number_input("…or type it (€m)", 0.0, 150.0, step=0.5,
                            key="budget_number", on_change=from_number)
    return st.session_state.budget_slider * 1_000_000


def main() -> None:
    st.set_page_config(page_title="LOFC Recruitment Intelligence",
                       page_icon=str(LOGO) if LOGO.exists() else None,
                       layout="wide", initial_sidebar_state="expanded")
    style()
    header()

    st.sidebar.header("Filters")
    position = st.sidebar.selectbox("Position", POSITION_ORDER,
                                    index=POSITION_ORDER.index("Centre Forward"))
    budget_eur = synced_budget()
    wage_multiplier = st.sidebar.slider(
        "Wage budget (× club ceiling)", 0.5, 25.0, 1.0, step=0.5,
        help="1× = Leyton Orient's modelled weekly-wage ceiling for each position and age band. "
             "Slide up to model a bigger wage budget and see who that would make affordable. "
             "On this top-flight demo data the real (1×) ceiling is far below most players' wages, "
             "so this is the slider that opens up the shortlist. Wages are modelled estimates.")
    min_minutes = st.sidebar.slider("Minimum minutes", 450, 3500, 450, step=90)

    candidates = load_candidates(wage_multiplier)
    percentiles = load_percentiles()

    pool = apply_gates(candidates[(candidates["position_group"] == position) &
                                  (candidates["minutes"] >= min_minutes)], budget_eur)
    pool = pool.sort_values("fit_score", ascending=False).reset_index(drop=True)
    metrics = list(ROLE_METRICS[POSITION_ROLE[position]])

    _kpi_strip(pool)
    shortlist_tab, profile_tab, compare_tab, method_tab = st.tabs(
        ["Shortlist", "Player profile", "Compare", "Methodology"])
    _shortlist(shortlist_tab, pool, position)
    _profile(profile_tab, pool, percentiles, metrics)
    _compare(compare_tab, pool, percentiles, metrics)
    _methodology(method_tab)

    st.caption("Demonstrated on StatsBomb open data (2015/16). Player market values are real (Transfermarkt); "
               "wages and the club identity profile are clearly-labelled modelled stand-ins, swappable for the "
               "club's real data with no code change.")


def _kpi_strip(pool: pd.DataFrame) -> None:
    players, leagues = headline()
    matching = int(pool["qualifies"].sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Players analysed", f"{players:,}", border=True)
    c2.metric("Leagues", leagues, border=True)
    c3.metric("Season", "2015/16", border=True)
    c4.metric("Match this filter", matching, border=True)
    st.write("")


def _shortlist(tab, pool: pd.DataFrame, position: str) -> None:
    with tab:
        qualifying = pool[pool["qualifies"]]
        # Live breakdown so it is obvious the sliders are doing something, even when the
        # ranked list itself looks similar (the wage gate dominates on this demo data).
        fee_ok = int(pool["affordable_fee"].sum())
        wage_ok = int(pool["affordable_wage"].sum())
        st.caption(f"**{len(pool)}** {position}s with enough minutes · **{fee_ok}** within the transfer budget · "
                   f"**{wage_ok}** within the wage budget · **{len(qualifying)}** pass both gates and the profile.")
        if qualifying.empty:
            st.info("No player passes both budget gates and the profile at these settings — showing the "
                    "closest on-profile targets. Raise the transfer or wage budget in the sidebar to open it up.")

        only_qualifying = st.toggle("Show only signable players (in budget and on style)",
                                    value=not qualifying.empty)
        view = (qualifying if (only_qualifying and not qualifying.empty) else pool).copy()
        view.insert(0, "Rank", range(1, len(view) + 1))
        view["Market value"] = (view["market_value_eur"] / 1e6).round(1)
        view["Below fair value"] = (view["undervaluation_pct"] * 100).round(0)  # fraction -> percent

        table = view.rename(columns={
            "player_name": "Player", "team_name": "Club", "age": "Age", "fit_score": "Style fit",
            "performance_score": "Quality", "cluster_label": "Player type",
            "affordable_fee": "Fee in budget", "affordable_wage": "Wages in budget",
            "on_profile": "Fits our style",
        })
        st.dataframe(
            table[["Rank", "Player", "Club", "Age", "Quality", "Style fit", "Player type",
                   "Market value", "Below fair value", "Fee in budget", "Wages in budget", "Fits our style"]],
            hide_index=True, width="stretch", height=720,
            column_config={
                "Quality": st.column_config.ProgressColumn(
                    "Quality", help="How good the player is across the stats that matter for this position (0-100).",
                    min_value=0, max_value=100, format="%d"),
                "Style fit": st.column_config.ProgressColumn(
                    "Style fit", help="How well the player matches Leyton Orient's playing style (0-100).",
                    min_value=0, max_value=100, format="%d"),
                "Player type": st.column_config.TextColumn("Player type", help="Playing-style archetype, e.g. poacher or target man."),
                "Market value": st.column_config.NumberColumn("Market value", help="Transfer market value (Transfermarkt).", format="€%.1fm"),
                "Below fair value": st.column_config.NumberColumn(
                    "Below fair value", help="How far under the model's fair value the market prices them. Higher = bigger bargain.",
                    format="%d%%"),
                "Fee in budget": st.column_config.CheckboxColumn("Fee in budget", help="The transfer fee fits the budget set in the sidebar."),
                "Wages in budget": st.column_config.CheckboxColumn("Wages in budget", help="The player's modelled wage fits the club's wage ceiling."),
                "Fits our style": st.column_config.CheckboxColumn("Fits our style", help="Meets the club's minimum requirements for this position."),
            },
        )
        st.caption("**Quality** = how good · **Style fit** = how well they suit our play · **Below fair value** = how much of a bargain · "
                   "the three ✓ columns are the checks a signing must pass: fee affordable, wages affordable, and fits the position profile.")


def _profile(tab, pool: pd.DataFrame, percentiles: pd.DataFrame, metrics: list[str]) -> None:
    with tab:
        if pool.empty:
            st.warning("No players for these filters.")
            return
        st.caption("Detailed profile for any player in the current shortlist.")
        name = st.selectbox("Player", pool["player_name"].tolist(), key="profile_player")
        row = pool[pool["player_name"] == name].iloc[0]

        st.subheader(f"{row['player_name']}  ·  {row['team_name']}")
        st.caption(f"{row['position_group']} · age {row['age']:.0f} · playing style: {row.get('cluster_label', 'n/a')}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Fit", f"{row['fit_score']:.0f}", border=True)
        c2.metric("Performance", f"{row['performance_score']:.0f}", border=True)
        c3.metric("Market value", f"€{row['market_value_eur'] / 1e6:.1f}m", border=True)
        c4.metric("Fair value", f"€{row['fair_value_eur'] / 1e6:.1f}m" if pd.notna(row.get("fair_value_eur")) else "n/a",
                  border=True)
        st.caption(f"Modelled weekly wage £{int(row['estimated_weekly_wage_gbp']):,} vs club ceiling "
                   f"£{int(row['wage_ceiling_gbp']):,} — modelled estimate, not an actual salary.")

        view = st.radio("View", ["Bars", "Radar"], horizontal=True, key="profile_view")
        values = percentile_vector(percentiles, int(row["player_id"]), metrics)
        chart = bar_chart(metrics, values) if view == "Bars" else radar_chart([(name, values)], metrics)
        st.plotly_chart(chart, width="stretch", config=PLOTLY_CONFIG)


def _compare(tab, pool: pd.DataFrame, percentiles: pd.DataFrame, metrics: list[str]) -> None:
    with tab:
        if len(pool) < 2:
            st.warning("Need at least two players for these filters.")
            return
        st.caption("Compare players head-to-head on the same percentile axes. The further out, the better.")

        names = pool["player_name"].tolist()
        c1, c2, c3 = st.columns(3)
        a = c1.selectbox("Player A", names, index=0, key="cmp_a")
        b = c2.selectbox("Player B", names, index=1, key="cmp_b")
        c = c3.selectbox("Player C (optional)", [NONE_OPTION] + names, index=0, key="cmp_c")

        chosen = [p for p in [a, b, (c if c != NONE_OPTION else None)] if p]
        chosen = list(dict.fromkeys(chosen))  # de-duplicate, keep order
        if len(chosen) < 2:
            st.info("Pick two different players to compare.")
            return

        traces, rows = [], []
        for player_name in chosen:
            r = pool[pool["player_name"] == player_name].iloc[0]
            traces.append((player_name, percentile_vector(percentiles, int(r["player_id"]), metrics)))
            rows.append({"Player": player_name, "Club": r["team_name"], "Age": round(r["age"]),
                         "Fit": round(r["fit_score"]), "Performance": round(r["performance_score"]),
                         "Market (€m)": round(r["market_value_eur"] / 1e6, 1)})

        chart_col, table_col = st.columns([3, 2])
        chart_col.plotly_chart(radar_chart(traces, metrics), width="stretch", config=PLOTLY_CONFIG)
        table_col.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# --- methodology ----------------------------------------------------------------------
STAGES = {
    "1 · Ingest": {
        "what": "Download every match's raw events (passes, shots, tackles) and line-ups for the three demo "
                "leagues from StatsBomb, and store them untouched so the source is auditable.",
        "assume": "We use free StatsBomb open data — the 2015/16 Premier League, La Liga and Serie A — as a "
                  "stand-in, because Leyton Orient's own division (League One) isn't on the free tier.",
        "extend": "Add the club's paid StatsBomb credentials and point the config at League One. Nothing else "
                  "in the pipeline changes.",
    },
    "2 · Aggregate": {
        "what": "Roll those millions of events into one row per player per season, converted to per-90-minute "
                "rates so a regular starter and a substitute are compared fairly.",
        "assume": "Minutes are derived from line-ups, correctly handling the half-time clock reset. Players with "
                  "under ~5 full matches (450 minutes) are flagged as small samples.",
        "extend": "Runs unchanged on any league or season's data.",
    },
    "3 · Store": {
        "what": "Load the player-season table, plus the wage and identity reference data, into a Postgres "
                "database that every later stage reads from.",
        "assume": "Structured tables (one row per player-season); large raw files stay on disk, not in the database.",
        "extend": "Scales to many more leagues and seasons simply by adding rows.",
    },
    "4 · Score": {
        "what": "Rank each player against peers in the same position and league (percentiles), then blend those "
                "into two 0–100 scores: Performance (how good) and Fit (how well they match the club's style).",
        "assume": "Performance is purely data-driven. Fit uses a club identity profile we constructed as a "
                  "stand-in, since LOFC's real recruitment profile wasn't provided.",
        "extend": "Swap in the club's real identity profile to retune Fit — it's a data file, no code change.",
    },
    "5 · Archetypes": {
        "what": "Group players within a position by playing style — for example poacher, target man or pressing "
                "forward — using k-means clustering on their relative strengths.",
        "assume": "The grouping is fully data-driven; only the plain-English labels are our reading of each cluster.",
        "extend": "Re-runs automatically whenever new data is loaded.",
    },
    "6 · Valuation": {
        "what": "Train a model to predict a player's fair market value from performance, age and position, then "
                "flag players priced below that estimate as undervalued.",
        "assume": "Real market values come from Transfermarkt (matched by name, ~98%). Performance explains roughly "
                  "half of market value; reputation, contract and potential explain the rest — so it's a guide.",
        "extend": "Add League One market values to value the club's real targets.",
    },
    "7 · Shortlist": {
        "what": "Filter to players the club can both afford (transfer fee and wage) and who meet the position's "
                "profile, then rank the survivors. If none pass, show the closest near-misses.",
        "assume": "Wages are a modelled estimate (real salaries aren't public). The transfer budget and wage "
                  "ceiling are sliders the recruiter controls.",
        "extend": "Replace the modelled wages, budget and identity profile with the club's real figures.",
    },
    "8 · Dashboard": {
        "what": "This app: pick a position, set a budget, and read a ranked, affordable, on-profile shortlist — "
                "with player profiles and side-by-side comparisons.",
        "assume": "Reads the model outputs live; moving a slider re-runs the shortlist instantly.",
        "extend": "Ships onto the club's server as a single Docker unit.",
    },
}


def _node(stage_key: str) -> str:
    """'4 · Score' -> 'Score'."""
    return stage_key.split("· ")[1].strip()


def _pipeline_dot(selected: str) -> str:
    """Flow diagram with the selected stage highlighted in solid club red."""
    nodes = [_node(k) for k in STAGES]
    lines = ['digraph {', 'rankdir=LR; bgcolor="transparent";',
             'node [shape=box, style="rounded,filled", color="#C8102E", penwidth=1.4, '
             'fontname="Helvetica", fontsize=11, margin="0.22,0.13"];',
             'edge [color="#C8102E", arrowsize=0.7];']
    for n in nodes:
        if n == selected:
            lines.append(f'"{n}" [fillcolor="{RED}", fontcolor="white"];')
        else:
            lines.append(f'"{n}" [fillcolor="#FCE8EB", fontcolor="{DARK}"];')
    lines.append(" -> ".join(f'"{n}"' for n in nodes) + ";")
    lines.append("}")
    return "\n".join(lines)


# "Stand-in today -> real with access" swap diagram. Amber = current stand-in, green = real.
DATA_SWAP_DOT = """
digraph {
  rankdir=LR; bgcolor="transparent"; nodesep=0.3; ranksep=1.3;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, margin="0.24,0.16"];
  edge [color="#9aa0a6", penwidth=1.2, arrowsize=0.8, fontname="Helvetica", fontsize=9, fontcolor="#5f6368"];

  node [fillcolor="#FBEAD2", color="#E8920C"];
  a1 [label="Player data\\n2015/16 PL · La Liga · Serie A\\n(free open data stand-in)"];
  a2 [label="Market values\\nTransfermarkt, top leagues only"];
  a3 [label="Wages\\nmodelled estimate"];
  a4 [label="Club identity\\nour constructed profile"];

  node [fillcolor="#E2F0E3", color="#2E7D32"];
  b1 [label="Player data\\ncurrent League One + target leagues"];
  b2 [label="Market values\\n+ League One (scrape GB3)"];
  b3 [label="Wages\\nclub's real salary data"];
  b4 [label="Club identity\\nclub's recruitment document"];

  a1 -> b1 [label="paid StatsBomb API"];
  a2 -> b2 [label="add source"];
  a3 -> b3 [label="club data"];
  a4 -> b4 [label="club document"];
}
"""


def _methodology(tab) -> None:
    with tab:
        st.markdown("**How a player becomes a recommendation** — from raw match data on the left to a ranked, "
                    "affordable shortlist on the right. Select a stage to see the detail.")

        diagram = st.container()  # filled after we know the selection, so it sits above the buttons
        choice = st.segmented_control("Pipeline stage", list(STAGES.keys()),
                                      default="1 · Ingest", label_visibility="collapsed") or "1 · Ingest"
        with diagram:
            st.graphviz_chart(_pipeline_dot(_node(choice)))

        stage = STAGES[choice]
        with st.container(border=True):
            st.markdown(f"#### {_node(choice)}")
            st.markdown(f"**What it does** — {stage['what']}")
            st.markdown(f"**Key assumption** — {stage['assume']}")
            st.markdown(f"**With more data** — {stage['extend']}")

        st.divider()
        st.markdown("#### What's real today, and what the club's data unlocks")
        st.caption("Every input is either real data (green) or a clearly-labelled stand-in (amber). The model logic "
                   "doesn't change — only the inputs improve. Each stand-in is a one-for-one swap:")
        st.graphviz_chart(DATA_SWAP_DOT)
        c1, c2 = st.columns(2)
        with c1.container(border=True):
            st.markdown("**Today (this demo)**")
            st.markdown("- Top-flight 2015/16 players (no League One on the free tier)\n"
                        "- Wages and club identity are modelled stand-ins\n"
                        "- Proves the method works end-to-end")
        with c2.container(border=True):
            st.markdown("**With a paid licence + club data**")
            st.markdown("- Score the club's actual targets in current League One\n"
                        "- Real wages and the club's own recruitment profile\n"
                        "- Shortlists become real, affordable signings")


if __name__ == "__main__":
    main()
