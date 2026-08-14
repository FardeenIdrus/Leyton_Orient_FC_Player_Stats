"""The Methodology tab: how the platform works, for a non-technical reader.

The pipeline as a funnel, a step-by-step account of the club's 1-5 composite with a worked
example, and an explicit statement of what is real data versus a labelled estimate."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lofc.config import settings
from lofc.constrain.filters import apply_gates
from lofc.dashboard.charts import _bar_layout
from lofc.dashboard.loaders import get_engine
from lofc.dashboard.theme import DARK, RED


METHOD_STEPS = {
    "1 · Collect": {
        "title": "Collect the match data",
        "what": "The platform pulls the full event record for every match in the leagues Leyton Orient "
                "recruits from — every pass, shot, tackle, dribble and save, with the player and location. "
                "The raw data is stored unchanged, so every figure on the dashboard traces back to source.",
        "why": "",
        "note": "Source: Impect event data — the EFL (Championship, League One, League Two, National "
                "League), the Scottish Premiership and Championship, and Premier League 2.",
        "tech": """
**Step by step:**
1. Targets are configuration, not code: the leagues and seasons to pull are set in the environment, so re-targeting requires no code change.
2. Impect player data is downloaded from the authenticated API (credentials from the environment, never in code) and stored to disk as the full metric set, exactly as returned.
3. The download is idempotent and resumable: data already on disk is skipped, so an interrupted run continues where it stopped.
4. Player identity — stable IDs, birth dates and league names — is currently seeded from StatsBomb line-ups during the migration to Impect; performance data is Impect-only. The final step of the migration moves identity seeding to Impect as well.
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
    "3 · Score": {
        "title": "Score every player on the club's 1–5 framework",
        "what": "Each player gets a single overall score from 1 to 5 — the club's own recruitment "
                "composite. Every stat that matters for his position is ranked against players in the "
                "same position and league, turned into a 1–5 mark on the club's bar (league average = 3, "
                "elite = 4), averaged into each area, then combined using the club's weights. The "
                "shortlist is ranked on this score.",
        "why": "This is Leyton Orient's real recruitment framework, not an invented one — so the ranking "
               "speaks the club's own language and every number traces back to a club document.",
        "note": "Built straight from the club's two files (the positional metric workbook and the "
                "archetype/weights document). The full step-by-step and a worked example are below the funnel.",
        "tech": """
**Step by step (the same calculation shown in full, with a worked example, below the funnel):**
1. **Rank each stat 0–100** within the player's position **and** league, over rankable players only (a League One full-back's crossing is ranked against League One full-backs). A few "lower is better" stats (e.g. turnovers) are flipped so a high rank always means good.
2. **Turn each rank into a 1–5 band** on the club's own bar: `band = 3 + (rank − 50) ÷ 20`, capped to [1, 5]. So the league median = 3.0 ("minimum standard"), the 70th percentile = 4.0 ("elite").
3. **Average the bands within each area** (Performance, Physical) — every stat counts equally. A stat with no data drops out rather than scoring zero; stats Impect measures with one number are counted once.
4. **Combine the areas** with the club's per-position weights (outfield: Performance 40, Physical 30, …, normalised to 100%). If an area has no data it drops out and the rest are rescaled, so nobody is penalised for missing data.
5. **Two composites:** the default **Objective** score uses Performance + Physical only (100% real data); the opt-in **Full** score adds the modelled money areas. Money never moves the default ranking.
6. **Advisory flags, never exclusions:** the club's "composite < 3.0 = do not proceed" and "any area < 2.0 = veto" are shown as flags, but no player is ever removed on them.
""",
        "stats": ["ranked", "composite_scale"],
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
        "what": "Affordability is an **opt-in layer** on top of the composite ranking, not part of it. When "
                "switched on, two gates flag players the club could actually sign: the transfer fee against "
                "the budget, and an estimated weekly wage against the club's wage ceiling for that position "
                "and age. Wages are estimated as a range — a player whose range straddles the ceiling is "
                "flagged for a judgement call rather than dropped. The ranking itself stays on the 1–5 "
                "composite; money never reorders it silently.",
        "why": "For a budget club, affordability matters — but it rests on modelled wages, so it informs the "
               "shortlist rather than driving the order. The default ranking is 100% real football data.",
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
        "title": "Physical data (tracking)",
        "what": "SkillCorner tracking data adds the physical dimension that event data cannot capture — "
                "distance covered, high-speed running, sprints and peak speed. It feeds both the Physical "
                "tab and the Physical dimension of the club scorecard.",
        "why": "",
        "note": "Physical coverage follows the SkillCorner licence: leagues without coverage score on the "
                "remaining dimensions, and no player is penalised for missing physical data.",
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
        "composite_scale": ("Composite scale", "1–5"),
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
    data["bargains"] = pd.read_sql(
        "SELECT m.player_name, v.market_value_eur, v.fair_value_eur "
        "FROM valuations v "
        "JOIN shortlists sl USING (player_id, competition_id, season_id) "
        "JOIN player_season_metrics m USING (player_id, competition_id, season_id) "
        "WHERE NOT sl.is_near_miss ORDER BY v.undervaluation_pct DESC LIMIT 3", engine)
    return data


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

    # Step 3 (scoring) has no example chart: players are ranked on the club's 1-5 composite,
    # shown in full (with the worked example below the funnel) and per-player on the Players tab.

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
        st.markdown("### How the platform works")
        st.markdown("The pipeline takes raw match data and produces a ranked, affordable, on-profile "
                    "shortlist. The funnel below shows each stage; select a stage to see what it does, "
                    "with the current figures.")

        stats = methodology_stats()
        # The funnel's last stage reacts to the sidebar: gates applied to every position
        # at the current budget, wage ceiling and minutes settings.
        gated = apply_gates(candidates[candidates["minutes"] >= min_minutes], budget_eur)
        live_qualifying = int(gated["qualifies"].sum())
        stats = {**stats, "qualifying": ("Pass gates right now", f"{live_qualifying:,}")}
        st.plotly_chart(_method_funnel(stats, live_qualifying), width="stretch",
                        config={"displayModeBar": False}, key="method_funnel")
        st.caption("The first four stages describe the dataset. The final stage is live: it counts the "
                   "players across all positions who pass the fee and wage gates at the budget, wage "
                   "ceiling and minutes currently set in the sidebar.")

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
        st.markdown("#### How the 1–5 score is built, step by step")
        st.markdown(
            "Every player gets one overall score from **1 to 5** — the club's own recruitment composite — "
            "and the shortlist is ranked on it. Here is the whole calculation, in plain terms. (The "
            "**Players** tab shows every one of these numbers for any player you click; the **Glossary** "
            "tab defines every stat.)"
        )
        st.markdown(
            "1. **Collect the player's stats, per 90 minutes** — the stats the club lists for his position.\n"
            "2. **Rank each stat against his positional rivals in the same league**, as a number from 0 to "
            "100 (90 = better than 90% of them). For the few stats where *lower* is better — e.g. losing "
            "the ball — the rank is flipped, so a low count correctly scores high.\n"
            "3. **Turn each rank into a 1–5 mark (the “band”)** on the club's own bar: the league "
            "median is the minimum standard (= 3.0) and the 70th percentile is elite (= 4.0). The formula "
            "is simply **band = 3 + (rank − 50) ÷ 20**, never below 1 or above 5.\n"
            "4. **Average the marks in each area** (Performance, Physical) — every stat counts equally. A "
            "stat with no data drops out rather than scoring zero.\n"
            "5. **Combine the areas using the club's weights** (outfield: Performance 40%, Physical 30%, …, "
            "rescaled to 100%). If an area has no data, the rest are rescaled so nobody is penalised for a "
            "gap.\n"
            "6. **Two scores:** the default **Objective** composite uses Performance + Physical only (100% "
            "real football data); the opt-in **Full** composite also folds in the modelled money areas. "
            "Money never changes the default ranking."
        )
        st.markdown("**Rank → 1–5 band (the club's bar):**")
        st.markdown(
            "| Rank (0–100) | Band | Meaning |\n"
            "|---|---|---|\n"
            "| 10 | 1.0 | Well below standard |\n"
            "| 30 | 2.0 | Below standard *(the veto line)* |\n"
            "| **50 — league median** | **3.0** | **Minimum standard** |\n"
            "| **70** | **4.0** | **Elite** |\n"
            "| 90 | 5.0 | Well above elite |"
        )
        with st.expander("A worked example — one real full back, every number"):
            st.markdown(
                "**Fraser Murray, Full Back, League One 2025/26** — exactly as the engine scores him "
                "(each stat ranked against League One full backs). A selection of his 22 scored "
                "performance stats:"
            )
            st.markdown(
                "| Performance stat (per 90) | His value | Rank /100 | Band |\n"
                "|---|---|---|---|\n"
                "| Expected assists | 0.20 | 100 | 5.00 |\n"
                "| Passes into the box | 2.07 | 99 | 5.00 |\n"
                "| Non-penalty xG | 0.11 | 97 | 5.00 |\n"
                "| Assists | 0.24 | 93 | 5.00 |\n"
                "| Cross completion (opponents bypassed) | 2.92 | 86 | 4.79 |\n"
                "| Pressures | 17.6 | 76 | 4.32 |\n"
                "| Counterpressures | 2.09 | 65 | 3.75 |\n"
                "| Deep progressions | 8.61 | 52 | 3.09 |\n"
                "| Ground-duel win % | 50% | 36 | 2.29 |\n"
                "| Pass completion % | 59% | 15 | 1.25 |\n"
                "| Turnovers *(lower is better → flipped)* | 22.8 | 10 | 1.02 |\n"
                "| Aerial win % | 33% | 8 | 1.00 |"
            )
            st.markdown(
                "**Average of all 22 performance marks → Performance = 3.60.** Elite attacking output "
                "(assists, xG, crossing all 5.0) pulled back toward average by weak aerials and passing "
                "(1.0–1.3) — equal weighting keeps that honest.\n\n"
                "His eight **Physical** marks average **4.85** (a relentless, high-running athlete: total "
                "distance, high-speed running and sprints all 5.0).\n\n"
                "**Combine, with full-back weights** (Performance 0.3636, Physical 0.2727):\n\n"
                "> Objective composite = (3.60 × 0.3636 + 4.85 × 0.2727) ÷ (0.3636 + 0.2727) = **4.14**\n\n"
                "That 4.14 is his headline score. No veto fires (no area below 2.0) and he clears the 3.0 "
                "minimum — a strong attacking, high-running full back, held short of the very top by his "
                "defensive and passing numbers."
            )
            st.caption("Illustrative snapshot of a real player on the latest season's data; exact figures "
                       "move as data updates. The same breakdown is on every player's card in the Players tab.")

        st.divider()
        st.markdown("#### What's real and what's modelled")
        st.markdown(
            "Nothing is hidden: every input is either genuine data or a clearly-labelled estimate, "
            "and every estimate is a file the club's real document replaces with no code change."
        )
        st.markdown(
            "| Input | Today | Status |\n"
            "|---|---|---|\n"
            "| Player performance | Impect event data — the EFL (Championship, League One, League Two, National League), Scottish Premiership & Championship, and Premier League 2 | **Real** |\n"
            "| Player ages | Birth dates from the official line-ups | **Real** |\n"
            "| Market values | Transfermarkt, current — matched player by player | **Real** (National League not priced) |\n"
            "| Physical output | SkillCorner tracking — LOFC squad + 24-club benchmarks | **Real** (squad-level scope) |\n"
            "| Player wages | Estimated from published reporting, league by league, shown as ranges | **Modelled** — validated against club payrolls |\n"
            "| Wage ceiling | EFL 50%-of-turnover rule + LOFC's published accounts | **Part fact, part modelled** |\n"
            "| Club identity (what Fit rewards) | Our construction, informed by the squad's measured physical profile | **Modelled** — awaiting the club's document |\n"
        )
        st.caption("The two modelled inputs left — wages and the club identity — are exactly the two documents "
                   "the club holds. Each drops in as a file and the whole platform re-ranks accordingly.")
