"""Metric naming, provenance and definitions — the vocabulary layer of the dashboard.

One place that answers "what is this metric called, who supplies it, what does it mean, and
(if it is a substitute) which StatsBomb stat does it stand in for". Imports nothing from the
rest of the dashboard, so it sits at the bottom of the dependency order.
"""

from __future__ import annotations

import streamlit as st

from lofc.model import metric_registry as reg
from lofc.model.metric_definitions import describe

# Short, friendly provenance label per registry source, shown against each metric so a
# recruiter always sees WHICH provider a number comes from.
SOURCE_LABEL = {
    reg.IMPECT: "Impect",
    reg.SB_ADVANCED: "StatsBomb",
    reg.SB_COMPUTED: "StatsBomb",
    reg.SKILLCORNER: "SkillCorner",
}

# Recruiter-facing names. Impect successors and Impect-native metrics are labelled by what
# they TRULY are (Impect's own concept), never dressed up as the StatsBomb stat they stand in
# for — that lineage lives in SUCCESSOR_LINEAGE below.
#
# This is the dashboard's DISPLAY vocabulary only. Retired StatsBomb columns with no live
# successor (empty for every player, in every league, since Impect became the spine) are
# deliberately absent: `progressive_passes_p90`, `passes_into_final_third_p90`, `dribbles_p90`,
# `dribbles_completed_p90`, `carries_p90`, `progressive_carries_p90`, `tackles_p90`,
# `interceptions_p90`, `ball_recoveries_p90`, `gk_saves_p90`, `dribble_success_pct`,
# `save_pct` (confirmed via `player_metrics_neutral`, zero non-null rows for each, whole
# table). Leaving a dead metric in here is how a profile ends up showing an empty "Tackles"
# card forever — every reader of this dict (glossary, full-stats table, charts) treats
# membership as "this can be shown", so a name earns a place here only once real data backs
# it. `club_framework.py` still names these metrics by their ORIGINAL StatsBomb identity for
# SCORING — `resolve_metric()` maps them to live Impect successors there — this dict has no
# bearing on that and must not be read as though it did.
LABELS = {'np_xg_p90': 'Non-pen xG',
 'np_goals_p90': 'Non-pen goals',
 'goals_p90': 'Goals',
 'xg_p90': 'xG',
 'shots_p90': 'Shots',
 'assists_p90': 'Assists',
 'xa_p90': 'Expected assists',
 'key_passes_p90': 'Key passes',
 'passes_p90': 'Passes',
 'passes_completed_p90': 'Completed passes',
 'passes_into_box_p90': 'Passes into box',
 'pressures_p90': 'Pressures',
 'blocks_p90': 'Blocks',
 'clearances_p90': 'Clearances',
 'pass_completion_pct': 'Pass accuracy',
 'ground_duels_won_p90': 'Ground duels won',
 'ball_wins_p90': 'Ball wins',
 'packing_bypassed_opponents_p90': 'Bypassed opponents (packing)',
 'packing_bypassed_defenders_p90': 'Bypassed defenders (packing)',
 'deep_progressions_p90': 'Deep progressions',
 'dribble_carry_value_p90': 'Dribble & carry value',
 'counterpressures_p90': 'Counterpressures',
 'gk_gsaa_p90': 'Goals saved above average',
 'gk_shot_stopping_pct': 'Shot stopping %',
 'pass_value_p90': 'Pass value (PxT)',
 'ground_duel_win_pct': 'Ground-duel win %',
 'aerial_win_pct': 'Aerial win %',
 'turnovers_p90': 'Turnovers',
 'off_ball_receiving_p90': 'Off-ball receiving',
 'post_shot_xg_p90': 'Post-shot xG',
 'shot_threat_p90': 'Shot threat (PxT)',
 'np_xg_xa_p90': 'NP xG + xA',
 'touches_in_box_p90': 'Touches in box',
 'open_play_assists_p90': 'Open-play assists',
 'xg_overperformance_p90': 'xG over/under-performance',
 'goal_conversion_pct': 'Goal conversion %',
 'xg_per_shot': 'xG per shot',
 'packing_xg_p90': 'Packing xG',
 'defensive_value_p90': 'Defensive-action value (PxT)',
 'on_ball_value_p90': 'On-ball value (PxT)',
 'gk_conceded_p90': 'Goals conceded',
 'gk_catches_p90': 'Keeper catches',
 'defensive_touches_outside_box_p90': 'Defensive touches outside box',
 'cross_bypassed_opponents_p90': 'Cross bypassed opponents',
 'dribble_count_p90': 'Dribbles (count)'}

# Honest lineage for substituted metrics: the StatsBomb concept each Impect metric stands
# in for, and why. Surfaced beside the metric (glossary, grand table) so a substitute is
# NEVER shown as if it were the StatsBomb stat it replaces. Keyed by the live Impect metric;
# values are (StatsBomb concept it succeeds, why the swap is honest).
SUCCESSOR_LINEAGE = {'ground_duels_won_p90': ('StatsBomb Tackles',
                          'Impect has no tackle count; won ground duels is the nearest measured '
                          "concept (a 'Tackles' number that was really duels won would mislead, "
                          'so it is named for what it is).'),
 'ball_wins_p90': ('StatsBomb Interceptions / Ball recoveries',
                   'Impect measures possession regains that remove an opponent from the game, '
                   'not raw interception or recovery events (correlations too low to relabel as '
                   'either).'),
 'packing_bypassed_opponents_p90': ('StatsBomb Progressive passes',
                                    'Impect counts opponents taken out of the game by a '
                                    'pass/carry (packing), rather than distance-based '
                                    'progressive passes.'),
 'deep_progressions_p90': ('StatsBomb Passes into final third',
                           'Opponents bypassed into the final third — counts opponents removed, '
                           'not passes played.'),
 'dribble_carry_value_p90': ('StatsBomb Progressive carries / Dribbles completed',
                             "Impect's PxT dribble value = change in team goal threat from "
                             'ball-carrying; it has no 1v1 take-on count, so this is a '
                             'progression-value proxy, not a take-on success rate.'),
 'gk_gsaa_p90': ('StatsBomb Saves',
                 'Impect has no save count; goals saved above average (post-shot xG faced minus '
                 'goals conceded) is the shot-value successor.'),
 'gk_shot_stopping_pct': ('StatsBomb Save %',
                          'Quality of shot-stopping (GSAA as a share of post-shot xG faced), not '
                          'volume of saves.'),
 'gk_catches_p90': ('StatsBomb Claims (CCAA%)',
                    'Impect has no claim-rate; keeper catches (possession regains via a catch) '
                    'is the nearest count.'),
 'defensive_touches_outside_box_p90': ('StatsBomb GK Aggressive Distance',
                                       'Impect has no tracking-based distance; defensive touches '
                                       'outside the own box is the event-data sweeper-keeper '
                                       'proxy.'),
 'cross_bypassed_opponents_p90': ('StatsBomb Successful Box Cross%',
                                  'Impect has no cross-completion %; opponents bypassed by high '
                                  '+ low crosses measures crossing effectiveness instead.'),
 'dribble_count_p90': ('StatsBomb Dribble Attempts',
                       'The count of dribble actions that bypass an opponent — the actual '
                       'dribble count the club asked for alongside dribble & carry value.')}

# Broad family per metric, used to pick two DIFFERENT kinds of axis for the cluster scatter
# (two attacking metrics would separate the groups far less than one attacking + one
# defensive).
METRIC_FAMILY = {'np_xg_p90': 'shooting',
 'np_goals_p90': 'shooting',
 'goals_p90': 'shooting',
 'xg_p90': 'shooting',
 'shots_p90': 'shooting',
 'xa_p90': 'creation',
 'key_passes_p90': 'creation',
 'assists_p90': 'creation',
 'passes_into_box_p90': 'creation',
 'passes_p90': 'passing',
 'passes_completed_p90': 'passing',
 'progressive_passes_p90': 'passing',
 'passes_into_final_third_p90': 'passing',
 'pass_completion_pct': 'passing',
 'carries_p90': 'carrying',
 'progressive_carries_p90': 'carrying',
 'dribbles_p90': 'carrying',
 'dribbles_completed_p90': 'carrying',
 'dribble_success_pct': 'carrying',
 'pressures_p90': 'defending',
 'tackles_p90': 'defending',
 'interceptions_p90': 'defending',
 'blocks_p90': 'defending',
 'clearances_p90': 'defending',
 'ball_recoveries_p90': 'defending',
 'gk_saves_p90': 'goalkeeping',
 'save_pct': 'goalkeeping'}

# SkillCorner physical metrics shown on the Physical tab, with recruiter-friendly names.
SC_METRIC_LABELS = {'distance_p90': 'Total distance (m per 90)',
 'running_distance_p90': 'Running distance (m per 90)',
 'hsr_distance_p90': 'High-speed running distance (m per 90)',
 'sprint_distance_p90': 'Sprint distance (m per 90)',
 'sprint_count_p90': 'Sprints (per 90)',
 'hi_count_p90': 'High-intensity runs (per 90)',
 'high_accel_count_p90': 'High accelerations (per 90)',
 'high_decel_count_p90': 'High decelerations (per 90)',
 'cod_count_p90': 'Changes of direction (per 90)',
 'psv99_kmh': 'Average match top speed (km/h)'}


def _metric_source(metric: str) -> str:
    """Friendly provider label for a metric ('Impect' / 'StatsBomb' / 'SkillCorner')."""
    spec = reg.BY_NAME.get(metric)
    return SOURCE_LABEL.get(spec.source, "—") if spec else "—"


@st.cache_data
def clean_definition(text: str) -> str:
    """Impect's definitions carry HTML (`<br/>`, `<b>`). Render them as Markdown: line
    breaks and bold kept, every other tag removed, entities decoded."""
    import html
    import re
    out = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    out = re.sub(r"</?(b|strong)>", "**", out, flags=re.I)
    out = re.sub(r"<[^>]+>", "", out)
    return html.unescape(out)


def _impect_name(column: str, defs: dict) -> str:
    """Impect's own name for a column: its catalogue label, plus the context it is scoped to
    (e.g. 'Successful Passes · Opponent Box'). Falls back to the raw column name."""
    d = defs.get(column) or {}
    label = d.get("label") or column
    return f"{label} · {d['context_label']}" if d.get("context_label") else label


def impect_basis(metric: str, defs: dict | None = None) -> str:
    """How a metric is built from Impect, in Impect's own names. The only words that are
    ours are the arithmetic: '+', '−', '÷' and 'per 90'."""
    from lofc.ingest.impect_definitions import load_definitions
    from lofc.ingest.impect_map import IMPECT_MAP
    defs = load_definitions() if defs is None else defs
    m = next((x for x in IMPECT_MAP if x.name == metric), None)
    if m is None or m.kind == "none":
        return ""

    def terms(pairs):
        out = ""
        for i, (col, sign) in enumerate(pairs):
            name = _impect_name(col, defs)
            out += name if i == 0 else (f" − {name}" if sign < 0 else f" + {name}")
        return out

    if m.kind == "ratio":
        num, den = terms(m.numer), terms(m.denom)
        num = f"({num})" if len(m.numer) > 1 else num
        den = f"({den})" if len(m.denom) > 1 else den
        return f"{num} ÷ {den}"
    return f"{terms(m.numer)}, per 90"


def metric_glossary() -> dict[str, dict]:
    """metric -> {label, source, text}: Impect's own words only, so a recruiter can check
    every entry against Impect (owner, 2026-10-12).

    text = the Impect metric(s) it is built from (impect_basis), then Impect's definition of
    each, verbatim and once per distinct Impect metric. The old '(scoped to this metric via
    X)' notes are gone: the basis line already names the scope in Impect's terms.
    """
    from lofc.ingest.impect_definitions import load_definitions
    from lofc.ingest.impect_map import IMPECT_MAP
    defs = load_definitions()
    by_name = {m.name: m for m in IMPECT_MAP}
    out = {}
    for metric, label in LABELS.items():
        md = describe(metric, defs)
        m = by_name.get(metric)
        if m is not None and m.kind != "none":
            parts, seen = [f"**Built from (Impect):** {impect_basis(metric, defs)}"], set()
            for col, _ in list(m.numer) + list(m.denom):
                d = defs.get(col) or {}
                if d.get("label") in seen or not d.get("definition"):
                    continue
                seen.add(d.get("label"))
                parts.append(f"**{d['label']}**: {clean_definition(d['definition'])}")
            text = "\n\n".join(parts)
        else:
            text = f"_LOFC derivation:_ {md.lofc_derivation}"
        lineage = SUCCESSOR_LINEAGE.get(metric)
        out[metric] = {"label": label, "source": SOURCE_LABEL.get(md.source, "—"),
                       "origin": md.origin, "text": text,
                       "stands_in_for": lineage[0] if lineage else "",
                       "lineage": lineage[1] if lineage else ""}
    return out


def metric_label(metric: str) -> str:
    return LABELS.get(metric, metric.replace("_p90", "").replace("_pct", " %").replace("_", " ").title())


PHYS_COMPARE_LABEL = {
    "distance_p90": ("Distance", "m/90"),
    "meters_per_minute": ("Metres per minute", "m/min"),
    "hsr_count_p90": ("High-speed runs", "per 90"),
    "hsr_distance_p90": ("High-speed distance", "m/90"),
    "sprint_count_p90": ("Sprints", "per 90"),
    "sprint_distance_p90": ("Sprint distance", "m/90"),
    "psv99_kmh": ("Average match top speed", "km/h"),
    "top5_psv99_kmh": ("Top speed (best 5 matches)", "km/h"),
}
