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
    # Bio facts from the squad-page scrape (attached to players during valuation).
    bio = pd.read_sql("SELECT player_id, foot, contract_until, height_cm FROM players", engine)
    out = (candidates.merge(archetypes, on=keys, how="left")
           .merge(totals, on=keys, how="left")
           .merge(bio, on="player_id", how="left"))
    out["contract_until"] = pd.to_datetime(out["contract_until"], errors="coerce")
    name_by_id = {c.competition_id: c.label.rsplit(" ", 1)[0] for c in settings.competitions}
    out["league"] = out["competition_id"].map(name_by_id).fillna("—")
    return out


@st.cache_data(ttl=600)
def load_percentiles() -> pd.DataFrame:
    # Latest season only, keyed by player AND league: a mid-season mover (e.g. League
    # Two to National League in January) legitimately has one row per league, and a
    # player_id-only lookup would mix them. Earlier seasons stay in the DB for trajectory.
    return pd.read_sql(
        "SELECT player_id, competition_id, metric, percentile FROM player_percentiles "
        "WHERE season_id = (SELECT MAX(season_id) FROM player_percentiles)", get_engine())


@st.cache_data(ttl=600)
def load_metric_values() -> pd.DataFrame:
    """Raw per-90 (and rate) values for every metric, for the profile's full-stats table."""
    engine = get_engine()
    available = pd.read_sql("SELECT * FROM player_season_metrics LIMIT 0", engine).columns
    cols = [c for c in LABELS if c in available]
    return pd.read_sql(
        f"SELECT player_id, competition_id, {', '.join(cols)} FROM player_season_metrics "
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
def load_trajectory() -> pd.DataFrame:
    """Every season row per player, for the profile's season-by-season view.

    The dashboard's scores and prices are pinned to the latest season; earlier
    seasons exist purely to show direction (improving or declining). A mid-season
    mover has one row per league, deliberately: rates are league-relative.
    """
    return pd.read_sql(
        "SELECT player_id, season_id, season_name, competition_name, team_name, "
        "minutes, goals, assists, np_xg_p90, xa_p90, "
        "save_pct, gk_saves_p90, tackles_p90, interceptions_p90, pass_completion_pct "
        "FROM player_season_metrics ORDER BY season_id", get_engine())


def _trajectory(player_id: int, role: str, key_prefix: str) -> None:
    """Season-by-season output for one player, role-relevant columns only."""
    rows = load_trajectory()
    rows = rows[rows["player_id"] == player_id]
    if len(rows) < 2:
        return
    view = pd.DataFrame({
        "Season": rows["season_name"].str.replace("/20", "/", regex=False),
        "League": rows["competition_name"],
        "Club": rows["team_name"],
        "Minutes": rows["minutes"].round(0).astype(int),
    })
    if role == "goalkeeper":
        view["Save %"] = (rows["save_pct"] * 100).round(0)  # stored 0-1
        view["Saves/90"] = rows["gk_saves_p90"].round(2)
    elif role == "defender":
        view["Tackles/90"] = rows["tackles_p90"].round(2)
        view["Interceptions/90"] = rows["interceptions_p90"].round(2)
        view["Pass %"] = (rows["pass_completion_pct"] * 100).round(0)  # stored 0-1
    else:
        view["Goals"] = rows["goals"].fillna(0).astype(int)
        view["Assists"] = rows["assists"].fillna(0).astype(int)
        view["npxG/90"] = rows["np_xg_p90"].round(2)
        view["xA/90"] = rows["xa_p90"].round(2)
    st.markdown("**Season by season**")
    st.dataframe(view, hide_index=True, width="stretch", key=f"{key_prefix}_trajectory")
    st.caption("Direction matters as much as level: improving output across seasons is a different "
               "buy from a one-off year. Scores and prices on this page are for the latest season; "
               "a league change between rows means the rates are not like-for-like (per-90 numbers "
               "are relative to each league).")


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


def percentile_vector(percentiles: pd.DataFrame, player_id: int, comp_id: int,
                      metrics: list[str]) -> list[float]:
    series = percentiles[(percentiles["player_id"] == player_id)
                         & (percentiles["competition_id"] == comp_id)
                         ].set_index("metric")["percentile"]
    return [float(series.get(m, 0.0)) for m in metrics]


def _strengths_weaknesses(percentiles: pd.DataFrame, player_id: int, comp_id: int,
                          metrics: list[str]) -> str:
    """A one-line plain-English read of a player: top-3 and bottom-3 percentiles."""
    series = percentiles[(percentiles["player_id"] == player_id)
                         & (percentiles["competition_id"] == comp_id)
                         ].set_index("metric")["percentile"]
    pairs = [(m, float(series[m])) for m in metrics if m in series.index and pd.notna(series[m])]
    if len(pairs) < 2:
        return ""
    high = sorted(pairs, key=lambda x: x[1], reverse=True)[:3]
    low = sorted(pairs, key=lambda x: x[1])[:3]
    fmt = lambda items: " · ".join(f"{LABELS.get(m, m)} ({v:.0f})" for m, v in items)
    return f":green[**Strengths**] {fmt(high)}  \n:red[**Watch-outs**] {fmt(low)}"


def _full_stats_table(row: pd.Series, percentiles: pd.DataFrame, metric_values: pd.DataFrame) -> pd.DataFrame | None:
    """Every metric for one player as actual numbers: season total, per-90 (or rate), and percentile."""
    player_id, comp_id = int(row["player_id"]), int(row["competition_id"])
    pcts = percentiles[(percentiles["player_id"] == player_id)
                       & (percentiles["competition_id"] == comp_id)].set_index("metric")["percentile"]
    value_rows = metric_values[(metric_values["player_id"] == player_id)
                               & (metric_values["competition_id"] == comp_id)]
    if value_rows.empty:
        return None
    values = value_rows.iloc[0]
    minutes = float(row["minutes"]) if pd.notna(row.get("minutes")) else 0.0

    records = []
    for metric in LABELS:
        if metric not in pcts.index or metric not in values.index or pd.isna(values[metric]):
            continue
        value = float(values[metric])
        if metric.endswith("_pct"):  # a 0-1 rate, not a count: no season total
            season_total, per_90 = "—", f"{value * 100:.0f}%"
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


def synced_min_minutes(max_mins: int) -> int:
    """A minimum-minutes control with a slider and a number box kept in sync.

    The floor is 450 (the rankable threshold: per-90 numbers below that are noise)
    and the top is the real maximum minutes in the data, not a guess. Values are
    clamped so a stored setting survives a switch to a dataset with a lower maximum.
    """
    st.session_state.setdefault("minutes_slider", 450)
    st.session_state.setdefault("minutes_number", 450)
    st.session_state.minutes_slider = min(max(st.session_state.minutes_slider, 450), max_mins)
    st.session_state.minutes_number = min(max(st.session_state.minutes_number, 450), max_mins)

    def from_slider():
        st.session_state.minutes_number = st.session_state.minutes_slider

    def from_number():
        st.session_state.minutes_slider = st.session_state.minutes_number

    st.sidebar.slider("Minimum minutes", 450, max_mins, step=10,
                      key="minutes_slider", on_change=from_slider)
    st.sidebar.number_input("…or type the minutes", 450, max_mins, step=10,
                            key="minutes_number", on_change=from_number)
    st.sidebar.caption("450 = the minimum sample to be ranked; per-90 numbers below that are noise.")
    return int(st.session_state.minutes_slider)


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
    min_minutes = synced_min_minutes(max(max_minutes(), 900))
    max_age = st.sidebar.slider(
        "Maximum age", 18, 40, 40,
        help="Veterans dominate raw bargain lists: the market floor-values older players regardless "
             "of current output (little resale value, short horizon), so their output looks underpriced. "
             "Cap the age to match the signing horizon — e.g. 28 if resale value matters.")
    league_options = league_names()
    chosen_leagues = st.sidebar.multiselect("Leagues", league_options, default=league_options)
    expiring_only = st.sidebar.checkbox(
        "Out of contract by summer 2026",
        help="Only players whose Transfermarkt contract runs out by 30 June 2026 — the free-transfer "
             "and cut-price market. Players with no known contract date are hidden while this is on.")
    foot_choice = st.sidebar.selectbox(
        "Preferred foot", ["Any", "Left", "Right"],
        help="Left/Right includes two-footed players. Only known feet are shown when set.")

    candidates = load_candidates(wage_multiplier)
    percentiles = load_percentiles()
    metric_values = load_metric_values()

    # An unknown age is kept, not silently dropped; the cap only excludes known-older players.
    age_ok = (candidates["age"] <= max_age) | candidates["age"].isna()
    candidates = candidates[age_ok]
    if chosen_leagues:
        candidates = candidates[candidates["league"].isin(chosen_leagues)]
    if expiring_only:
        candidates = candidates[candidates["contract_until"].notna()
                                & (candidates["contract_until"] <= pd.Timestamp("2026-06-30"))]
    if foot_choice != "Any":
        candidates = candidates[candidates["foot"].isin([foot_choice.lower(), "both"])]
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
    _methodology(method_tab, candidates, budget_eur, min_minutes)

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
    bio_bits = [f"{row['position_group']}", f"age {row['age']:.1f}", str(row.get("league", ""))]
    if pd.notna(row.get("foot")):
        bio_bits.append(f"{row['foot']}-footed")
    if pd.notna(row.get("height_cm")):
        bio_bits.append(f"{int(row['height_cm'])} cm")
    if pd.notna(row.get("contract_until")):
        bio_bits.append(f"contract to {row['contract_until']:%b %Y}")
    bio_bits.append(f"playing style: {row.get('cluster_label', 'n/a')}")
    st.caption(" · ".join(b for b in bio_bits if b))

    # Season output as tiles, chosen for the player's role: goals mean nothing on a
    # goalkeeper's card, save percentage means nothing on a striker's.
    role = POSITION_ROLE[row["position_group"]]
    mv = metric_values[(metric_values["player_id"] == int(row["player_id"]))
                       & (metric_values["competition_id"] == int(row["competition_id"]))]
    mv = mv.iloc[0] if not mv.empty else pd.Series(dtype=float)
    minutes = float(row["minutes"]) if pd.notna(row.get("minutes")) else 0.0

    def total(per90_col: str) -> str:
        value = mv.get(per90_col)
        return f"{round(float(value) * minutes / 90):,}" if pd.notna(value) and minutes else "—"

    o1, o2, o3 = st.columns(3)
    if role == "goalkeeper":
        save_pct = mv.get("save_pct")  # stored 0-1
        o1.metric("Save %", f"{float(save_pct) * 100:.0f}%" if pd.notna(save_pct) else "—", border=True)
        o2.metric("Saves", total("gk_saves_p90"), border=True)
    elif role == "defender":
        o1.metric("Tackles", total("tackles_p90"), border=True)
        o2.metric("Interceptions", total("interceptions_p90"), border=True)
    else:
        goals = int(row["goals"]) if pd.notna(row.get("goals")) else 0
        assists = int(row["assists"]) if pd.notna(row.get("assists")) else 0
        o1.metric("Goals", goals, border=True)
        o2.metric("Assists", assists, border=True)
    o3.metric("Minutes", f"{int(row['minutes']):,}", border=True)

    npxg, xa = row.get("np_xg_p90"), row.get("xa_p90")
    if role in ("midfielder", "attacker") and pd.notna(npxg) and pd.notna(xa):
        st.caption(f"Underlying rates: {npxg:.2f} non-pen xG per 90 · {xa:.2f} xA per 90 — these (not raw "
                   "goals/assists) drive the scores, because they're steadier season to season.")

    _trajectory(int(row["player_id"]), role, key_prefix)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fit", f"{row['fit_score']:.0f}", border=True)
    c2.metric("Quality", f"{row['performance_score']:.0f}", border=True)
    c3.metric("Market value", f"€{row['market_value_eur'] / 1e6:.1f}m", border=True)
    c4.metric("Fair value", f"€{row['fair_value_eur'] / 1e6:.1f}m" if pd.notna(row.get("fair_value_eur")) else "n/a",
              border=True)
    st.caption(f"Modelled weekly wage £{int(row['estimated_weekly_wage_gbp']):,} vs the wage cap "
               f"£{int(row['wage_ceiling_gbp']):,} for this player — modelled estimate, not an actual salary.")
    if int(row["competition_id"]) == 65 and pd.notna(row.get("fair_value_eur")):
        st.caption("⚠️ Fair-value note: Transfermarkt prices very few National League players "
                   "(23 in our data), so fair values in this league carry extra uncertainty — "
                   "trust the direction, not the exact figure.")

    summary = _strengths_weaknesses(percentiles, int(row["player_id"]), int(row["competition_id"]), metrics)
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
    values = percentile_vector(percentiles, int(row["player_id"]), int(row["competition_id"]), metrics)
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
        # Contract as the expiry month/year a recruiter scans for ("06/2026"), dash when unknown.
        view["Contract"] = view["contract_until"].dt.strftime("%m/%Y").fillna("—")

        table = view.rename(columns={
            "player_name": "Player", "team_name": "Club", "league": "League", "age": "Age",
            "fit_score": "Style fit",
            "performance_score": "Quality", "cluster_label": "Player type",
            "affordable_fee": "Fee in budget", "affordable_wage": "Wages in budget",
            "on_profile": "Meets requirements",
        })
        display_cols = ["Rank", "Player", "Club", "League", "Age", "Quality", "Style fit", "Player type",
                        "Market value", "Est. wage", "Contract", "Below fair value",
                        "Fee in budget", "Wages in budget", "Meets requirements"]

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
                "Contract": st.column_config.TextColumn(
                    "Contract", help="Contract end (Transfermarkt). Expiring deals are the cheap market: "
                                     "free transfers and cut-price January sales."),
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

        # The same list, portable: recruitment runs on spreadsheets shared with scouts.
        export = table[[c for c in display_cols if c != "Rank"]].copy()
        export.insert(0, "Rank", table["Rank"])
        st.download_button(
            "⬇ Download this shortlist (CSV)",
            data=export.to_csv(index=False).encode("utf-8"),
            file_name=f"lofc_shortlist_{position.lower().replace(' ', '_')}.csv",
            mime="text/csv",
            help="Saves exactly what is on screen — the current filters, ranking and columns — "
                 "to open in Excel or Sheets.")

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
            traces.append((r["player_name"], percentile_vector(percentiles, int(r["player_id"]),
                                                               int(r["competition_id"]), metrics)))
            rows.append({"Player": r["player_name"], "Club": r["team_name"], "Age": round(r["age"], 1),
                         "Fit": round(r["fit_score"]), "Performance": round(r["performance_score"]),
                         "Market (€m)": round(r["market_value_eur"] / 1e6, 1)})

        chart_col, table_col = st.columns([3, 2])
        chart_col.plotly_chart(radar_chart(traces, metrics), width="stretch", config=PLOTLY_CONFIG)
        table_col.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        # Percentiles are ranked within a league, so a cross-league comparison needs a caveat.
        chosen_comps = {int(pool.loc[by_label[label], "competition_id"]) for label in chosen}
        if len(chosen_comps) > 1:
            name_by_id = {c.competition_id: c.label.rsplit(" ", 1)[0] for c in settings.competitions}
            leagues_str = " and ".join(sorted({name_by_id.get(c, f"league {c}") for c in chosen_comps}))
            st.warning(f"These players play in different leagues ({leagues_str}). All percentiles are "
                       "ranked against each player's own league, so an 80 in a lower league does not "
                       "equal an 80 in a higher one. Use the radar for style, not as a like-for-like "
                       "quality comparison; the valuation model is what accounts for league level.")


def _player_types(tab, pool: pd.DataFrame, percentiles: pd.DataFrame, metrics: list[str], position: str) -> None:
    """Show the playing-style groups for this position: summary cards plus a scatter."""
    with tab:
        if pool.empty:
            st.warning("No players for these filters.")
            return
        st.markdown("**Playing-style groups for this position.** These are found by clustering players on their "
                    "relative strengths (what they do more of than the rest of their own game), so the split is by "
                    "*style*, not quality. The labels are auto-generated from each group's standout stats.")

        # Keyed by player AND league: a mid-season mover has one row per league, and a
        # player_id-only pivot would average his two leagues' percentiles together.
        keys = ["player_id", "competition_id"]
        pairs = pool[keys].drop_duplicates()
        block = percentiles.merge(pairs, on=keys)
        block = block[block["metric"].isin(metrics)]
        wide = block.pivot_table(index=keys, columns="metric", values="percentile")
        info = pool.drop_duplicates(keys).set_index(keys)[
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
                    # No average-quality figure here: the groups are built style-not-quality,
                    # so group means hover near 50 and a "47 vs 50" read would be noise.
                    st.caption(f"{len(group)} players · top fits: {', '.join(examples)}")

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
# The recruitment flow, one entry per step. Plain language first; the technical
# line lives in a footnote so the page reads cleanly for a non-technical audience.
METHOD_STEPS = {
    "1 · Collect": {
        "title": "Collect every match, ball by ball",
        "what": "We pull the full event feed for every match in the leagues Leyton Orient recruits from: "
                "every pass, shot, tackle, dribble and save, with who did it and where. The raw feed is "
                "stored untouched, so any number on this dashboard can be traced back to source.",
        "why": "Recruitment opinions start from what actually happened on the pitch — not highlights, "
               "not reputation.",
        "note": "Data: the club's paid StatsBomb feed — Championship, League One, League Two and the "
                "National League, the 2024/25 and 2025/26 seasons.",
        "tech": """
**Step by step:**
1. Targets are config, not code: `SB_COMPETITIONS` lists competition/season ids (currently 8 EFL league-seasons), so re-targeting is an environment change.
2. `statsbombpy` pulls matches, then per match the full nested event feed plus line-ups, against the authenticated API (credentials from `.env`, never in code).
3. Every payload lands on disk untouched (atomic temp-file + rename), keyed by competition/season/match — the audit trail back to source.
4. The pull is idempotent and resumable: matches already on disk are skipped, so an interrupted run continues where it stopped.
5. Guards added on real data: a transient empty API response is never persisted (the next run retries it), and the aggregator skips zero-event fixtures loudly rather than dying. 19 of 4,456 fixtures (0.4%, almost all National League) are genuinely uncollected on the feed — documented, not hidden.
6. Bonus from the paid feed: line-ups carry each player's date of birth (99.6% coverage), which later powers exact player matching to market values.
""",
        "stats": ["matches", "league_seasons", "leagues"],
    },
    "2 · Player profiles": {
        "title": "Turn matches into one fair profile per player",
        "what": "All of a player's actions across the season are rolled into one profile, expressed per 90 "
                "minutes so a starter and a substitute are compared fairly. Anyone with fewer than 450 "
                "minutes (about five matches) is kept but not ranked — too small a sample to judge.",
        "why": "Per-90 rates with a minutes floor stop one lucky cameo from outranking a season of real work.",
        "note": "Spot-checked against published records: our top-scorer counts match the real golden-boot "
                "tallies in League One (Dom Ballard, 23) and the Championship exactly.",
        "tech": """
**Step by step:**
1. Minutes come from line-up position spells, not event timestamps: each spell's start/end clock is converted to cumulative match time, period-aware (the clock resets to 45:00 at half-time, so a spell crossing the break is the sum of each half's real length, stoppage included). The paid feed adds milliseconds to spell clocks; the parser handles both formats.
2. Events roll up per player per match (goals, npxG, shots, passing volumes and completions, progressive passes and carries, dribbles, pressures, tackles, interceptions, recoveries, GK saves and goals conceded). xA comes from linking each shot back to its key pass via the shot's `key_pass_id`.
3. Match rows accumulate into one row per player per league-season; the dominant position (most minutes) sets the position group; a player who appears in two leagues gets two rows, ranked within each.
4. Counting stats become per-90 rates (value ÷ minutes × 90); ratios (pass %, save %) stay ratios.
5. `rankable` = 450+ minutes (≈5 full matches). Below that, per-90 rates are noise — one goal in 30 minutes reads as 3.0 goals/90 — so small samples are kept but never ranked.
6. Validation protocol: computed totals are checked against published records. League One and Championship top scorers match exactly (Ballard 23, Vipotnik 23, Wareham 19, McBurnie 18); the National League differences are fully explained by the 14 uncollected fixtures and our inclusion of playoffs.
""",
        "stats": ["player_seasons", "ranked"],
    },
    "3 · Two scores": {
        "title": "Score every player twice: Quality and Fit",
        "what": "Each player is ranked against peers in the same position and the same league, then given two "
                "0–100 scores. Quality answers “how good is he?” — equal weight across the stats that matter "
                "for his role. Fit answers “does he suit the way we play?” — weighted to the club's identity.",
        "why": "A brilliant player who doesn't suit the team is a different conversation from a perfect-fit "
               "player. Keeping the two scores separate keeps both conversations honest.",
        "note": "The identity behind Fit is currently our construction, clearly labelled — it becomes the "
                "club's own document the day it's provided, as a file swap.",
        "tech": """
**Step by step:**
1. Every metric becomes a percentile within the player's position **and** league, computed over rankable players only. A League Two centre-back's passing is ranked against League Two centre-backs — never against Championship midfielders. Pooling leagues into one ranking would be wrong (the 90th percentile means different things in different tiers), so cross-league comparison happens later, via the valuation model's league feature.
2. **Quality** is the equal-weight mean of the percentiles relevant to the player's role — goalkeeper (4 stats: save %, saves/90, pass completion, passes/90), defender (10), midfielder (10), attacker (9: npxG, np goals, shots, xA, key passes, passes into box, completed dribbles, progressive carries, pressures). Equal weights are deliberate: weighting is an opinion, and this score is the opinion-free baseline.
3. **Fit** is the identity-weighted sum over the club profile's metrics (weights sum to 1.0 per position; e.g. centre-forward: npxG 0.28, np goals 0.20, pressures 0.17, …). The profile also carries minimum-percentile floors used later as the on-profile filter.
4. Both scores are scaled 0–100 and ranked within position and league. A player can be high on one and low on the other — that split is the point (a lethal finisher who never presses: high Quality, lower Fit for a pressing identity).
""",
        "stats": ["ranked", "scores_two"],
    },
    "4 · Playing styles": {
        "title": "Group players by how they play",
        "what": "Within each position, players are grouped by playing style — poacher versus link forward, "
                "ball-playing versus no-nonsense centre-back. The grouping looks at what each player does "
                "most relative to his own game, so it captures style, not ability.",
        "why": "When a specific profile is needed — a pressing forward, a progressive full-back — the search "
               "starts from players who already play that way.",
        "note": "The groups are found by the data; only the plain-English labels are our reading of them.",
        "tech": """
**Step by step:**
1. Each player's percentiles are centred on his own average first — subtracting his overall level — so what remains is his *shape*: what he does more and less of than the rest of his own game. Without this, clusters would just split good players from bad ones.
2. The centred profiles are standardised, compressed with PCA (keeping ~90% of the variance), then clustered with k-means, separately per position, pooled across leagues.
3. k runs from 2 to 6 per position and the silhouette score picks the best split; a fixed random seed makes assignments reproducible run to run. Silhouettes are modest (~0.2) and reported honestly: playing styles are a continuum, not sharp boxes.
4. Labels are auto-generated from each cluster's standout metrics versus position peers — nobody hand-names the groups. On demo data this reproduced the classic archetypes (ball-playing vs stopper centre-backs, poacher vs link forwards) without being told they exist.
5. Each player also stores his distance to the cluster centre — how typical of the group he is.
""",
        "stats": ["style_groups", "ranked"],
    },
    "5 · Price check": {
        "title": "Estimate what each player should cost",
        "what": "Every player gets a real market price (Transfermarkt) and a fair price — what players with "
                "his output, age, position and league typically cost. Each player is priced by a model that "
                "never saw his own price tag. A player priced well below his fair price is flagged as "
                "potentially undervalued.",
        "why": "For a club that can't outspend rivals, finding players the market underrates is the whole "
               "game. This makes that search systematic instead of anecdotal.",
        "note": "It flags who to scout, not what to bid: stats explain most of the price difference between "
                "players, and scouts verify the rest (contract, injuries, character).",
        "tech": """
**Step by step:**
1. **Getting the prices:** no free dataset covers the EFL, so current market values are read from Transfermarkt club squad pages (96 clubs, one polite request every 2.5s). Coverage: Championship 97%, League One 91%, League Two 90%, National League ~2.5% — so the National League keeps scores and styles but is excluded from pricing.
2. **Matching players across databases:** primary match = identical birth date (from the paid feed's line-ups) + name agreement; fallback = name match within the same league, vetoed if birth dates contradict; final fallback = a maintained dataset for loanees whose value lives on a parent club's page (only entries still updated this season — stale price tags are refused). An implausible-age guard (16–38) catches mistaken identity. Net: ~85% of rankable players in the priced leagues are matched; the rest are mostly January movers, shown with scores but no price.
3. **The model:** Ridge regression predicts log market value (prices are multiplicative) from role percentiles, age, minutes, position and league. Regularisation strength is auto-tuned (RidgeCV over four alphas).
4. **No self-pricing:** 5-fold cross-validation — every player's fair value comes from a model trained on the other four folds, so nobody is priced by a model that saw his own tag.
5. **Accuracy, honestly:** cross-validated R² 0.748 on the log scale; median absolute error ~€166k. The unexplained remainder is what stats can't see — contracts, injuries, agents — which is why the output is a scouting flag, never a bid price.
6. **Eras never mix:** the demo era (2015/16) and the current EFL era train as separate models; prices a decade apart must not share coefficients. Only the current season is priced — the scrape is a snapshot, and last season's output must not be judged against today's tags.
""",
        "stats": ["valued", "value_leagues"],
    },
    "6 · Affordability": {
        "title": "Apply Leyton Orient's reality, then rank",
        "what": "Two gates filter the pool to players the club could actually sign: the transfer fee against "
                "the budget, and an estimated weekly wage against the club's wage ceiling for that position "
                "and age. Wages are estimated as a range — a player whose range straddles the ceiling is "
                "kept and flagged for a judgement call rather than silently dropped. Survivors are ranked "
                "by Fit; that ranked list is the shortlist.",
        "why": "A shortlist of unaffordable players is a wish list. The gates make every name on screen a "
               "realistic conversation.",
        "note": "Wage estimates are modelled from published reporting and validated against club payrolls "
                "(Leyton Orient's modelled wage bill lands within ~10% of the published figure). The club's "
                "real wage framework replaces the whole table as a file swap.",
        "tech": """
**Step by step:**
1. **The wage estimate** = league tier anchor × position factor × age factor. Tier = which third of his position's Quality ranking the player falls in, within his league. Anchors are prime-age weekly figures per league, each sourced — League One: Mid £5,500 (calculated from Capology's published £4,100 average over 640 salaries, scaled to prime age by ÷0.75), Top £12,000 (set between two published bounds: top-50 all >£8,400, extremes £15–20k), Squad £2,400 (inferred, consistent with the ~£1,000 floor).
2. Position factors (CF 1.20 → GK 0.82, mean ≈ 1) compress the top-flight pay spread, since lower-league pay is flatter; the age curve peaks at 25–29 (U21 ×0.45, 21–24 ×0.75, 25–29 ×1.00, 30–32 ×0.90, 33+ ×0.65). Both are labelled assumptions — no public positional wage data exists below the top flight.
3. **The band:** ×0.70 to ×1.40 around the central estimate, wider upward because real asks (signing-on fees, agents) overshoot more than undershoot.
4. **Gate semantics:** pass if the band's low end fits the ceiling; flagged `wage_marginal` when the band straddles it (affordable on the low estimate, not the high — a phone call, not a model decision); excluded only when even the low end exceeds the ceiling. The fee gate compares real market value to the transfer budget. On-profile floors must also clear. If nothing passes, the nearest misses are shown — never a blank screen.
5. **Validation:** modelled wages summed per squad are reconciled against published payrolls (±40% tolerance). All 8 league-seasons pass (−2% to +31%); Leyton Orient's own modelled bill lands +9% from its published figure. The Championship anchor originally failed (+57%), was re-anchored down 30%, and now passes — the calibration loop demonstrably works.
6. The whole grid is a screening prior, replaced wholesale by the club's real wage framework (one CSV, no code change).
""",
        "stats": ["qualifying", "gates"],
    },
    "7 · Physical layer": {
        "title": "Add what event data can't see: the running",
        "what": "SkillCorner tracking data adds the off-ball dimension — distance covered, sprints, "
                "high-intensity runs, peak speed. Player-level data covers the Leyton Orient squad; "
                "team-level data covers all 24 League One clubs, so the club can see exactly where it "
                "sits physically in its league.",
        "why": "Two uses: an evidence-based picture of the team's physical identity for the Director of "
               "Football to confirm or challenge, and physical benchmarks scouts can hold a target against.",
        "note": "Said plainly: no tracking data exists for other clubs' individual players, so candidates "
                "are never given a physical score. Their physical assessment stays with the scouts.",
        "tech": """
**Step by step:**
1. The club-provided SkillCorner export holds four sheets; the two season sheets are loaded into Postgres (team level: all 24 clubs; player level: the LOFC squad), as a conditional pipeline step that runs whenever an export exists in the data folder.
2. A curated set of 18 physical metrics is kept (distances, high-speed running, sprints, high-intensity runs, accelerations/decelerations, changes of direction, peak speed PSV-99), per-90 where applicable; SkillCorner's literal 'null' strings are handled.
3. LOFC players are matched to their StatsBomb identities by birth date + name — 21 of 21 matched — so tracking data joins onto scores and profiles.
4. Scope is enforced by design, not by caveat: team-level data powers the league benchmarking; player-level data describes only our own squad. No table exists from which a candidate's physical score could even be computed.
5. The measured squad profile is presented as a *draft* identity: it describes how the team currently plays, which is evidence for the Director of Football's decision, not the decision itself.
""",
        "stats": ["sc_clubs", "sc_players"],
    },
}


@st.cache_data(ttl=600)
def methodology_stats() -> dict:
    """Live counts shown on the methodology cards, straight from the database."""
    engine = get_engine()

    def one(query: str):
        return pd.read_sql(query, engine).iloc[0, 0]

    import glob as _glob
    matches = sum(len(_glob.glob(f"data/raw/{c.competition_id}/{c.season_id}/events/*.json"))
                  for c in settings.competitions)
    try:
        sc_clubs = int(one("SELECT COUNT(*) FROM skillcorner_team_season"))
        sc_players = int(one("SELECT COUNT(*) FROM skillcorner_player_season"))
    except Exception:
        sc_clubs = sc_players = 0
    return {
        "matches": ("Matches analysed", f"{matches:,}"),
        "league_seasons": ("League-seasons", int(one(
            "SELECT COUNT(DISTINCT (competition_id, season_id)) FROM player_season_metrics"))),
        "leagues": ("Leagues", int(one(
            "SELECT COUNT(DISTINCT competition_id) FROM player_season_metrics"))),
        "player_seasons": ("Player-season profiles", f"{int(one('SELECT COUNT(*) FROM player_season_metrics')):,}"),
        "ranked": ("Players ranked", f"{int(one('SELECT COUNT(*) FROM player_scores')):,}"),
        "scores_two": ("Scores per player", "2"),
        "style_groups": ("Style groups found", int(one(
            "SELECT COUNT(DISTINCT (position_group, cluster_label)) FROM archetypes"))),
        "valued": ("Players priced", f"{int(one('SELECT COUNT(*) FROM valuations')):,}"),
        "value_leagues": ("Leagues priced", "3 of 4"),
        "qualifying": ("Pass both gates today", f"{int(one('SELECT COUNT(*) FROM shortlists WHERE NOT is_near_miss')):,}"),
        "gates": ("Affordability gates", "Fee + Wage"),
        "sc_clubs": ("Clubs benchmarked", sc_clubs),
        "sc_players": ("LOFC players tracked", sc_players),
    }


def _flow_strip(selected: str) -> str:
    """The pipeline as a chain of on-brand chips, the selected step solid red."""
    chips = []
    for key in METHOD_STEPS:
        number, name = key.split(" · ")
        active = key == selected
        style = (f"background:{RED};color:#fff;border:1px solid {RED};" if active else
                 f"background:#FCE8EB;color:{DARK};border:1px solid {RED}33;")
        chips.append(f"<span style='{style}border-radius:999px;padding:4px 13px;font-size:.82rem;"
                     f"font-weight:600;white-space:nowrap;'>{number} · {name}</span>")
    arrow = f"<span style='color:{RED};font-weight:700;'>→</span>"
    return ("<div style='display:flex;align-items:center;gap:7px;flex-wrap:wrap;"
            "justify-content:center;margin:.3rem 0 .9rem;'>" + arrow.join(chips) + "</div>")


@st.cache_data(ttl=600)
def method_visual_data() -> dict:
    """Small data frames behind the per-step methodology charts."""
    import glob as _glob
    engine = get_engine()
    data: dict = {}
    data["matches_by_league"] = pd.DataFrame(
        [{"label": c.label,
          "matches": len(_glob.glob(f"data/raw/{c.competition_id}/{c.season_id}/events/*.json"))}
         for c in settings.competitions])
    data["minutes"] = pd.read_sql("SELECT minutes FROM player_season_metrics", engine)["minutes"]
    data["example"] = pd.read_sql(
        "SELECT m.player_name, m.team_name, s.performance_score, s.fit_score "
        "FROM shortlists sl JOIN player_scores s USING (player_id, competition_id, season_id) "
        "JOIN player_season_metrics m USING (player_id, competition_id, season_id) "
        "WHERE NOT sl.is_near_miss ORDER BY sl.fit_score DESC LIMIT 1", engine)
    data["bargains"] = pd.read_sql(
        "SELECT m.player_name, v.market_value_eur, v.fair_value_eur "
        "FROM valuations v "
        "JOIN shortlists sl USING (player_id, competition_id, season_id) "
        "JOIN player_season_metrics m USING (player_id, competition_id, season_id) "
        "WHERE NOT sl.is_near_miss ORDER BY v.undervaluation_pct DESC LIMIT 3", engine)
    return data


def _bar_layout(fig: go.Figure, height: int = 260, **kwargs) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=10),
                      plot_bgcolor="white", showlegend=False, **kwargs)
    return fig


def _method_visual(choice: str) -> go.Figure | None:
    """A small, concrete chart for each methodology step. None = no chart."""
    data = method_visual_data()

    if choice.startswith("1"):
        frame = data["matches_by_league"]
        fig = go.Figure(go.Bar(x=frame["label"], y=frame["matches"], marker_color=RED))
        return _bar_layout(fig, title_text="Matches collected per league-season")

    if choice.startswith("2"):
        fig = go.Figure(go.Histogram(x=data["minutes"], nbinsx=40, marker_color="#d4d4d4"))
        fig.add_vline(x=450, line_color=RED, line_width=2, line_dash="dash",
                      annotation_text="450 min — ranked from here", annotation_font_color=RED)
        return _bar_layout(fig, title_text="Season minutes per player; below the line = kept but not ranked",
                           xaxis_title="minutes", yaxis_title="players")

    if choice.startswith("3") and not data["example"].empty:
        ex = data["example"].iloc[0]
        fig = go.Figure(go.Bar(
            x=[ex["performance_score"], ex["fit_score"]], y=["Quality", "Fit"],
            orientation="h", marker_color=["#9a9a9a", RED],
            text=[f"{ex['performance_score']:.0f}", f"{ex['fit_score']:.0f}"], textposition="outside"))
        fig.update_xaxes(range=[0, 100])
        return _bar_layout(fig, height=200,
                           title_text=f"Example — {ex['player_name']} ({ex['team_name']}): two scores, two questions")

    if choice.startswith("5") and not data["bargains"].empty:
        frame = data["bargains"]
        fig = go.Figure([
            go.Bar(name="Market value", x=frame["player_name"], y=frame["market_value_eur"],
                   marker_color="#9a9a9a"),
            go.Bar(name="Fair value (model)", x=frame["player_name"], y=frame["fair_value_eur"],
                   marker_color=RED),
        ])
        fig.update_layout(barmode="group", legend=dict(orientation="h", y=1.15))
        fig.update_yaxes(title_text="€")
        return _bar_layout(fig, title_text="The three biggest gaps on today's shortlist: price vs what the profile is worth")

    return None


def _method_funnel(stats: dict, live_qualifying: int) -> go.Figure:
    """The whole pipeline in one picture: data narrowing to a shortlist.

    The first four stages are facts about the dataset; the last one is computed
    live from the sidebar's current budget, wage and minutes settings.
    """
    steps = [("Matches collected", int(str(stats["matches"][1]).replace(",", ""))),
             ("Player-season profiles", int(str(stats["player_seasons"][1]).replace(",", ""))),
             ("Ranked (450+ minutes)", int(str(stats["ranked"][1]).replace(",", ""))),
             ("Priced against the market", int(str(stats["valued"][1]).replace(",", ""))),
             ("Pass the gates at your current settings (all positions)", live_qualifying)]
    fig = go.Figure(go.Funnel(
        y=[label for label, _ in steps], x=[value for _, value in steps],
        marker=dict(color=[RED, "#d94f63", "#e57f8d", "#f0aeb7", "#FCE8EB"]),
        textinfo="value", connector=dict(line=dict(color="rgba(200,16,46,0.33)", width=1))))
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white")
    return fig


def _methodology(tab, candidates: pd.DataFrame, budget_eur: float, min_minutes: int) -> None:
    with tab:
        st.markdown("### How a player becomes a recommendation")
        st.markdown("Raw match data goes in; a ranked shortlist of **affordable, on-profile, undervalued** "
                    "players comes out. The funnel below is the whole story in one picture — then select "
                    "any step to see what happens there, with the live numbers from the current data.")

        stats = methodology_stats()
        # The funnel's last stage reacts to the sidebar: gates applied to every position
        # at the current budget, wage ceiling and minutes settings.
        gated = apply_gates(candidates[candidates["minutes"] >= min_minutes], budget_eur)
        live_qualifying = int(gated["qualifies"].sum())
        stats = {**stats, "qualifying": ("Pass gates right now", f"{live_qualifying:,}")}
        st.plotly_chart(_method_funnel(stats, live_qualifying), width="stretch",
                        config={"displayModeBar": False}, key="method_funnel")
        st.caption("The first four stages are facts about the dataset. The final stage is live: it counts "
                   "players in every position who pass the fee and wage gates at the budget, wage ceiling "
                   "and minutes you have set in the sidebar right now.")

        strip = st.container()  # filled after we know the selection, so the flow sits above the control
        keys = list(METHOD_STEPS.keys())
        choice = st.segmented_control("Step", keys, default=keys[0],
                                      label_visibility="collapsed") or keys[0]
        with strip:
            st.markdown(_flow_strip(choice), unsafe_allow_html=True)

        step = METHOD_STEPS[choice]
        with st.container(border=True):
            st.markdown(f"#### {choice.split(' · ')[0]} — {step['title']}")
            text_col, stat_col = st.columns([3, 1])
            with text_col:
                st.markdown(step["what"])
                st.markdown(f"**Why it matters** — {step['why']}")
                st.caption(step["note"])
            with stat_col:
                for key in step["stats"]:
                    label, value = stats[key]
                    st.metric(label, value, border=True)
            figure = _method_visual(choice)
            if figure is not None:
                st.plotly_chart(figure, width="stretch", config={"displayModeBar": False},
                                key=f"method_visual_{choice.split(' · ')[0]}")
        with st.expander("For the analyst (the full technical detail, step by step)"):
            st.markdown(step["tech"])

        st.divider()
        st.markdown("#### What's real and what's modelled")
        st.markdown(
            "Nothing is hidden: every input is either genuine data or a clearly-labelled estimate, "
            "and every estimate is a file the club's real document replaces with no code change."
        )
        st.markdown(
            "| Input | Today | Status |\n"
            "|---|---|---|\n"
            "| Player performance | StatsBomb paid feed — Championship, League One, League Two, National League (2024/25 + 2025/26) | **Real** |\n"
            "| Player ages | Birth dates from the official line-ups | **Real** |\n"
            "| Market values | Transfermarkt, current — matched player by player | **Real** (National League not priced) |\n"
            "| Physical output | SkillCorner tracking — LOFC squad + 24-club benchmarks | **Real** (squad-level scope) |\n"
            "| Player wages | Estimated from published reporting, league by league, shown as ranges | **Modelled** — validated against club payrolls |\n"
            "| Wage ceiling | EFL 50%-of-turnover rule + LOFC's published accounts | **Part fact, part modelled** |\n"
            "| Club identity (what Fit rewards) | Our construction, informed by the squad's measured physical profile | **Modelled** — awaiting the club's document |\n"
        )
        st.caption("The two modelled inputs left — wages and the club identity — are exactly the two documents "
                   "the club holds. Each drops in as a file and the whole platform re-ranks accordingly.")


if __name__ == "__main__":
    main()
