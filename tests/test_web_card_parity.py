"""The web card's numbers are the Streamlit card's, on the REAL database (skipped without one).

The Streamlit side is exercised the way the live page does it: the row the card receives is the
Players pool's row (`core.players_pool.build_pool`, the lifted `app.py` pool), the header text
is `player_header`'s own HTML, the rank is `scorecard.rank_in_pool`, the season table is
checked against `player_scorecards` read straight from SQL (not through the card's own code),
and the squad section is checked for internal consistency (its rank, its median line)."""
import html
import re

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine

from lofc.config import settings

# (label, player_id, competition_id, season_id)
CASES = [
    ("winger", 39154, 5, 318),
    ("centre forward", 47357, 5, 318),
    ("goalkeeper", 44875, 3, 318),
    ("2024/25, no physical data", 39154, 5, 317),
    ("2026/27", 47357, 5, 319),
    ("Leyton Orient player", 24835, 4, 318),
    ("loanee at Orient", 391964, 903, 318),
    ("scout reports", 52132, 3, 318),
    ("injuries, two leagues", 3581, 3, 318),
]
IDS = [c[0] for c in CASES]


@pytest.fixture(scope="module")
def engine():
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    return e


@pytest.fixture(scope="module")
def cards(engine):
    from lofc.core import card
    out = {}
    for label, p, c, s in CASES:
        out[label] = card.build_card(engine, p, c, s)
    return out


def _plain(markup: str) -> str:
    markup = re.sub(r"<style>.*?</style>", "", markup, flags=re.S)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup))).strip()


def _same(a, b):
    if a is None or (isinstance(a, float) and np.isnan(a)):
        return b is None or (isinstance(b, float) and np.isnan(b))
    if isinstance(a, (float, np.floating)) and not isinstance(b, (str, bool)):
        return b is not None and abs(float(a) - float(b)) < 1e-9
    return a == b


@pytest.mark.parametrize("label,p,c,s", CASES, ids=IDS)
def test_card_exists_and_has_every_section(cards, label, p, s, c):
    d = cards[label]
    assert d is not None
    assert set(d) >= {"meta", "header", "rating", "season_by_season", "current_form", "style",
                      "season_output", "impect", "performance", "packing_zones", "receptions",
                      "physical", "scout_reports", "scout_assessment", "availability"}
    assert d["meta"]["player_id"] == p and d["meta"]["season_id"] == s


def test_unknown_player_season_is_none(engine):
    from lofc.core import card
    assert card.build_card(engine, 1, 1, 318) is None


def _no_leaked_blank(x, path="$"):
    """Blanks are null in the JSON: never the text None / nan / NaN / undefined."""
    if isinstance(x, dict):
        for k, v in x.items():
            _no_leaked_blank(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            _no_leaked_blank(v, f"{path}[{i}]")
    elif isinstance(x, str):
        assert not re.fullmatch(r"\s*(None|nan|NaN|undefined|null)\s*", x), path
    elif isinstance(x, float):
        assert np.isfinite(x), path


@pytest.mark.parametrize("label", IDS)
def test_json_has_no_leaked_blanks_and_serialises(cards, label):
    import json
    json.dumps(cards[label], allow_nan=False)
    _no_leaked_blank(cards[label])


# --- the card's input row = the Players pool's row ----------------------------------------------
@pytest.mark.parametrize("label,p,c,s", [x for x in CASES if x[0] in
                                         ("winger", "centre forward", "goalkeeper", "scout reports",
                                          "Leyton Orient player", "2024/25, no physical data")],
                         ids=lambda v: v if isinstance(v, str) else None)
def test_row_equals_the_players_pool_row(label, p, c, s):
    from lofc.core import card
    from lofc.core.players_pool import PoolFilters, build_pool
    row, lens, reason = card.card_row(p, c, s)
    pos = row["position_group"]
    pool = build_pool(PoolFilters(season_id=s, position=pos)).pool
    hit = pool[(pool["player_id"] == p) & (pool["competition_id"] == c)]
    if hit.empty:
        pytest.skip("not in the ranked pool (not rated)")
    srow = hit.iloc[0]
    assert reason == "ok"
    for col in ["objective_composite", "performance_band", "physical_band", "financial_band",
                "resale_band", "psychological_band", "medical_band", "veto", "below_min_composite",
                "peer_count", "market_value_eur", "fair_value_eur", "estimated_weekly_wage_gbp",
                "wage_ceiling_gbp", "style_label", "age", "foot", "height_cm", "nationality",
                "minutes", "team_name", "league", "contract_until", "tm_player_id"]:
        if col in srow.index:
            assert _same(row.get(col), srow[col]) or (pd.isna(row.get(col)) and pd.isna(srow[col])), col
    for col in [x for x in srow.index if x.startswith("fit.")]:
        assert _same(row.get(col), srow[col]) or (pd.isna(row.get(col)) and pd.isna(srow[col])), col


# --- rating tiles + rank ---------------------------------------------------------------------------
@pytest.mark.parametrize("label,p,c,s", CASES, ids=IDS)
def test_rating_tiles_and_rank_match_the_scorecard(cards, label, p, c, s):
    from lofc.dashboard import loaders as L
    from lofc.model import scorecard as sc
    from lofc.model.score import POSITION_ROLE  # noqa: F401
    d = cards[label]
    stored = L._stored_scorecards(s)
    mine = stored[(stored["player_id"] == p) & (stored["competition_id"] == c)
                  & (stored["archetype"] == "All Metrics")]
    pos = d["meta"]["position"]
    pool = stored[(stored["archetype"] == "All Metrics") & (stored["competition_id"] == c)
                  & (stored["position_group"] == pos)]
    rated = (not mine.empty and pd.notna(mine.iloc[0]["objective_composite"])
             and not sc.pool_is_thin(len(pool)))
    R = d["rating"]
    if not rated:
        assert R["overall"]["value"] is None and R["overall"]["rank_text"] is None
        assert R["not_rated"]
        return
    r = mine.iloc[0]
    assert R["overall"]["value"] == pytest.approx(float(r["objective_composite"]))
    assert R["performance"]["value"] == pytest.approx(float(r["performance_band"]))
    assert (R["physical"]["value"] is None) == pd.isna(r["physical_band"])
    # "Nth of M": rank among the same league, season, position (ties share the better place)
    ranked = pool[pool["objective_composite"].notna()]
    rank = int((ranked["objective_composite"] > r["objective_composite"]).sum()) + 1
    assert R["overall"]["rank_text"].startswith(f"{rank}") and f"of {len(ranked)} in this league" in R["overall"]["rank_text"]
    assert R["not_rated"] is None


# --- header: the Streamlit header's own HTML says the same -------------------------------------------
@pytest.mark.parametrize("label,p,c,s", CASES, ids=IDS)
def test_header_matches_player_header_html(cards, label, p, c, s):
    from lofc.core import card
    from lofc.dashboard import loaders as L
    from lofc.dashboard import player_header
    d = cards[label]["header"]
    row, _, _ = card.card_row(p, c, s)
    shares = L.load_position_shares(p, c, s)
    loan = L.load_loan_for_player(p)
    hrow = player_header.with_current_club(row, L.load_current_clubs())
    page = player_header.build(hrow, shares, loan)
    text = _plain(page)
    assert d["name"] in text
    assert player_header.club_text(row.get("team_name") or "", hrow.get("current_club")) == d["club_text"]
    for cell in d["register"]:
        assert f"{cell['label']} {cell['value'] or 'not recorded'}" in text, cell
    strip = _plain(player_header.status_strip(row, loan))
    chips = ["".join(t for t, _ in d["contract"]["parts"])] + (
        ["".join(t for t, _ in d["loan"]["parts"])] if d["loan"] else [])
    assert strip == " ".join(chips)
    m = d["minutes_by_position"]
    bar = _plain(player_header.minutes_bar(shares, d["position"]))
    if m is None:
        assert bar == ""
    else:
        assert " · ".join(f"{x['position']} {x['share_pct']:.0f}%" for x in m["segments"]) in bar
        assert (m["goals_line"] or "") in bar


# --- season by season: against player_scorecards read straight from SQL --------------------------
@pytest.mark.parametrize("label,p,c,s", CASES, ids=IDS)
def test_season_by_season_matches_sql(engine, cards, label, p, c, s):
    from lofc.dashboard import loaders as L
    from lofc.dashboard.tabs.players import whole_minutes
    sbs = cards[label]["season_by_season"]
    traj = L.load_trajectory()
    traj = traj[traj["player_id"] == p]
    if len(traj) < 2:
        assert sbs["table"] is None and sbs["empty"]
        return
    t = sbs["table"]
    col = {name: i for i, name in enumerate(t["columns"])}
    assert len(t["rows"]) == len(traj)
    sc = pd.read_sql("SELECT player_id, competition_id, season_id, objective_composite, "
                     "performance_band, physical_band FROM player_scorecards "
                     "WHERE archetype = 'All Metrics'", engine)
    # a season in which NOBODY has a physical band: its Overall is blank (the owner's rule)
    rated = sc[sc["objective_composite"].notna()].groupby("season_id").size()
    phys = sc[sc["physical_band"].notna()].groupby("season_id").size()
    no_phys = {int(x) for x in rated.index if int(phys.get(x, 0)) == 0}
    for (_, tr), row in zip(traj.iterrows(), t["rows"]):
        assert row[col["Minutes"]] == whole_minutes(tr["minutes"])
        hit = sc[(sc["player_id"] == p) & (sc["competition_id"] == tr["competition_id"])
                 & (sc["season_id"] == tr["season_id"])]
        for name, src in (("Overall", "objective_composite"), ("Performance", "performance_band"),
                          ("Physical", "physical_band")):
            want = None if hit.empty or pd.isna(hit.iloc[0][src]) else round(float(hit.iloc[0][src]), 2)
            if name == "Overall" and int(tr["season_id"]) in no_phys:
                want = None
            got = row[col[name]]
            assert (got is None and want is None) or got == pytest.approx(want), (tr["season_name"], name)
    assert "no comparison possible" in sbs["note"]
    if no_phys & {int(x) for x in traj["season_id"]}:
        assert "no physical data" in sbs["note"]


def test_2024_25_card_has_no_physical_and_says_so(cards):
    d = cards["2024/25, no physical data"]
    assert d["rating"]["physical"]["value"] is None
    assert "2024/25" in d["season_by_season"]["note"] and "no physical data" in d["season_by_season"]["note"]
    assert d["physical"]["in_rating"] is None and d["physical"]["gap"]


# --- current form: SQL ---------------------------------------------------------------------------------
@pytest.mark.parametrize("label,p,c,s", CASES, ids=IDS)
def test_current_form_matches_sql(engine, cards, label, p, c, s):
    cf_ = cards[label]["current_form"]
    live = settings.live_season_id
    rows = pd.read_sql("SELECT minutes, goals_p90, assists_p90 FROM player_metrics_neutral "
                       "WHERE player_id = %(p)s AND season_id = %(s)s", engine, params={"p": p, "s": live})
    if rows.empty:
        assert cf_["tiles"] is None and cf_["empty"].startswith("No 2026/27 appearances")
        return
    half = lambda v: int(float(v) + 0.5)
    mins = half(rows["minutes"].fillna(0).sum())
    goals = half((rows["goals_p90"].fillna(0) * rows["minutes"].fillna(0) / 90).sum())
    assists = half((rows["assists_p90"].fillna(0) * rows["minutes"].fillna(0) / 90).sum())
    assert [t["value"] for t in cf_["tiles"]] == [f"{mins:,}", str(goals), str(assists)]


# --- percentiles ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("label,p,c,s", CASES, ids=IDS)
def test_percentiles_are_the_scorecard_percentiles(cards, label, p, c, s):
    from lofc.dashboard import loaders as L
    d = cards[label]["performance"]
    pf = L.load_scorecard_percentiles(s)
    mine = pf[(pf["player_id"] == p) & (pf["competition_id"] == c) & (pf["season_id"] == s)]
    t = d["table"]
    if t is None:
        return
    assert not mine.empty
    r = mine.iloc[0]
    from lofc.dashboard.labels import LABELS
    by_label = {LABELS[m]: m for m in pf.columns if m in LABELS}
    ci = {n: i for i, n in enumerate(t["columns"])}
    for row in t["rows"]:
        pct = row[ci["Percentile"]]
        m = by_label.get(row[ci["Metric"]])
        if pct is None:
            continue
        if m is not None:
            assert pct == round(float(r[m]))
    prof = d["profile"]
    if prof:
        for m, v in zip(prof["metrics"], prof["player"]):
            assert v == pytest.approx(float(r[m]))


# --- playing style ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("label,p,c,s", CASES, ids=IDS)
def test_style_fits_are_the_rows_fits(cards, label, p, c, s):
    from lofc.core import card
    from lofc.model.styles import style_pills
    row, _, _ = card.card_row(p, c, s)
    st = cards[label]["style"]
    pills = style_pills(row)
    shown = st["pills"]["strong"] + [f"{x} (leans)" for x in st["pills"]["leans"]]
    if shown:
        assert shown == pills
    if st["fit"]:
        for g in st["fit"]["groups"]:
            for x in g["styles"]:
                assert x["fit"] == pytest.approx(float(row[f"fit.{x['style']}"]))


# --- scouting ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("label,p,c,s", CASES, ids=IDS)
def test_scout_reports_match_sql(engine, cards, label, p, c, s):
    n = int(pd.read_sql("SELECT COUNT(*) n FROM scout_reports WHERE player_id = %(p)s "
                        "AND missing_since IS NULL", engine, params={"p": p})["n"][0])
    S = cards[label]["scout_reports"]
    assert len(S["reports"]) == n
    assert sum(v["count"] for v in S["verdicts"]) <= n
    assert (S["empty"] is not None) == (n == 0)
    if n:
        assert S["heading"] == f"Scout reports ({n})" and S["open_single"] == (n == 1)


def test_player_with_reports_has_them_attributed(cards):
    S = cards["scout reports"]["scout_reports"]
    assert len(S["reports"]) >= 2 and all(r["title"][0][1] for r in S["reports"])   # scout in bold


# --- availability -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("label,p,c,s", CASES, ids=IDS)
def test_availability_matches_the_evidence_module(engine, cards, label, p, c, s):
    from lofc.dashboard import evidence
    from lofc.model.medical import AVAILABILITY_SEASONS, availability_with_evidence, games_missed_in_window
    A = cards[label]["availability"]
    inj = evidence.load_for_player(engine, p)
    assert A["n_spells"] == len(inj)
    window = evidence.resolve_window(s)
    assert A["window"] == (list(window) if window else None)
    if window:
        row = pd.read_sql("SELECT minutes FROM player_metrics_neutral WHERE player_id=%(p)s AND "
                          "competition_id=%(c)s AND season_id=%(s)s", engine, params={"p": p, "c": c, "s": s})
        minutes = int(row["minutes"][0]) if len(row) and pd.notna(row["minutes"][0]) else None
        missed = games_missed_in_window(inj, s)
        ev = availability_with_evidence(inj, missed, c, minutes, seasons=AVAILABILITY_SEASONS, minutes_seasons=1)
        # Text rule (2.36): the same facts in short form -- the window in the figure's label,
        # the status line only when the figure needs one, the league coverage in one line.
        from lofc.core import card as C
        from lofc.store.injuries import COVERAGE
        assert A["caption"] == C.availability_line(ev)
        assert A["tiles"][0]["label"] == C.availability_label(window)
        assert A["tiles"][0]["value"] == ("—" if ev.value is None else f"{ev.value:.0%}")
        assert A["coverage"] == C.coverage_line(COVERAGE.get(c))
    if len(inj):
        if window:
            spells = evidence.spell_rows(inj, window)
            assert A["in_window"]["heading"].endswith(f"{int(spells['in_window'].sum())} spell"
                                                       + ("" if int(spells["in_window"].sum()) == 1 else "s"))
    else:
        assert A["empty"]


# --- physical / zones / impect, against the stored values --------------------------------------------------
def test_physical_distance_is_the_stored_value(engine, cards):
    d = cards["winger"]["physical"]
    row = pd.read_sql("SELECT distance_p90 FROM player_metrics_neutral WHERE player_id=39154 AND "
                      "competition_id=5 AND season_id=318", engine)
    v = float(row["distance_p90"][0])
    names = [r[0] for r in d["in_rating"]["rows"] + (d["other"]["rows"] if d["other"] else [])]
    first = next(r for r in d["in_rating"]["rows"] + d["other"]["rows"] if r[0].startswith("Distance"))
    assert first[1] == f"{v:.1f}" and names


def test_goalkeeper_has_no_physical_gap_line_and_no_output_tiles_for_goals(cards):
    d = cards["goalkeeper"]
    assert d["physical"]["gap"] is None
    labels = [t["label"] for t in d["season_output"]["tiles"]]
    assert "Goals" not in labels and "Minutes" in labels


def test_zone_values_follow_the_unit_rules(engine, cards):
    z = cards["winger"]["packing_zones"]
    assert z and [m["label"] for m in z["value_modes"]] == ["Per match", "Per 90", "Season total"]
    raw = pd.read_sql("SELECT metric, value_p90, total FROM player_detail_metrics WHERE player_id=39154 "
                      "AND competition_id=5 AND season_id=318 AND (metric='zone.total_touches.AM' "
                      "OR metric LIKE 'meta.%%')", engine)
    am = raw[raw["metric"] == "zone.total_touches.AM"].iloc[0]
    cell = z["measures"]["total_touches"]["cells"]["AM"]
    assert cell["per_90"] == f"{float(am['value_p90']):.1f}" and cell["season_total"] == f"{float(am['total']):.0f}"
    matches = float(raw[raw["metric"].str.startswith("meta.")].iloc[0]["total"])
    assert cell["per_match"] == f"{float(am['total']) / matches:.1f}"


# --- Against our <position>s: internal consistency ----------------------------------------------------------------
def _squad(engine, p, c, s, season=None):
    from lofc.core import card, squad
    row, lens, _ = card.card_row(p, c, s)
    return card.clean(squad.section(p, str(row["player_name"]), row["position_group"],
                                    season or s, lens, row.get("birth_date"), row.get("contract_until")))


@pytest.mark.parametrize("label,p,c,s", [x for x in CASES if x[0] != "goalkeeper"], ids=lambda v: v if isinstance(v, str) else None)
def test_squad_rank_is_counted_from_its_own_table(engine, label, p, c, s):
    S = _squad(engine, p, c, s)
    if S["empty"]:
        return
    rows = S["table"]
    assert rows[0]["is_target"] and not any(r["is_target"] for r in rows[1:])
    ours = [r["overall"] for r in rows[1:] if r["overall"] is not None]
    if rows[0]["overall"] is None:
        assert S["verdict"]["rank_text"] == "—"
    else:
        rank = 1 + sum(1 for x in ours if x > rows[0]["overall"])
        assert S["verdict"]["rank"] == rank and S["verdict"]["of"] == len(ours) + 1
    assert S["verdict"]["our_best"] == (max(ours) if ours else None)
    # unrated rows say why, in words; rated rows have all three chips
    for r in rows:
        assert (r["unrated"] is None) == (r["overall"] is not None)


def test_orient_player_is_compared_with_the_others_not_himself(engine):
    S = _squad(engine, 24835, 4, 318)           # Aaron Connolly, a current Orient centre forward
    assert S["target_is_ours"] and S["title"].startswith("Against our other ")
    assert "Connolly" not in " ".join(r["name"] for r in S["table"][1:])
    assert S["table"][0]["name"] == "Aaron Connolly"


def test_orient_line_is_the_median_of_the_others_percentiles(engine):
    S = _squad(engine, 24835, 4, 319 if False else 318, season=None)
    if not S.get("radar") or not S.get("metrics"):
        pytest.skip("no metric comparison for this season")
    players = S["metrics"]["players"]
    cells = {}
    for sec in S["metrics"]["sections"]:
        for r in sec["rows"]:
            cells[r["label"]] = [x["raw"] for x in r["cells"]]
    idx = [i for i, pl in enumerate(players) if not pl["is_target"]]
    for label, med in zip(S["radar"]["labels"], S["radar"]["ours_median"]):
        vals = [cells[label][i] for i in idx if label in cells and cells[label][i] is not None]
        if med is None:
            assert not vals
        else:
            assert med == pytest.approx(float(np.median(vals)))


def test_orient_is_matched_by_squad_id_not_by_substring(engine):
    from lofc.core import squad
    q = squad.squad()
    names = pd.read_sql("SELECT player_id, club_name, impect_squad_id FROM player_current_club "
                        "WHERE player_id = ANY(%(i)s)", engine,
                        params={"i": [int(x) for x in q["player_id"]]})
    assert all(squad.is_orient_club(n, sid) for n, sid in zip(names["club_name"], names["impect_squad_id"]))
    assert not names["club_name"].str.contains("Lorient", case=False).any()


def test_loanee_is_labelled_as_a_loan_in_our_squad_table(engine):
    S = _squad(engine, 24835, 4, 318)
    notes = [r["note"] for r in S["table"][1:] if r["note"]]
    assert any(n.startswith("On loan from ") for n in notes) or any(n.startswith("Joined from") for n in notes)


# --- "Rank as" lens: the same rows the Players page ranks from --------------------------------------
def test_rank_as_lens_equals_the_players_lens_ranking(engine):
    from lofc.core import card
    from lofc.dashboard import loaders as L
    lens = "Direct & 1v1 Specialist"
    d = card.build_card(engine, 39154, 5, 318, rank_as=lens)
    assert d["meta"]["rank_as"] == lens and d["rating"]["overall"]["label"] == f"Composite ({lens})"
    ranking = L.load_scorecards_archetype("Winger", lens, 318)
    r = ranking[(ranking["player_id"] == 39154) & (ranking["competition_id"] == 5)].iloc[0]
    assert d["rating"]["overall"]["value"] == pytest.approx(float(r["objective_composite"]))
    assert d["rating"]["performance"]["value"] == pytest.approx(float(r["performance_band"]))
    pool = ranking[(ranking["competition_id"] == 5) & (ranking["position_group"] == "Winger")
                   & ranking["objective_composite"].notna()]
    rank = int((pool["objective_composite"] > r["objective_composite"]).sum()) + 1
    assert d["rating"]["overall"]["rank_text"] == f"{rank}{'th' if 10 < rank % 100 < 14 else {1:'st',2:'nd',3:'rd'}.get(rank % 10, 'th')} of {len(pool)} in this league"


def test_a_lens_that_is_not_his_positions_is_ignored(engine):
    from lofc.core import card
    d = card.build_card(engine, 44875, 3, 318, rank_as="Direct & 1v1 Specialist")   # a goalkeeper
    assert d["meta"]["rank_as"] == "All Metrics" and d["meta"]["rank_as_options"] == ["All Metrics"]


def test_a_player_under_450_minutes_cannot_be_opened(engine):
    from lofc.core import card
    assert card.build_card(engine, 24835, 4, 319) is None        # 337 minutes: not in the pool


# --- thin peer pool (owner-approved 2026-11-09): no rating, percentiles say how many peers -----
def test_thin_pool_card_names_the_pool_size(engine):
    from lofc.core import card
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING
    d = card.build_card(engine, 2000030124, 901, 319)            # Benjamin Nygren, a thin pool (8 on 2026-11-09, grows in-season)
    n = d["meta"]["thin_pool"]
    assert n is not None and 0 < n < MIN_PEERS_FOR_RANKING
    r = d["rating"]
    assert r["overall"]["value"] is None and r["performance"]["value"] is None
    assert r["physical"]["value"] is None and r["overall"]["rank_text"] is None
    assert r["not_rated"] == f"Not rated: only {n} comparable players (needs {MIN_PEERS_FOR_RANKING})"
    league = d["meta"]["league"]
    assert d["performance"]["sub"] == f"Percentile vs {n} {league} Attacking Mids · band 1–5"
    if d["performance"]["profile"]:
        assert d["performance"]["profile"]["sub"] == f"Percentile vs {n} {league} Attacking Mids"
    assert d["physical"]["sub"] == f"Percentile vs {n} {league} Attacking Mids · rated physical metrics"
    assert d["physical"]["table_sub"] == f"SkillCorner · per 90 · percentile vs {n} {league} Attacking Mids"


def test_a_rated_card_keeps_its_headings(engine):
    from lofc.core import card
    d = card.build_card(engine, 39154, 5, 318)
    league = d["meta"]["league"]
    assert d["meta"]["thin_pool"] is None and d["rating"]["not_rated"] is None
    assert d["performance"]["sub"] == f"Percentile vs {league} Wingers · band 1–5"
    assert d["performance"]["profile"]["sub"] == f"Percentile vs {league} Wingers"
    assert d["physical"]["sub"] == f"Percentile vs {league} Wingers · rated physical metrics"
    assert d["physical"]["table_sub"] == f"SkillCorner · per 90 · percentile vs {league} Wingers"
