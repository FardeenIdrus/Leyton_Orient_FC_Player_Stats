"""Plotly chart builders for the dashboard.

Read-only presentation: every figure here takes already-computed numbers and returns a
go.Figure. Depends only on theme (colours) and labels (metric names), never on loaders or
tabs, so it stays free of import cycles.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from lofc.dashboard.labels import LABELS, METRIC_FAMILY, SC_METRIC_LABELS
from lofc.dashboard.theme import CLUSTER_COLOURS, COMPARE_COLOURS, DARK, RED

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

def _bar_layout(fig: go.Figure, height: int = 260, **kwargs) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=10),
                      plot_bgcolor="white", showlegend=False, **kwargs)
    return fig



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
