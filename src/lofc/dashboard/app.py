"""Leyton Orient recruitment dashboard (Streamlit).

A clean, on-brand front end over the model outputs in Postgres. A recruiter picks a
position, sets a budget, and reads a ranked shortlist of affordable, on-profile players,
then drills into a profile, compares players, browses playing-style groups, or reads how
the pipeline works. The sliders call the Phase 7 filter live. Clicking a shortlist row
opens that player's profile inline below the table.

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
# Distinct, readable colours for the playing-style groups on the cluster scatter.
CLUSTER_COLOURS = [RED, "#1F77B4", "#2CA02C", "#9467BD", "#FF7F0E", "#8C564B"]
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

# Trait family per metric, used to pick two *different* axes for the cluster scatter
# (so it contrasts, say, shot threat vs driving forward, not xG vs goals).
METRIC_FAMILY = {
    "np_xg_p90": "shooting", "np_goals_p90": "shooting", "goals_p90": "shooting",
    "xg_p90": "shooting", "shots_p90": "shooting",
    "xa_p90": "creation", "key_passes_p90": "creation", "assists_p90": "creation",
    "passes_into_box_p90": "creation",
    "passes_p90": "passing", "passes_completed_p90": "passing", "progressive_passes_p90": "passing",
    "passes_into_final_third_p90": "passing", "pass_completion_pct": "passing",
    "carries_p90": "carrying", "progressive_carries_p90": "carrying", "dribbles_p90": "carrying",
    "dribbles_completed_p90": "carrying", "dribble_success_pct": "carrying",
    "pressures_p90": "defending", "tackles_p90": "defending", "interceptions_p90": "defending",
    "blocks_p90": "defending", "clearances_p90": "defending", "ball_recoveries_p90": "defending",
    "gk_saves_p90": "goalkeeping", "save_pct": "goalkeeping",
}


# --- data access (cached) -------------------------------------------------------------
@st.cache_resource
def get_engine():
    return create_engine(settings.database_url)


@st.cache_data(ttl=600)
def load_candidates(wage_ceiling_multiplier: float) -> pd.DataFrame:
    engine = get_engine()
    candidates = build_candidates(engine, wage_ceiling_multiplier)
    keys = ["player_id", "competition_id", "season_id"]
    archetypes = pd.read_sql("SELECT player_id, competition_id, season_id, cluster_label "
                             "FROM archetypes", engine)
    # Season goals/assists totals plus the underlying xG/xA rates, for display context.
    totals = pd.read_sql("SELECT player_id, competition_id, season_id, goals, assists, "
                         "np_xg_p90, xa_p90 FROM player_season_metrics", engine)
    return candidates.merge(archetypes, on=keys, how="left").merge(totals, on=keys, how="left")


@st.cache_data(ttl=600)
def load_percentiles() -> pd.DataFrame:
    # Latest season only: profile views are keyed by player_id, so a second season
    # would duplicate every metric row. Earlier seasons stay in the DB for trajectory.
    return pd.read_sql(
        "SELECT player_id, metric, percentile FROM player_percentiles "
        "WHERE season_id = (SELECT MAX(season_id) FROM player_percentiles)", get_engine())


@st.cache_data(ttl=600)
def load_metric_values() -> pd.DataFrame:
    """Raw per-90 (and rate) values for every metric, for the profile's full-stats table."""
    engine = get_engine()
    available = pd.read_sql("SELECT * FROM player_season_metrics LIMIT 0", engine).columns
    cols = [c for c in LABELS if c in available]
    return pd.read_sql(
        f"SELECT player_id, {', '.join(cols)} FROM player_season_metrics "
        "WHERE season_id = (SELECT MAX(season_id) FROM player_season_metrics)", engine)


@st.cache_data(ttl=600)
def load_wage_framework() -> pd.DataFrame:
    return pd.read_sql("SELECT position_group, age_band, weekly_wage_ceiling_gbp FROM wage_framework",
                       get_engine())


# SkillCorner physical metrics shown on the Physical tab, with recruiter-friendly names.
SC_METRIC_LABELS = {
    "distance_p90": "Total distance (m per 90)",
    "running_distance_p90": "Running distance (m per 90)",
    "hsr_distance_p90": "High-speed running distance (m per 90)",
    "sprint_distance_p90": "Sprint distance (m per 90)",
    "sprint_count_p90": "Sprints (per 90)",
    "hi_count_p90": "High-intensity runs (per 90)",
    "high_accel_count_p90": "High accelerations (per 90)",
    "high_decel_count_p90": "High decelerations (per 90)",
    "cod_count_p90": "Changes of direction (per 90)",
    "psv99_kmh": "Peak speed, PSV-99 (km/h)",
}


@st.cache_data(ttl=600)
def load_sc_teams() -> pd.DataFrame:
    """Team-level SkillCorner physical output: all 24 League One clubs."""
    try:
        teams = pd.read_sql("SELECT * FROM skillcorner_team_season", get_engine())
    except Exception:
        return pd.DataFrame()
    teams["display_name"] = teams["team_name"].str.replace(r"\s+FC$", "", regex=True)
    return teams


@st.cache_data(ttl=600)
def load_sc_players() -> pd.DataFrame:
    """Player-level SkillCorner physical output: LOFC's own squad, with positions."""
    engine = get_engine()
    try:
        players = pd.read_sql("SELECT * FROM skillcorner_player_season", engine)
    except Exception:
        return pd.DataFrame()
    if players.empty:
        return players
    positions = pd.read_sql(
        "SELECT player_id, position_group FROM player_season_metrics "
        "WHERE season_id = (SELECT MAX(season_id) FROM player_season_metrics)", engine)
    return players.merge(positions, on="player_id", how="left")


@st.cache_data(ttl=600)
def headline() -> tuple[int, int]:
    """Top-level counts for the KPI strip: players analysed and leagues covered."""
    engine = get_engine()
    players = pd.read_sql("SELECT COUNT(*) AS c FROM player_season_metrics", engine)["c"][0]
    leagues = pd.read_sql("SELECT COUNT(DISTINCT competition_id) AS c FROM player_season_metrics", engine)["c"][0]
    return int(players), int(leagues)


@st.cache_data(ttl=600)
def season_label() -> str:
    """The season shown in the KPI strip: the latest one in the data (e.g. '2025/26')."""
    name = pd.read_sql(
        "SELECT season_name FROM player_season_metrics "
        "WHERE season_id = (SELECT MAX(season_id) FROM player_season_metrics) LIMIT 1",
        get_engine())["season_name"]
    return str(name[0]).replace("/20", "/") if len(name) else "—"


@st.cache_data(ttl=600)
def max_minutes() -> int:
    """Data-driven top of the minutes slider (a season's real maximum, not a guess)."""
    value = pd.read_sql(
        "SELECT MAX(minutes) AS m FROM player_season_metrics "
        "WHERE season_id = (SELECT MAX(season_id) FROM player_season_metrics)",
        get_engine())["m"][0]
    return int(value) if pd.notna(value) else 3500


@st.cache_data(ttl=600)
def league_names() -> list[str]:
    """The actual leagues present in the data, named (e.g. 'Premier League'), from config."""
    ids = pd.read_sql("SELECT DISTINCT competition_id FROM player_season_metrics", get_engine())["competition_id"]
    # config labels look like 'Premier League 2015/16'; drop the season for a clean name.
    name_by_id = {c.competition_id: c.label.rsplit(" ", 1)[0] for c in settings.competitions}
    return [name_by_id.get(int(i), f"League {int(i)}") for i in sorted(ids)]


def percentile_vector(percentiles: pd.DataFrame, player_id: int, metrics: list[str]) -> list[float]:
    series = percentiles[percentiles["player_id"] == player_id].set_index("metric")["percentile"]
    return [float(series.get(m, 0.0)) for m in metrics]


def _strengths_weaknesses(percentiles: pd.DataFrame, player_id: int, metrics: list[str]) -> str:
    """A one-line plain-English read of a player: top-3 and bottom-3 percentiles."""
    series = percentiles[percentiles["player_id"] == player_id].set_index("metric")["percentile"]
    pairs = [(m, float(series[m])) for m in metrics if m in series.index and pd.notna(series[m])]
    if len(pairs) < 2:
        return ""
    high = sorted(pairs, key=lambda x: x[1], reverse=True)[:3]
    low = sorted(pairs, key=lambda x: x[1])[:3]
    fmt = lambda items: " · ".join(f"{LABELS.get(m, m)} ({v:.0f})" for m, v in items)
    return f":green[**Strengths**] {fmt(high)}  \n:red[**Watch-outs**] {fmt(low)}"


def _full_stats_table(row: pd.Series, percentiles: pd.DataFrame, metric_values: pd.DataFrame) -> pd.DataFrame | None:
    """Every metric for one player as actual numbers: season total, per-90 (or rate), and percentile."""
    player_id = int(row["player_id"])
    pcts = percentiles[percentiles["player_id"] == player_id].set_index("metric")["percentile"]
    value_rows = metric_values[metric_values["player_id"] == player_id]
    if value_rows.empty:
        return None
    values = value_rows.iloc[0]
    minutes = float(row["minutes"]) if pd.notna(row.get("minutes")) else 0.0

    records = []
    for metric in LABELS:
        if metric not in pcts.index or metric not in values.index or pd.isna(values[metric]):
            continue
        value = float(values[metric])
        if metric.endswith("_pct"):  # a rate, not a count: no season total
            season_total, per_90 = "—", f"{value:.0f}%"
        else:
            season_total = f"{round(value * minutes / 90):,}" if minutes else "—"
            per_90 = f"{value:.2f}"
        records.append({"Metric": LABELS[metric], "Season total": season_total,
                        "Per 90 / rate": per_90, "Percentile": round(float(pcts[metric]))})
    if not records:
        return None
    return pd.DataFrame(records).sort_values("Percentile", ascending=False).reset_index(drop=True)


# --- charts ---------------------------------------------------------------------------
# Charts are read-only: drag-to-zoom is disabled and the toolbar hidden (PLOTLY_CONFIG),
# so a stray mouse drag can't turn the chart into a zoom box.
PLOTLY_CONFIG = {"displayModeBar": False, "staticPlot": False}
# The cluster scatter is explorable: allow zoom/pan and show the toolbar (unlike the
# read-only bar/radar charts, which stay locked).
SCATTER_CONFIG = {"displayModeBar": True, "scrollZoom": True, "displaylogo": False,
                  "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}


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


def _cluster_axes(wide: pd.DataFrame, metric_cols: list[str]) -> tuple[str, str]:
    """Pick two axes that separate the groups most while showing two different traits.

    The first axis is the metric the groups differ on most. The second is the most-separating
    metric from a *different* trait family (shooting, creation, passing, carrying, defending), so
    the scatter contrasts two genuinely different things (e.g. shot threat vs driving forward)
    rather than two flavours of the same thing (e.g. xG vs goals).
    """
    if wide["cluster_label"].nunique() >= 2:
        means = wide.groupby("cluster_label")[metric_cols].mean()
        separation = means.max() - means.min()
    else:
        separation = wide[metric_cols].var()
    ranked = separation.sort_values(ascending=False).index.tolist()
    x_metric = ranked[0]
    x_family = METRIC_FAMILY.get(x_metric)
    for candidate in ranked[1:]:
        if METRIC_FAMILY.get(candidate) != x_family:
            return x_metric, candidate
    return x_metric, ranked[1]  # all one family: fall back to the next most separating


def cluster_scatter(wide: pd.DataFrame, x_metric: str, y_metric: str, selected: str | None) -> go.Figure:
    """One dot per player on two percentile axes, coloured by playing-style group.

    Explorable (zoom/pan via SCATTER_CONFIG). The axes run slightly past 0-100 so dots
    sitting on the edge are not clipped, and dotted lines mark the 50th percentile (average).
    """
    fig = go.Figure()
    # Median reference lines, drawn first so they sit behind the dots.
    fig.add_hline(y=50, line_dash="dot", line_color="#DDDDDD")
    fig.add_vline(x=50, line_dash="dot", line_color="#DDDDDD")
    for i, label in enumerate(sorted(wide["cluster_label"].dropna().unique())):
        group = wide[wide["cluster_label"] == label]
        fig.add_trace(go.Scatter(
            x=group[x_metric], y=group[y_metric], mode="markers", name=label,
            marker=dict(size=11, color=CLUSTER_COLOURS[i % len(CLUSTER_COLOURS)], opacity=0.75,
                        line=dict(width=1, color="white")),
            text=group["player_name"],
            hovertemplate="<b>%{text}</b><br>" + LABELS.get(x_metric, x_metric) + ": %{x:.0f}<br>"
                          + LABELS.get(y_metric, y_metric) + ": %{y:.0f}<extra>" + label + "</extra>",
        ))
    # Ring the currently selected player so they're easy to spot.
    if selected and (wide["player_name"] == selected).any():
        row = wide[wide["player_name"] == selected].iloc[0]
        fig.add_trace(go.Scatter(
            x=[row[x_metric]], y=[row[y_metric]], mode="markers+text", text=[selected],
            textposition="top center", textfont=dict(size=12, color=DARK),
            showlegend=False, hoverinfo="skip",
            marker=dict(size=18, color="rgba(0,0,0,0)", line=dict(width=3, color=DARK)),
        ))
    fig.update_layout(
        height=520, plot_bgcolor="white", paper_bgcolor="white", hovermode="closest", dragmode="zoom",
        legend=dict(orientation="h", y=-0.2, x=0),
        xaxis=dict(title=LABELS.get(x_metric, x_metric) + " (percentile)", range=[-5, 105],
                   tickvals=[0, 25, 50, 75, 100], showgrid=True, gridcolor="#F0F0F0", zeroline=False),
        yaxis=dict(title=LABELS.get(y_metric, y_metric) + " (percentile)", range=[-5, 105],
                   tickvals=[0, 25, 50, 75, 100], showgrid=True, gridcolor="#F0F0F0", zeroline=False),
        margin=dict(l=10, r=10, t=10, b=10),
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
          .block-container {{padding-top: 4rem; max-width: 1180px;}}
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
            st.image(str(LOGO), width=96)
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


def synced_wage_budget(prime_ceiling: float) -> float:
    """Wage cap shown two synced ways: a slider (× club ceiling) and a £/week box.

    The £ box is the cap for a prime-age player in the selected position; the slider is the same
    value as a multiple of the club's modelled ceiling. Whichever you change, the other follows.
    Returns the exact multiplier the gate applies to each age band's ceiling, so a typed figure
    like £11,500 is used precisely even though the slider can only snap to its nearest 0.5 step.
    """
    st.session_state.setdefault("wage_pounds", int(round(prime_ceiling)))  # default = ceiling (1×)

    def from_slider():
        # Slider moved: set the £ box to the wage that multiple implies for a prime-age player.
        st.session_state.wage_pounds = int(round(st.session_state.wage_slider * prime_ceiling))

    # Keep the slider in step with the £ cap and the current position's ceiling (the £ box wins).
    implied_x = min(25.0, max(0.5, st.session_state.wage_pounds / prime_ceiling))
    st.session_state.wage_slider = round(implied_x / 0.5) * 0.5  # snap to the slider's 0.5 step

    st.sidebar.slider(
        "Wage budget (× club ceiling)", 0.5, 25.0, step=0.5,
        key="wage_slider", on_change=from_slider,
        help="1× = Leyton Orient's modelled weekly-wage ceiling for each position and age band. "
             "Slide up to model a bigger wage budget and see who that would make affordable. "
             "On this top-flight demo data the real (1×) ceiling is far below most players' wages, "
             "so this is the control that opens up the shortlist. Wages are modelled estimates.")
    st.sidebar.number_input(
        "…or type a max weekly wage (£)", min_value=0, max_value=200_000, step=500, key="wage_pounds",
        help="A specific weekly wage cap for a prime-age player in this position. The slider above is "
             "the same cap, expressed as a multiple of the club's modelled ceiling.")
    return st.session_state.wage_pounds / prime_ceiling


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
    framework = load_wage_framework()
    position_ceilings = framework.query("position_group == @position")["weekly_wage_ceiling_gbp"]
    prime_ceiling = float(position_ceilings.max()) if not position_ceilings.empty else 6500.0
    wage_multiplier = synced_wage_budget(prime_ceiling)
    # Show the £/week cap this implies across the position's age bands, so it stays concrete.
    applied = position_ceilings * wage_multiplier
    if not applied.empty:
        st.sidebar.caption(f"≈ £{int(applied.min()):,}–£{int(applied.max()):,}/week across age bands for a "
                           f"{position} (the typed value is the prime-age cap; younger players scale down; modelled).")
    min_minutes = st.sidebar.slider("Minimum minutes", 450, max(max_minutes(), 900), 450, step=10)
    st.sidebar.caption("450 = the minimum sample to be ranked; per-90 numbers below that are noise.")

    candidates = load_candidates(wage_multiplier)
    percentiles = load_percentiles()
    metric_values = load_metric_values()

    pool = apply_gates(candidates[(candidates["position_group"] == position) &
                                  (candidates["minutes"] >= min_minutes)], budget_eur)
    pool = pool.sort_values("fit_score", ascending=False).reset_index(drop=True)
    metrics = list(ROLE_METRICS[POSITION_ROLE[position]])

    _kpi_strip(pool)
    shortlist_tab, profile_tab, compare_tab, types_tab, physical_tab, method_tab = st.tabs(
        ["Shortlist", "Player profile", "Compare", "Player types", "Physical", "Methodology"])
    _shortlist(shortlist_tab, pool, position, percentiles, metrics, metric_values)
    _profile(profile_tab, pool, percentiles, metrics, metric_values)
    _compare(compare_tab, pool, percentiles, metrics)
    _player_types(types_tab, pool, percentiles, metrics, position)
    _physical(physical_tab)
    _methodology(method_tab)

    st.caption(f"StatsBomb event data, {season_label()} season. Player market values are real (Transfermarkt); "
               "wages and the club identity profile are clearly-labelled modelled estimates, swappable for the "
               "club's real data with no code change.")


def _kpi_strip(pool: pd.DataFrame) -> None:
    players, _ = headline()
    leagues = league_names()
    matching = int(pool["qualifies"].sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Players analysed", f"{players:,}", border=True)
    c2.metric("Leagues", len(leagues), border=True)
    c3.metric("Season", season_label(), border=True)
    c4.metric("Match this filter", matching, border=True)
    # League names as on-brand pills, centred under the strip (nicer than grey caption text).
    pills = " ".join(
        f"<span style='background:#FCE8EB;color:{RED};border:1px solid {RED}33;border-radius:999px;"
        f"padding:3px 12px;margin:0 4px;font-size:.8rem;font-weight:600;white-space:nowrap;'>{lg}</span>"
        for lg in leagues)
    st.markdown(f"<div style='text-align:center;margin:.45rem 0 .7rem;'>{pills}</div>", unsafe_allow_html=True)
    st.write("")


def _render_profile_body(row: pd.Series, percentiles: pd.DataFrame, metrics: list[str],
                         metric_values: pd.DataFrame, key_prefix: str) -> None:
    """The full profile for one player: header, output, scores, a plain read, stats and chart.

    Shared by the Player profile tab and the inline profile under a clicked shortlist row,
    so both stay identical. key_prefix keeps the two instances' widgets distinct.
    """
    st.subheader(f"{row['player_name']}  ·  {row['team_name']}")
    st.caption(f"{row['position_group']} · age {row['age']:.1f} · playing style: {row.get('cluster_label', 'n/a')}")

    # Season output as tiles, with the underlying expected rates noted beneath.
    goals = int(row["goals"]) if pd.notna(row.get("goals")) else 0
    assists = int(row["assists"]) if pd.notna(row.get("assists")) else 0
    o1, o2, o3 = st.columns(3)
    o1.metric("Goals", goals, border=True)
    o2.metric("Assists", assists, border=True)
    o3.metric("Minutes", f"{int(row['minutes']):,}", border=True)
    npxg, xa = row.get("np_xg_p90"), row.get("xa_p90")
    if pd.notna(npxg) and pd.notna(xa):
        st.caption(f"Underlying rates: {npxg:.2f} non-pen xG per 90 · {xa:.2f} xA per 90 — these (not raw "
                   "goals/assists) drive the scores, because they're steadier season to season.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fit", f"{row['fit_score']:.0f}", border=True)
    c2.metric("Quality", f"{row['performance_score']:.0f}", border=True)
    c3.metric("Market value", f"€{row['market_value_eur'] / 1e6:.1f}m", border=True)
    c4.metric("Fair value", f"€{row['fair_value_eur'] / 1e6:.1f}m" if pd.notna(row.get("fair_value_eur")) else "n/a",
              border=True)
    st.caption(f"Modelled weekly wage £{int(row['estimated_weekly_wage_gbp']):,} vs the wage cap "
               f"£{int(row['wage_ceiling_gbp']):,} for this player — modelled estimate, not an actual salary.")

    summary = _strengths_weaknesses(percentiles, int(row["player_id"]), metrics)
    if summary:
        st.markdown(summary)

    # Full numbers on demand: every metric as a season total, a per-90 rate, and a percentile.
    stats_table = _full_stats_table(row, percentiles, metric_values)
    if stats_table is not None and not stats_table.empty:
        with st.expander("Full stats — actual numbers (season total, per 90, and percentile)"):
            st.dataframe(
                stats_table, hide_index=True, width="stretch", key=f"{key_prefix}_fullstats",
                column_config={
                    "Percentile": st.column_config.ProgressColumn(
                        "Percentile", help="Rank against peers in the same position and league (0-100).",
                        min_value=0, max_value=100, format="%d"),
                },
            )

    view = st.radio("View", ["Bars", "Radar"], horizontal=True, key=f"{key_prefix}_view")
    values = percentile_vector(percentiles, int(row["player_id"]), metrics)
    chart = bar_chart(metrics, values) if view == "Bars" else radar_chart([(row["player_name"], values)], metrics)
    st.plotly_chart(chart, width="stretch", config=PLOTLY_CONFIG, key=f"{key_prefix}_chart")


def _shortlist(tab, pool: pd.DataFrame, position: str, percentiles: pd.DataFrame, metrics: list[str],
               metric_values: pd.DataFrame) -> None:
    with tab:
        # Filter and grouping by playing-style group, above the table.
        types = sorted(pool["cluster_label"].dropna().unique().tolist())
        fc1, fc2 = st.columns([3, 1])
        chosen = fc1.multiselect("Player type", types, default=types,
                                 help="Filter the shortlist to one or more playing-style groups.")
        group_by_type = fc2.toggle("Group by type", value=False,
                                   help="Order the table by playing-style group, then by fit within each group.")
        if chosen:
            pool = pool[pool["cluster_label"].isin(chosen)]
        if group_by_type:
            pool = pool.sort_values(["cluster_label", "fit_score"], ascending=[True, False])
        else:
            pool = pool.sort_values("fit_score", ascending=False)
        pool = pool.reset_index(drop=True)

        qualifying = pool[pool["qualifies"]]
        # Live breakdown so it is obvious the sliders are doing something, even when the
        # ranked list itself looks similar (the wage gate dominates on this demo data).
        fee_ok = int(pool["affordable_fee"].sum())
        wage_ok = int(pool["affordable_wage"].sum())
        st.caption(f"**{len(pool)}** {position}s with enough minutes · **{fee_ok}** within the transfer budget · "
                   f"**{wage_ok}** within the wage budget · **{len(qualifying)}** pass both gates and meet the requirements.")
        if qualifying.empty:
            st.info("No player passes both budget gates and the requirements at these settings — showing the "
                    "closest players that meet the requirements. Raise the transfer or wage budget in the sidebar to open it up.")

        only_qualifying = st.toggle("Show only signable players (in budget and meeting requirements)",
                                    value=not qualifying.empty)
        view = (qualifying if (only_qualifying and not qualifying.empty) else pool).copy().reset_index(drop=True)
        view.insert(0, "Rank", range(1, len(view) + 1))
        view["Market value"] = (view["market_value_eur"] / 1e6).round(1)
        view["Est. wage"] = (view["estimated_weekly_wage_gbp"] / 1000).round(1)  # £ thousands per week
        view["Below fair value"] = (view["undervaluation_pct"] * 100).round(0)  # fraction -> percent

        table = view.rename(columns={
            "player_name": "Player", "team_name": "Club", "age": "Age", "fit_score": "Style fit",
            "performance_score": "Quality", "cluster_label": "Player type",
            "affordable_fee": "Fee in budget", "affordable_wage": "Wages in budget",
            "on_profile": "Meets requirements",
        })
        display_cols = ["Rank", "Player", "Club", "Age", "Quality", "Style fit", "Player type",
                        "Market value", "Est. wage", "Below fair value", "Fee in budget", "Wages in budget", "Meets requirements"]

        # Polish: tint signable rows green, near-misses amber, so the eye lands on the right players.
        def _tint(r):
            colour = "#E9F7EE" if r["qualifies"] else "#FFF6EA"
            return [f"background-color: {colour}"] * len(r)

        st.caption("🟢 in budget and meets requirements · 🟠 near-miss. **Click any row** to open that player's profile below.")
        selection = st.dataframe(
            table.style.apply(_tint, axis=1),
            column_order=display_cols, hide_index=True, width="stretch", height=560,
            on_select="rerun", selection_mode="single-row",
            key=f"shortlist_{position}_{only_qualifying}_{group_by_type}_{'|'.join(chosen)}",
            column_config={
                "Age": st.column_config.NumberColumn("Age", format="%.1f"),
                "Quality": st.column_config.ProgressColumn(
                    "Quality", help="How good the player is across the stats that matter for this position (0-100).",
                    min_value=0, max_value=100, format="%d"),
                "Style fit": st.column_config.ProgressColumn(
                    "Style fit", help="How well the player matches Leyton Orient's playing style (0-100).",
                    min_value=0, max_value=100, format="%d"),
                "Player type": st.column_config.TextColumn("Player type", help="Playing-style archetype, e.g. poacher or target man."),
                "Market value": st.column_config.NumberColumn("Market value", help="Transfer market value (Transfermarkt).", format="€%.1fm"),
                "Est. wage": st.column_config.NumberColumn(
                    "Est. wage", help="Modelled weekly wage (£ thousands). Real salaries are private, so this is a stand-in.",
                    format="£%.1fk"),
                "Below fair value": st.column_config.NumberColumn(
                    "Below fair value", help="How far under the model's fair value the market prices them. Higher = bigger bargain.",
                    format="%d%%"),
                "Fee in budget": st.column_config.CheckboxColumn("Fee in budget", help="The transfer fee fits the budget set in the sidebar."),
                "Wages in budget": st.column_config.CheckboxColumn("Wages in budget", help="The player's modelled wage fits the club's wage ceiling."),
                "Meets requirements": st.column_config.CheckboxColumn("Meets requirements", help="Meets the club's minimum requirements for this position."),
            },
        )
        st.caption("**Quality** = how good · **Style fit** = how well they suit our play · **Below fair value** = how much of a bargain · "
                   "the three ✓ columns are the checks a signing must pass: fee affordable, wages affordable, and meets the position's minimum requirements.")

        # Option B (master-detail): a clicked row opens that player's profile right here.
        rows = list(selection.selection.rows) if selection and selection.selection else []
        if rows and rows[0] < len(view):
            selected_row = view.iloc[rows[0]]
            st.session_state["shortlist_selected_player"] = selected_row["player_name"]
            st.divider()
            st.markdown("#### Selected player")
            _render_profile_body(selected_row, percentiles, metrics, metric_values, key_prefix="inline")
        else:
            st.caption("⬆️ Click a player in the table to open their full profile here.")


def _player_options(pool: pd.DataFrame) -> tuple[list[str], dict[str, int]]:
    """Selectbox labels 'Name — Club' and a label -> pool-index map.

    The club in the label disambiguates genuine namesakes (two different players
    with the same name), which a bare-name lookup would silently conflate.
    """
    labels, by_label = [], {}
    for idx, r in pool.iterrows():
        label = f"{r['player_name']} — {r['team_name']}"
        labels.append(label)
        by_label[label] = idx
    return labels, by_label


def _profile(tab, pool: pd.DataFrame, percentiles: pd.DataFrame, metrics: list[str],
             metric_values: pd.DataFrame) -> None:
    with tab:
        if pool.empty:
            st.warning("No players for these filters.")
            return
        st.caption("Detailed profile for any player in the current shortlist.")
        labels, by_label = _player_options(pool)
        selected = st.session_state.get("shortlist_selected_player")
        default_index = next((i for i, lb in enumerate(labels)
                              if selected and lb.startswith(f"{selected} — ")), 0)
        label = st.selectbox("Player", labels, index=default_index, key="profile_player")
        row = pool.loc[by_label[label]]
        _render_profile_body(row, percentiles, metrics, metric_values, key_prefix="profile")


def _compare(tab, pool: pd.DataFrame, percentiles: pd.DataFrame, metrics: list[str]) -> None:
    with tab:
        if len(pool) < 2:
            st.warning("Need at least two players for these filters.")
            return
        st.caption("Compare players head-to-head on the same percentile axes. The further out, the better.")

        labels, by_label = _player_options(pool)
        c1, c2, c3 = st.columns(3)
        a = c1.selectbox("Player A", labels, index=0, key="cmp_a")
        b = c2.selectbox("Player B", labels, index=1, key="cmp_b")
        c = c3.selectbox("Player C (optional)", [NONE_OPTION] + labels, index=0, key="cmp_c")

        chosen = [p for p in [a, b, (c if c != NONE_OPTION else None)] if p]
        chosen = list(dict.fromkeys(chosen))  # de-duplicate, keep order
        if len(chosen) < 2:
            st.info("Pick two different players to compare.")
            return

        traces, rows = [], []
        for label in chosen:
            r = pool.loc[by_label[label]]
            traces.append((r["player_name"], percentile_vector(percentiles, int(r["player_id"]), metrics)))
            rows.append({"Player": r["player_name"], "Club": r["team_name"], "Age": round(r["age"], 1),
                         "Fit": round(r["fit_score"]), "Performance": round(r["performance_score"]),
                         "Market (€m)": round(r["market_value_eur"] / 1e6, 1)})

        chart_col, table_col = st.columns([3, 2])
        chart_col.plotly_chart(radar_chart(traces, metrics), width="stretch", config=PLOTLY_CONFIG)
        table_col.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _player_types(tab, pool: pd.DataFrame, percentiles: pd.DataFrame, metrics: list[str], position: str) -> None:
    """Show the playing-style groups for this position: summary cards plus a scatter."""
    with tab:
        if pool.empty:
            st.warning("No players for these filters.")
            return
        st.markdown("**Playing-style groups for this position.** These are found by clustering players on their "
                    "relative strengths (what they do more of than the rest of their own game), so the split is by "
                    "*style*, not quality. The labels are auto-generated from each group's standout stats.")

        ids = pool["player_id"].tolist()
        block = percentiles[(percentiles["player_id"].isin(ids)) & (percentiles["metric"].isin(metrics))]
        wide = block.pivot_table(index="player_id", columns="metric", values="percentile")
        info = pool.drop_duplicates("player_id").set_index("player_id")[
            ["cluster_label", "performance_score", "fit_score", "player_name", "team_name", "qualifies"]]
        wide = wide.join(info, how="inner")
        metric_cols = [m for m in metrics if m in wide.columns]
        if wide.empty or len(metric_cols) < 2:
            st.info("Not enough data to show playing-style groups for this position.")
            return
        wide[metric_cols] = wide[metric_cols].fillna(50.0)

        labels = sorted(wide["cluster_label"].dropna().unique())
        st.markdown("##### The groups")
        columns = st.columns(min(len(labels), 3) or 1)
        for i, label in enumerate(labels):
            group = wide[wide["cluster_label"] == label]
            examples = group.sort_values("fit_score", ascending=False)["player_name"].head(2).tolist()
            with columns[i % len(columns)]:
                with st.container(border=True):
                    st.markdown(f"**{label}**")
                    st.caption(f"{len(group)} players · average quality {group['performance_score'].mean():.0f}/100")
                    st.caption("e.g. " + ", ".join(examples))

        st.markdown("##### How the groups separate")
        # Let the user circle any player directly here, defaulting to whoever is selected elsewhere.
        names = sorted(wide["player_name"].dropna().unique().tolist())
        prior = st.session_state.get("shortlist_selected_player") or st.session_state.get("profile_player")
        options = [NONE_OPTION] + names
        highlight = st.selectbox("Find a player (circles their dot)", options,
                                 index=options.index(prior) if prior in options else 0, key="types_highlight")
        selected = highlight if highlight != NONE_OPTION else None
        x_metric, y_metric = _cluster_axes(wide, metric_cols)
        st.plotly_chart(cluster_scatter(wide, x_metric, y_metric, selected),
                        width="stretch", config=SCATTER_CONFIG, key="cluster_scatter")
        st.caption(f"Each dot is a {position}, placed by {LABELS.get(x_metric, x_metric)} vs "
                   f"{LABELS.get(y_metric, y_metric)} (percentile), coloured by group. The two axes are the stats "
                   "that separate the groups most; the dotted lines mark the 50th percentile (average). The ringed "
                   "dot is the player selected on the Shortlist or Profile tab. Scroll or use the toolbar to zoom; "
                   "double-click to reset.")


# --- physical (SkillCorner) -----------------------------------------------------------
def _sc_league_bar(teams: pd.DataFrame, metric: str) -> go.Figure:
    """All 24 clubs on one physical metric, Leyton Orient highlighted."""
    data = teams.dropna(subset=[metric]).sort_values(metric)
    is_lofc = data["team_name"].str.contains("Leyton", na=False)
    fig = go.Figure(go.Bar(
        x=data[metric], y=data["display_name"], orientation="h",
        marker_color=[RED if flag else "#d4d4d4" for flag in is_lofc],
    ))
    fig.update_layout(height=560, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_title=SC_METRIC_LABELS[metric], yaxis_title=None,
                      plot_bgcolor="white", showlegend=False)
    return fig


def _physical(tab) -> None:
    with tab:
        teams = load_sc_teams()
        players = load_sc_players()
        if teams.empty:
            st.info("SkillCorner tracking data is not loaded. Drop the club export in "
                    "data/reference/skillcorner/ and run: python -m lofc.ingest.skillcorner")
            return

        season = teams["season_label"].iloc[0]
        st.markdown(f"**Physical output from SkillCorner tracking data, League One {season}.** "
                    "Off-ball running and intensity, which on-ball event data cannot see.")
        st.caption("Scope, stated plainly: player-level tracking covers the Leyton Orient squad only; "
                   "other clubs appear as team totals. So this page measures our own physical identity and "
                   "where the team sits in the league. It never scores recruitment targets, because no "
                   "tracking data exists for them.")

        st.markdown("##### Where Leyton Orient sit in the league")
        label_by_col = {v: k for k, v in SC_METRIC_LABELS.items()}
        choice = st.selectbox("Physical metric", list(SC_METRIC_LABELS.values()), key="sc_metric")
        metric = label_by_col[choice]
        ranks = teams[metric].rank(ascending=False, method="min")
        lofc_mask = teams["team_name"].str.contains("Leyton", na=False)
        if lofc_mask.any() and pd.notna(teams.loc[lofc_mask, metric].iloc[0]):
            rank = int(ranks[lofc_mask].iloc[0])
            value = teams.loc[lofc_mask, metric].iloc[0]
            median = teams[metric].median()
            st.caption(f"Leyton Orient: {value:,.1f} — rank {rank} of {len(teams)} "
                       f"(league median {median:,.1f}).")
        st.plotly_chart(_sc_league_bar(teams, metric), width="stretch", key="sc_league_bar")

        st.markdown("##### The measured identity of the current squad")
        summary_rows = []
        for col, label in SC_METRIC_LABELS.items():
            if teams[col].notna().sum() == 0 or not lofc_mask.any():
                continue
            rank = int(teams[col].rank(ascending=False, method="min")[lofc_mask].iloc[0])
            summary_rows.append({"Metric": label,
                                 "Leyton Orient": round(float(teams.loc[lofc_mask, col].iloc[0]), 1),
                                 "League median": round(float(teams[col].median()), 1),
                                 "Rank of 24": rank})
        st.dataframe(pd.DataFrame(summary_rows), hide_index=True, width="stretch")
        st.caption("This describes how the team currently plays, not how it should: a draft physical identity "
                   "for the Director of Football to confirm or override. Once confirmed, it informs which "
                   "on-ball traits (e.g. pressing volume) the Fit score weights for every candidate — the "
                   "traits themselves come from event data that exists for all players.")

        if not players.empty:
            st.markdown("##### Player level: the Leyton Orient squad")
            cols = {"player_name": "Player", "position_group": "Position",
                    "matches_measured": "Matches tracked", "distance_p90": "Distance/90 (m)",
                    "hsr_distance_p90": "High-speed dist/90 (m)", "sprint_count_p90": "Sprints/90",
                    "high_accel_count_p90": "High accels/90", "psv99_kmh": "Peak speed (km/h)"}
            view = (players[list(cols)].rename(columns=cols)
                    .sort_values("Distance/90 (m)", ascending=False).round(1))
            st.dataframe(view, hide_index=True, width="stretch", height=420)
            st.caption("Players with enough tracked minutes for season averages. Use this to see who drives "
                       "the team's running and sprint output, and as physical benchmarks when scouts assess "
                       "a target for the same role in person.")


# --- methodology ----------------------------------------------------------------------
STAGES = {
    "1 · Ingest": {
        "tag": "API pull", "method": "statsbombpy API pull, idempotent landing on disk",
        "source": "StatsBomb open data", "kind": "real",
        "what": "Download every match's raw events (passes, shots, tackles) and line-ups for the three demo "
                "leagues from StatsBomb, and store them untouched so the source is auditable.",
        "assume": "We use free StatsBomb open data — the 2015/16 Premier League, La Liga and Serie A — as a "
                  "stand-in, because Leyton Orient's own division (League One) isn't on the free tier.",
        "extend": "Add the club's paid StatsBomb credentials and point the config at League One. Nothing else "
                  "in the pipeline changes.",
    },
    "2 · Aggregate": {
        "tag": "per-90 rates", "method": "event roll-up to per-player-season, per-90 normalisation",
        "source": "StatsBomb open data", "kind": "real",
        "what": "Roll those millions of events into one row per player per season, converted to per-90-minute "
                "rates so a regular starter and a substitute are compared fairly.",
        "assume": "Minutes are derived from line-ups, correctly handling the half-time clock reset. Players with "
                  "under ~5 full matches (450 minutes) are flagged as small samples.",
        "extend": "Runs unchanged on any league or season's data.",
    },
    "3 · Store": {
        "tag": "PostgreSQL", "method": "PostgreSQL via SQLAlchemy, schema versioned with Alembic",
        "source": "—", "kind": "none",
        "what": "Load the player-season table, plus the wage and identity reference data, into a Postgres "
                "database that every later stage reads from.",
        "assume": "Structured tables (one row per player-season); large raw files stay on disk, not in the database.",
        "extend": "Scales to many more leagues and seasons simply by adding rows.",
    },
    "4 · Score": {
        "tag": "percentiles + weights", "method": "percentile rank within position+league, then a weighted blend",
        "source": "StatsBomb (real) + club style profile (stand-in)", "kind": "standin",
        "what": "Rank each player against peers in the same position and league (percentiles), then blend those "
                "into two 0–100 scores: Performance (how good) and Fit (how well they match the club's style).",
        "assume": "Performance is purely data-driven. Fit uses a club 'style profile' we built — which stats "
                  "matter most for each position — as a stand-in, since LOFC's real one wasn't provided.",
        "extend": "Swap in the club's real recruitment/style profile to retune Fit — it's a data file, no code change.",
    },
    "5 · Archetypes": {
        "tag": "PCA + k-means", "method": "standardise, PCA, then k-means clustering (k chosen by silhouette)",
        "source": "StatsBomb open data", "kind": "real",
        "what": "Group players within a position by playing style — for example poacher, target man or pressing "
                "forward — using k-means clustering on their relative strengths.",
        "assume": "The grouping is fully data-driven; only the plain-English labels are our reading of each cluster.",
        "extend": "Re-runs automatically whenever new data is loaded.",
    },
    "6 · Valuation": {
        "tag": "Ridge regression", "method": "Ridge regression on log market value, cross-validated (out-of-fold)",
        "source": "Transfermarkt market values", "kind": "real",
        "what": "Train a model to predict a player's fair market value from performance, age and position, then "
                "flag players priced below that estimate as undervalued.",
        "assume": "Real market values come from Transfermarkt (matched by name, ~98%). Performance explains roughly "
                  "half of market value; reputation, contract and potential explain the rest — so it's a guide.",
        "extend": "Add League One market values to value the club's real targets.",
    },
    "7 · Shortlist": {
        "tag": "gates + ranking", "method": "two affordability gates + on-profile filter, ranked by fit",
        "source": "wage framework + wage estimates (stand-ins)", "kind": "standin",
        "what": "Filter to players the club can both afford (transfer fee and wage) and who meet the position's "
                "profile, then rank the survivors. If none pass, show the closest near-misses.",
        "assume": "Wages are a modelled estimate (real salaries aren't public). The transfer budget and wage "
                  "ceiling are sliders the recruiter controls.",
        "extend": "Replace the modelled wages, budget and identity profile with the club's real figures.",
    },
    "8 · Dashboard": {
        "tag": "Streamlit", "method": "Streamlit + Plotly, reading the model outputs live",
        "source": "all model outputs", "kind": "none",
        "what": "This app: pick a position, set a budget, and read a ranked shortlist of affordable players "
                "who meet the club's requirements — with player profiles and side-by-side comparisons.",
        "assume": "Reads the model outputs live; moving a slider re-runs the shortlist instantly.",
        "extend": "Ships onto the club's server as a single Docker unit.",
    },
}

KIND_COLOUR = {"real": "green", "standin": "orange", "none": "gray"}


def _node(stage_key: str) -> str:
    """'4 · Score' -> 'Score'."""
    return stage_key.split("· ")[1].strip()


def _pipeline_dot(selected: str) -> str:
    """Flow diagram of the pipeline; the selected stage is solid red. The method for each
    stage is shown in the detail card below, not crammed into the box."""
    lines = ['digraph {', 'rankdir=LR; bgcolor="transparent"; nodesep=0.3; ranksep=0.55;',
             'node [shape=box, style="rounded,filled", color="#C8102E", penwidth=1.4, '
             'fontname="Helvetica", fontsize=13, margin="0.3,0.18"];',
             'edge [color="#C8102E", arrowsize=0.8, penwidth=1.2];']
    for key in STAGES:
        node = _node(key)
        if node == selected:
            lines.append(f'"{node}" [label="{key}", fillcolor="{RED}", fontcolor="white"];')
        else:
            lines.append(f'"{node}" [label="{key}", fillcolor="#FCE8EB", fontcolor="{DARK}"];')
    lines.append(" -> ".join(f'"{_node(k)}"' for k in STAGES) + ";")
    lines.append("}")
    return "\n".join(lines)


def _methodology(tab) -> None:
    with tab:
        st.markdown("**How a player becomes a recommendation.** Each box is a pipeline stage. Select one to see "
                    "its method, data source, the assumption behind it, and how it extends with the club's data.")

        diagram = st.container()  # filled after we know the selection, so it sits above the buttons
        choice = st.segmented_control("Pipeline stage", list(STAGES.keys()),
                                      default="1 · Ingest", label_visibility="collapsed") or "1 · Ingest"
        with diagram:
            st.graphviz_chart(_pipeline_dot(_node(choice)))

        stage = STAGES[choice]
        with st.container(border=True):
            st.markdown(f"#### {_node(choice)}")
            st.markdown(f":violet-background[**Method:** {stage['method']}] &nbsp; "
                        f":{KIND_COLOUR[stage['kind']]}-background[**Data:** {stage['source']}]")
            st.markdown(f"**What it does** — {stage['what']}")
            st.markdown(f"**Assumption** — {stage['assume']}")
            st.markdown(f"**With paid / club data** — {stage['extend']}")

        st.divider()
        st.markdown("#### What's real, what we modelled, and what the club's data unlocks")
        st.markdown(
            "Nothing is hidden. Two kinds of input feed the model. **Real data** is genuine StatsBomb / "
            "Transfermarkt data that simply comes from the demo leagues. **Modelled** inputs are figures we "
            "built ourselves, because the club's own documents and a paid data feed weren't available. "
            "Improving any input is a file or config change — the model logic never changes."
        )
        st.markdown(
            "| Input | What the demo uses now | Real or modelled? | With the club's data + a paid StatsBomb licence |\n"
            "|---|---|---|---|\n"
            "| Player performance | StatsBomb 2015/16 (PL, La Liga, Serie A) | Real data, demo leagues | Current **League One** + your target leagues |\n"
            "| Market values | Transfermarkt, top leagues | Real data, demo leagues | **+ League One** market values |\n"
            "| Player wages | modelled from position, age and quality | **Modelled** (salaries aren't public) | the club's **real salary data** |\n"
            "| Wage budget (the ceiling) | EFL 50%-of-turnover rule + LOFC's published accounts | Part fact, part assumption | the club's **real wage budget** |\n"
            "| Style profile (what we want per position) | our football-judgement profile | **Modelled** (no club document yet) | the club's **recruitment document** |\n"
        )
        st.caption("So the only invented pieces are wages and the club's style/budget preferences — and each is a "
                   "one-line swap for the club's real figures. The performance and market-value data are already real.")


if __name__ == "__main__":
    main()
