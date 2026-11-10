"""Every database read the dashboard performs, cached in one place.

All Streamlit @cache_data loaders live here so the data layer is separate from presentation:
the tabs receive DataFrames and never open a connection themselves. Restart the dashboard
container after a pipeline run to pick up fresh data (the caches are time-limited, not
event-driven).

Two kinds of loader (classified in the "Cache policy" block below `get_engine`):
  * PIPELINE data -- long-lived (24 h) and keyed on `data_version()`, so a pipeline write is a
    new cache key and a cache can never outlive the data it holds;
  * USER-written / frequently synced data -- short TTL, not version-keyed (unchanged).
"""

from __future__ import annotations

import functools
import hashlib
import io
import logging
import threading
import time

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

from lofc.config import settings
from lofc.constrain.filters import build_candidates
from lofc.dashboard.labels import LABELS
from lofc.dashboard.seasons import SEASON_REF_DATE, age_reference_date, default_season_id
from lofc.core.infobar import headline_counts
from lofc.model import assessment_status
from lofc.model import club_framework as cf
from lofc.model import metric_registry as reg
from lofc.model import scorecard as scorecard_mod
from lofc.model.financial_resale import financial_resale_bands
from lofc.store import assessments as store_assess

@st.cache_resource
def get_engine():
    # hide_parameters: every auth/user-management call in store/users.py goes through this
    # engine. An IntegrityError (e.g. the create_user username race -- see store/users.py)
    # would otherwise print the failing statement's bound parameters -- including a fresh
    # account's password salt and hash -- into whatever renders the exception. Combined with
    # Streamlit's default showErrorDetails="full" (see .streamlit/config.toml, now "none"),
    # that reached the browser. admin.py's CLI engine already sets this for the same reason;
    # the dashboard's engine did not.
    return create_engine(settings.database_url, hide_parameters=True,
                         pool_pre_ping=True)  # heal after a database restart (2026-11-10)


def _read_sql_copy(sql: str) -> pd.DataFrame:
    """`pd.read_sql` for a LONG, narrow result, via Postgres COPY -> CSV.

    Measured (2026-11-08, 390k-row style-signal read): read_sql 4.1 s, of which the database
    is 0.3 s -- the rest is SQLAlchemy/pandas turning rows into Python objects. COPY + read_csv
    returns the identical frame in 0.9 s. Text columns come back as pandas' string dtype, as
    read_sql returns them. `sql` must be a literal (no bind parameters), so build it from
    ints only. Falls back to read_sql on any failure, so the result is never different."""
    try:
        raw = get_engine().raw_connection()
        try:
            buf = io.StringIO()
            raw.cursor().copy_expert(
                f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)", buf)
        finally:
            raw.close()
        buf.seek(0)
        # Only an empty field is NULL (COPY's csv default); text such as "NA" or "None"
        # stays text, as read_sql would return it.
        frame = pd.read_csv(buf, keep_default_na=False, na_values=[""])
        if frame.empty:                                     # let read_sql define empty dtypes
            return pd.read_sql(sql, get_engine())
        # read_csv reads text as object; read_sql under this pandas gives the string dtype.
        for col in frame.columns[frame.dtypes == object]:
            frame[col] = frame[col].astype("str")
        return frame
    except Exception:                                       # noqa: BLE001
        logging.getLogger(__name__).warning("COPY read failed; using read_sql", exc_info=True)
        return pd.read_sql(sql, get_engine())


# --- cache policy: data-version keyed long caches ---------------------------------------
# Measured on the server (2026-11-02): a warm cache hit is <15 ms, a cold miss costs ~17 s
# across the Players path -- and with a 60-600 s TTL and few users almost every visit was
# cold, as was the first visit after every deploy. Pipeline-written tables change only when
# the pipeline runs, so those loaders now cache for a day, but under a key that includes
# `data_version()`: the moment any table they read is written, the key changes and the next
# call re-reads. The cache can therefore never serve data older than the database.
#
# Classification (see the report / tests/test_loader_cache.py):
#   version-keyed   available_seasons, player_names, load_candidates, load_scorecard_percentiles,
#                   load_percentiles, load_metric_values, player_context_lookup,
#                   load_injuries_for_players, load_wage_framework, load_sc_teams,
#                   load_sc_players, headline*, load_trajectory, load_current_form, season_label,
#                   max_minutes, league_names, load_position_shares, load_other_league_seasons*,
#                   load_previous_ratings*,
#                   load_loans, load_loan_for_player, position_and_league_for, load_loan_status,
#                   load_style_inputs*, load_style_labels*, load_current_clubs, _scorecard_meta
#                   (* also reads player_scorecards -> uses the scorecard version)
#   short TTL kept  load_scorecards, load_scorecards_archetype, _stored_scorecards (carry
#                   `assessed_composite`, rewritten on every assessment save),
#                   load_assessment_status (user-written)
_LONG_TTL = 24 * 3600
_MAX_ENTRIES = 16          # a few seasons x a few wage multipliers; older versions age out

# Tables the version-keyed loaders read. `player_scorecards` is split out because scout
# assessments UPDATE it (assessed_composite): tracking it for every loader would empty the
# 8-second candidate cache on each assessment save for no reason.
_CORE_TABLES = (
    "player_metrics_neutral", "player_season_metrics", "player_scores", "player_percentiles",
    "valuations", "archetypes", "players", "wage_estimates", "wage_framework",
    "identity_profiles", "player_style_signals", "player_current_club", "player_loans",
    "player_injuries", "player_position_shares", "skillcorner_team_season",
    "skillcorner_player_season",
)
_SCORECARD_TABLES = _CORE_TABLES + ("player_scorecards",)
# Extra tables only the web front end's caches are keyed on (`web_data_version`): its caches
# have no time limit, so everything they read must be tracked. Querying their counters here
# does not change the tokens above (`_hash_stats` keeps only the tables asked for).
_WEB_TABLES = _SCORECARD_TABLES + ("player_detail_metrics", "scout_reports",
                                   "scout_assessments", "transfermarkt_squads",
                                   "skillcorner_match_counts")


def _hash_stats(stats: pd.DataFrame, postmaster_start: str, tables) -> str:
    """Short token from the write counters of `tables` plus the server start time (a stats
    reset after a restart/crash could otherwise bring a counter back to an old value)."""
    wanted = set(tables)
    # relfilenode: the table's file id, which changes when it is dropped and recreated or
    # truncated (a database restore) -- the write counter restarts then, and equal counts
    # must not keep an old token (verifier, 2026-11-02).
    files = stats["relfilenode"] if "relfilenode" in stats.columns else [0] * len(stats)
    counts = sorted((str(r), int(w), int(f)) for r, w, f in
                    zip(stats["relname"], stats["writes"], files) if r in wanted)
    return hashlib.sha1(repr((counts, str(postmaster_start))).encode()).hexdigest()[:12]


@st.cache_data(ttl=30, show_spinner=False)
def _table_stats() -> tuple[pd.DataFrame, str]:
    """(write counters per tracked table, postmaster start time): one tiny query, at most
    every 30 s per process. Postgres bumps n_tup_ins/upd/del on every write to a table."""
    engine = get_engine()
    names = ", ".join(f"'{t}'" for t in _WEB_TABLES)
    stats = pd.read_sql(
        "SELECT s.relname, (s.n_tup_ins + s.n_tup_upd + s.n_tup_del) AS writes, "
        "c.relfilenode FROM pg_stat_user_tables s JOIN pg_class c ON c.oid = s.relid "
        f"WHERE s.relname IN ({names})", engine)
    start = pd.read_sql("SELECT pg_postmaster_start_time() AS t", engine)["t"][0]
    return stats, str(start)


def _compute_data_version(with_scorecards: bool = False) -> str:
    try:
        stats, start = _table_stats()
        tables = _SCORECARD_TABLES if with_scorecards else _CORE_TABLES
        # The date is in the token because age is derived from today for the live season.
        return _hash_stats(stats, start, tables) + time.strftime("-%Y%m%d", time.gmtime())
    except Exception:                                       # noqa: BLE001
        # Degrade to a short-TTL-like behaviour, never to stale-forever: the token changes
        # every 10 minutes.
        logging.getLogger(__name__).warning("data_version query failed; using time window",
                                            exc_info=True)
        return f"fallback-{int(time.time() // 600)}"


def web_data_version() -> str:
    """`data_version(with_scorecards=True)` plus the detail metrics, scout reports and scout
    assessments: the key of the web front end's in-process caches, which never expire on a
    timer (a 60 s TTL meant the first click after a quiet minute paid a 1-2 s rebuild).
    Changes within ~30 s of any write to those tables (`_table_stats`)."""
    try:
        stats, start = _table_stats()
        return _hash_stats(stats, start, _WEB_TABLES) + time.strftime("-%Y%m%d", time.gmtime())
    except Exception:                                       # noqa: BLE001
        logging.getLogger(__name__).warning("data_version query failed; using time window",
                                            exc_info=True)
        return f"fallback-{int(time.time() // 600)}"


def data_version(with_scorecards: bool = False) -> str:
    """Token that changes whenever a pipeline-written table the long caches read is written.
    The underlying query is cached 30 s (`_table_stats`), so this costs one tiny query at
    most every 30 s. `with_scorecards=True` also tracks `player_scorecards`."""
    return _compute_data_version(with_scorecards)


def _versioned(with_scorecards: bool = False, max_entries: int = _MAX_ENTRIES):
    """Cache a loader for a day, keyed on `data_version()` (plus its own arguments)."""
    def deco(fn):
        def inner(version, *args, **kwargs):
            return fn(*args, **kwargs)
        # Streamlit keys a cache on the function's module + qualified name (+ source), and
        # every `inner` has identical source -- give each its own name or they would collide.
        inner.__module__ = fn.__module__
        inner.__qualname__ = f"{fn.__qualname__}._versioned"
        inner.__name__ = fn.__name__
        cached = st.cache_data(ttl=_LONG_TTL, max_entries=max_entries,
                               show_spinner=False)(inner)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return cached(data_version(with_scorecards), *args, **kwargs)
        wrapper.clear = cached.clear
        wrapper._is_versioned = True
        return wrapper
    return deco


# --- warm-up -------------------------------------------------------------------------
_warm_lock = threading.Lock()
_last_warmed_version: str | None = None


def _warm_order(seasons: list[int]) -> list[int]:
    """Seasons in warm-up order: the default and live seasons first (what a user opens
    first), then every other season, newest first."""
    first = [s for s in dict.fromkeys(
        [default_season_id(seasons, settings.live_season_id), settings.live_season_id])
        if s in seasons]
    return first + [s for s in seasons if s not in first]


def _warm_caches() -> None:
    """Fill the heavy Players-path caches for EVERY season, one at a time (default and live
    first), so no visit after a restart or a pipeline run pays the cold cost. Measured
    2026-11-08: the first visit to an older season cost up to 29 s, because only the default
    and live seasons were warmed. Never raises; a failure in one loader skips only that one."""
    try:
        seasons = available_seasons()
        for sid in _warm_order(seasons):
            # 1.0 = the wage multiplier app.py uses with the affordability layer off (default)
            for fn, args in ((load_candidates, (1.0, sid)), (load_percentiles, (sid,)),
                             (load_metric_values, (sid,)), (load_scorecard_percentiles, (sid,)),
                             (load_style_labels, (sid,)), (load_scorecards, (sid,)),
                             (load_previous_ratings, (sid,)), (headline, (sid,))):
                try:
                    fn(*args)
                except Exception:                           # noqa: BLE001
                    logging.getLogger(__name__).warning("warm-up of %s failed", fn.__name__,
                                                        exc_info=True)
    except Exception:                                       # noqa: BLE001
        logging.getLogger(__name__).warning("cache warm-up failed", exc_info=True)


def start_warmup_if_needed() -> threading.Thread | None:
    """Start a background warm-up when the data version differs from the last one warmed
    (always true on a fresh process). One at a time per process; returns the thread, or None
    if nothing was started. Cheap to call on every rerun, never raises, never blocks."""
    global _last_warmed_version
    try:
        version = data_version(with_scorecards=True)
        if version == _last_warmed_version or not _warm_lock.acquire(blocking=False):
            return None
        _last_warmed_version = version

        def run():
            try:
                _warm_caches()
            finally:
                _warm_lock.release()
        thread = threading.Thread(target=run, name="lofc-cache-warmup", daemon=True)
        thread.start()
        return thread
    except Exception:                                       # noqa: BLE001
        logging.getLogger(__name__).warning("could not start warm-up", exc_info=True)
        return None


# --- season selection --------------------------------------------------------------
# The platform holds multiple seasons of Impect data. Scoring/ranking is done WITHIN one
# season at a time (so a player appears once, on that season's form, ranked against that
# season's peers, with that season's physical coverage). The default is the latest season;
# 2024/25 stays fully available (switch the sidebar selector) and powers the trajectory
# chart. SkillCorner physical exists for 2025/26 only.
# Contract-expiry horizons for the free-transfer market, as a table so no date is hard-coded
# in the filter (the previous "out of contract by summer 2026" checkbox silently became a
# description of the PAST once that date passed).
#
# English contracts effectively all end on 30 JUNE (of the 1,381 expiry dates we hold, 1,377
# are June and 4 are May; ZERO are January). So there is no such thing as a player "out of
# contract in January" here: the January window matters because a player whose deal ends in
# summer is then inside his final six months, which is the same set as the summer horizon --
# read it off the "Months left" column (<= 6) rather than a separate filter.

@_versioned()
def available_seasons() -> list[int]:
    """Season ids present in the data, latest first (the default is the first)."""
    df = pd.read_sql("SELECT DISTINCT season_id FROM player_metrics_neutral ORDER BY season_id DESC",
                     get_engine())
    return df["season_id"].astype(int).tolist()


@_versioned()
def player_names() -> dict[int, str]:
    """Every player's display name, keyed by player_id, across EVERY competition and season.

    The sign-off queue (spec section 16) lists submitted assessments regardless of the
    sidebar's season/position filters -- like the watchlist, it must resolve a name for a
    player who may sit outside whatever the sidebar currently shows.
    """
    df = pd.read_sql("SELECT player_id, player_name FROM player_metrics_neutral", get_engine())
    return dict(zip(df["player_id"].astype(int), df["player_name"]))


@_versioned()
def load_candidates(wage_ceiling_multiplier: float, season_id: int | None = None) -> pd.DataFrame:
    # build_candidates reads every season of ~10 tables (the 510k-row percentiles table
    # alone is 5 s) and tiers/ages every season, whatever season is asked for -- so the old
    # per-season call paid ~8-25 s for EACH season. Build the all-season frame once (cached
    # on the data version) and slice it: the same rows the old code produced, since it also
    # built every season and filtered last.
    # The players bio query lives in _candidates_all_seasons (checked by test_display_contract).
    out = _candidates_all_seasons(wage_ceiling_multiplier)
    if season_id is not None:                       # rank within one season only
        out = out[out["season_id"] == season_id].reset_index(drop=True)
    return out


@_versioned()
def _candidates_all_seasons(wage_ceiling_multiplier: float) -> pd.DataFrame:
    engine = get_engine()
    # all_leagues: keep EVERY scored player (EFL + Scottish/PL2). Non-EFL players carry
    # NaN market value/wage, so they can't pass the affordability gates, but they are
    # browsable and rankable by quality/style — the merged Shortlist spans all leagues.
    candidates = build_candidates(engine, wage_ceiling_multiplier, all_leagues=True)
    keys = ["player_id", "competition_id", "season_id"]
    archetypes = pd.read_sql("SELECT player_id, competition_id, season_id, cluster_label "
                             "FROM archetypes", engine)
    # Season goals/assists totals + underlying rates, from the combined table (all leagues).
    totals = pd.read_sql("SELECT player_id, competition_id, season_id, np_goals_p90, "
                         "assists_p90, np_xg_p90, xa_p90 FROM player_metrics_neutral", engine)
    # nationality is selected here or it reaches nothing: the player card, the report and
    # the squad view all read this frame. It sat at 97% coverage in `players` while every
    # card printed "not recorded", because the column was never in the SELECT.
    bio = pd.read_sql("SELECT player_id, birth_date, foot, contract_until, height_cm, "
                      "nationality, tm_player_id FROM players", engine)
    out = (candidates.merge(archetypes, on=keys, how="left")
           .merge(totals, on=keys, how="left")
           .merge(bio, on="player_id", how="left"))
    out["contract_until"] = pd.to_datetime(out["contract_until"], errors="coerce")
    out["league"] = out["competition_id"].map(competition_name_by_id()).fillna("—")
    # Age from birth_date (present for ~99% of players in every league) at the season midpoint,
    # so age is not limited to valued EFL players. The valuations age (EFL only) is the fallback
    # for the rare player with no birth date. Implausible results are ignored, not shown.
    out["birth_date"] = pd.to_datetime(out["birth_date"], errors="coerce")
    # Per-season reference date: a completed season keeps its fixed midpoint, the LIVE season
    # uses today. SEASON_REF_DATE[319] is 2027-01-01, so mapping it directly made every
    # 2026/27 player up to a year too old (see seasons.age_reference_date).
    ref = out["season_id"].map(
        lambda sid: age_reference_date(int(sid), settings.live_season_id))
    dob_age = ((ref - out["birth_date"]).dt.days / 365.25).round(1)
    dob_age = dob_age.where(dob_age.between(14, 50))          # drop nonsense before using
    # pd.to_numeric (not a bare fallback): the EFL-only valuations "age" being replaced here
    # can hold a Python None (object dtype) rather than a real NaN for a player it has no
    # value for. `.where()` against an object-dtype column upcasts the whole result to
    # object, mixing float NaN with Python None -- and a NumberColumn later renders that None
    # as the literal text "None" instead of a blank cell. Coercing first keeps "age" a clean
    # float64 column, so "missing" is always NaN, never a stray object.
    fallback_age = pd.to_numeric(out["age"], errors="coerce")
    out["age"] = dob_age.where(dob_age.notna(), fallback_age)
    return out


@st.cache_data(ttl=60)
def load_scorecards(season_id: int | None = None) -> pd.DataFrame:
    """The club's 1-5 composite scorecard per player for one season, read from the persisted
    `player_scorecards` table (computed live as a fallback if it has not been built yet).
    Scored WITHIN the season (percentiles and coverage are that season's), so a player appears
    once. Two composites: objective (Performance + Physical) and full (adds the modelled
    Financial + Resale). Nobody is excluded by the advisory veto/gate flags.

    60s, matching `_stored_scorecards` below (which this reads through) -- see its docstring:
    `assessed_composite` on this frame updates live as scouts work.
    """
    return _build_scorecard_frame(season_id=season_id)


# The columns `model/scorecard.build_scorecards` puts on each record. When zero players in
# the requested season are rankable (e.g. a season three weeks old, still below the 450-minute
# threshold), it returns `pd.DataFrame(records)` with `records = []` -- a frame with NO columns
# at all, not this schema. `_attach_scorecard_meta` below restores this schema before merging,
# the same "well-formed empty frame" principle already used by
# `store/injuries.py::load_for_player` and `model/scout_scores.resolve_bands`.
RAW_SCORECARD_COLUMNS = [
    "player_id", "competition_id", "season_id", "position_group",
    "performance_band", "physical_band", "financial_band", "resale_band",
    "psychological_band", "medical_band",
    "objective_composite", "objective_weight_covered",
    "full_composite", "full_weight_covered",
    "assessed_composite", "assessed_weight_covered",
    "veto", "below_min_composite",
]


def _attach_scorecard_meta(sc: pd.DataFrame, neutral: pd.DataFrame) -> pd.DataFrame:
    """Add player_name, team_name and league to a scorecard frame.

    `sc` can arrive completely columnless (0 rows, 0 columns) when nobody in the requested
    season has reached the rankable-minutes threshold yet -- reindex onto the expected raw
    schema first so the merge below (and every downstream .merge/.groupby/column access)
    sees a well-formed empty frame instead of raising `KeyError: 'player_id'`.
    """
    if sc.empty:
        sc = sc.reindex(columns=RAW_SCORECARD_COLUMNS)
    keys = ["player_id", "competition_id", "season_id"]
    meta = neutral[keys + ["player_name", "team_name"]].drop_duplicates(keys)
    sc = sc.merge(meta, on=keys, how="left")
    sc["league"] = sc["competition_id"].map(competition_name_by_id()).fillna("—")
    return sc


@st.cache_data(ttl=60)
def _stored_scorecards(season_id: int | None = None) -> pd.DataFrame:
    """The persisted club scorecards (`player_scorecards`, written by model/scorecard_run).
    Empty frame if the table has not been built yet — the caller then computes live.

    60s, matching `load_assessment_status`, not the 600s used elsewhere: this table carries
    `assessed_composite`, which `model/assessed_refresh` recomputes and writes immediately on
    every assessment save/sign-off/reject. At 600s a scout who saves an assessment, switches
    to the assessed ranking and does not see their player for up to ten minutes reasonably
    concludes the save failed. `objective_composite`/`performance_band`/etc on this same row
    only change on a pipeline rebuild, so shortening the TTL costs an extra query on a cache
    miss, not correctness.
    """
    where = f"WHERE season_id = {int(season_id)}" if season_id is not None else ""
    try:
        return pd.read_sql(f"SELECT * FROM player_scorecards {where}", get_engine())
    except Exception:                                # table not migrated yet
        return pd.DataFrame()


@_versioned()
def _scorecard_meta(season_id: int | None = None) -> pd.DataFrame:
    """Names/teams to attach to the (short-TTL) scorecard frame. Pipeline data, so it is
    version-cached and read for the one season rather than the whole table every 60 s."""
    where = "WHERE season_id = %(s)s" if season_id is not None else ""
    return pd.read_sql("SELECT player_id, competition_id, season_id, player_name, team_name "
                       f"FROM player_metrics_neutral {where}", get_engine(),
                       params={"s": int(season_id)} if season_id is not None else None)


def _build_scorecard_frame(archetype_by_position: dict[str, str] | None = None,
                           season_id: int | None = None) -> pd.DataFrame:
    """One scorecard row per player for the requested archetype per position.

    Reads the PERSISTED table (fast: the pipeline already did the maths). Falls back to
    computing live if the table is empty — so the dashboard still works on a database where
    the scorecard stage has not run yet.
    """
    engine = get_engine()
    stored = _stored_scorecards(season_id)
    if not stored.empty:
        # Keep, per position, the row whose archetype is the one asked for (default otherwise).
        # An archetype absent from the stored table silently falls back to the default, so a
        # new lens can never blank the ranking.
        available = set(stored["archetype"].unique())
        by_position = {p: a for p, a in (archetype_by_position or {}).items() if a in available}
        wanted = stored["position_group"].map(
            lambda p: by_position.get(p, cf.DEFAULT_ARCHETYPE))
        sc = stored[stored["archetype"] == wanted].drop(columns=["id", "archetype"],
                                                        errors="ignore")
        return _attach_scorecard_meta(sc.reset_index(drop=True), _scorecard_meta(season_id))

    # Fallback: no persisted scorecards yet -> compute them live, exactly as before.
    neutral = pd.read_sql("SELECT * FROM player_metrics_neutral", engine)
    if season_id is not None:                       # score within one season only
        neutral = neutral[neutral["season_id"] == season_id]
    fr = financial_resale_bands(engine)
    sc = scorecard_mod.build_scorecards(neutral, financial_resale=fr,
                                        archetype_by_position=archetype_by_position)
    return _attach_scorecard_meta(sc, neutral)


@st.cache_data(ttl=60)
def load_scorecards_archetype(position: str, archetype: str, season_id: int | None = None) -> pd.DataFrame:
    """Scorecards with one position's Performance dimension scored on a chosen archetype's
    metric subset (the archetype lens). Only that position's rows differ from the default.

    60s -- see `load_scorecards`; the same `assessed_composite` freshness concern applies to
    the archetype-lens rows used by the Players tab's assessed-ranking toggle.
    """
    return _build_scorecard_frame(archetype_by_position={position: archetype}, season_id=season_id)


@_versioned()
def load_scorecard_percentiles(season_id: int | None = None) -> pd.DataFrame:
    """Each player's direction-aware percentile per metric (within season + position + league),
    so a selected player's scorecard can show the metric-by-metric detail behind each dimension."""
    # One season only: this used to read the whole table (every season, ~3 s) and filter in
    # pandas. SELECT * for that season, not a column list: `metric_percentiles` ranks every
    # column that is not a key/meta column, so the set of columns is the set of metrics.
    if season_id is not None:
        neutral = pd.read_sql("SELECT * FROM player_metrics_neutral WHERE season_id = %(s)s",
                              get_engine(), params={"s": int(season_id)})
    else:
        neutral = pd.read_sql("SELECT * FROM player_metrics_neutral", get_engine())
    return scorecard_mod.metric_percentiles(neutral).reset_index()


@_versioned()
def load_percentiles(season_id: int | None = None) -> pd.DataFrame:
    # One season, keyed by player AND league: a mid-season mover (e.g. League Two to National
    # League in January) legitimately has one row per league. Other seasons stay in the DB
    # for the trajectory chart.
    where = (f"season_id = {int(season_id)}" if season_id is not None
             else "season_id = (SELECT MAX(season_id) FROM player_percentiles)")
    return _read_sql_copy(
        f"SELECT player_id, competition_id, metric, percentile FROM player_percentiles "
        f"WHERE {where}")


# Metrics the club framework treats as goalkeeper-only: the stored metric a GK club-metric
# resolves to (club_framework.CLUB_SUCCESSOR) that appears in NO outfield position's
# PERFORMANCE_METRICS/PHYSICAL_METRICS list, plus gk_conceded_p90 (not itself scored, but
# unambiguously a goalkeeper concept by name). `player_metrics_neutral` carries a real,
# non-null value for these on every position, not just Goalkeeper: the underlying Impect
# columns (e.g. CONCEDED_POSTSHOT_XG, CONCEDED_GOALS) are populated per player-position-row
# as team defensive context ("conceded while this player was on the pitch"), not an
# individual save-quality figure -- confirmed non-zero for outfield rows in the landed data.
# Deriving the metric is correct in general; only the "goalkeeper" framing is wrong for a
# player whose season position is not Goalkeeper. Nulling it here (not at derivation) keeps
# the neutral table's raw numbers intact for reuse, and masks only where the goalkeeper
# label is actually asserted -- the profile's tracked-metrics view. Scoring is unaffected:
# club_framework.PERFORMANCE_METRICS never lists these for an outfield position, so they
# never fed a percentile/band for one regardless of this table's contents.
GOALKEEPER_ONLY_METRICS = [
    "gk_shot_stopping_pct", "gk_gsaa_p90", "gk_conceded_p90", "gk_catches_p90",
    "defensive_touches_outside_box_p90", "gk_saves_p90", "save_pct",
    # Their retired StatsBomb-advanced-endpoint namesakes (superseded by the Impect stand-ins
    # two lines up via CLUB_SUCCESSOR, but the raw columns still exist in the registry --
    # currently NULL for every position in the data checked, so no live symptom today, but
    # the same defect class would reappear silently if that source is ever repopulated).
    "gk_claims_pct", "gk_aggressive_distance",
]


def _mask_goalkeeper_only_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """NaN out goalkeeper-only metrics for every row whose position_group is not
    Goalkeeper. Never turns a missing value into 0 -- a metric a source never populated is
    already NaN; this only adds NaN for the position-mismatch case, on top of that."""
    if "position_group" not in frame.columns:
        return frame
    frame = frame.copy()
    not_gk = frame["position_group"] != "Goalkeeper"
    for col in GOALKEEPER_ONLY_METRICS:
        if col in frame.columns:
            frame.loc[not_gk, col] = pd.NA
    return frame


@_versioned()
def load_metric_values(season_id: int | None = None) -> pd.DataFrame:
    """Raw per-90 (and rate) values for every metric, for the profile's full-stats table,
    for one season. Reads the combined table so it covers ALL leagues (including the
    Impect-spined Scottish/PL2 ones) and matches exactly the values scoring uses -- except
    the goalkeeper-only metrics (see `GOALKEEPER_ONLY_METRICS`), which are masked to NaN for
    every non-Goalkeeper row before this returns; scoring already never reads them for an
    outfield position, so nothing scored changes."""
    engine = get_engine()
    available = pd.read_sql("SELECT * FROM player_metrics_neutral LIMIT 0", engine).columns
    # Every registry metric (incl. physical + club-framework metrics), so the unified detail's
    # grand table has a per-90/total for each dimension's metrics, not just the LABELS set.
    metric_names = [s.name for s in reg.REGISTRY]
    cols = [c for c in dict.fromkeys(list(LABELS) + metric_names) if c in available]
    where = (f"season_id = {int(season_id)}" if season_id is not None
             else "season_id = (SELECT MAX(season_id) FROM player_metrics_neutral)")
    select_cols = ["player_id", "competition_id", "position_group"] + [c for c in cols if c != "position_group"]
    frame = pd.read_sql(
        f"SELECT {', '.join(select_cols)} FROM player_metrics_neutral "
        f"WHERE {where}", engine)
    return _mask_goalkeeper_only_metrics(frame).drop(columns=["position_group"])


@st.cache_data(ttl=60)
def load_assessment_status(season_id: int | None = None) -> pd.DataFrame:
    """One status per assessed player-season.

    A 60s TTL rather than the 600s used elsewhere: assessments change while people are
    working, and a scout who saves an assessment and does not see the badge update for ten
    minutes will reasonably conclude the save failed.
    """
    return assessment_status_frame(season_id)


def assessment_status_frame(season_id: int | None = None) -> pd.DataFrame:
    """`load_assessment_status` without its cache (the web front end keys its own copy on
    `web_data_version`)."""
    frame = store_assess.load_all(get_engine())
    if season_id is not None and not frame.empty:
        frame = frame[frame["season_id"] == season_id]
    return assessment_status.per_player(frame)


@_versioned()
def player_context_lookup() -> pd.DataFrame:
    """position_group and minutes for every (player, competition, season) row that has
    Impect data, unfiltered by the sidebar -- for the sign-off queue's conflict view
    (`dashboard/tabs/signoff.py`), which needs the club's criteria list and the evidence
    panel for a contested player-season that may sit in a different season than whatever the
    sidebar currently shows (matches `player_names`' reasoning, same file)."""
    return pd.read_sql(
        "SELECT player_id, competition_id, season_id, position_group, minutes "
        "FROM player_metrics_neutral", get_engine())


_INJURY_COLUMNS = ["player_id", "date_from", "date_until", "injury_category",
                   "injury_type_raw", "days_out", "games_missed"]


@_versioned(max_entries=256)  # keyed per player
def load_injuries_for_players(player_ids: tuple[int, ...]) -> pd.DataFrame:
    """Every recorded Transfermarkt injury spell for a set of players, for the watchlist's
    injury-record column.

    `store/injuries.py::load_for_player` is one-player-at-a-time -- exactly right for the
    evidence panel (one player), wrong for a table of watched players (would be N queries).
    This is the same table, read in bulk instead. `player_ids` is a tuple (not a list) so
    it is hashable and can be an `st.cache_data` key. A well-formed empty frame (the full
    column set) on an empty request or a database that has not been migrated yet, matching
    the "empty but well-formed" convention already used by `_stored_scorecards`,
    `load_sc_teams`/`load_sc_players` and `store/injuries.py::load_for_player`.
    """
    if not player_ids:
        return pd.DataFrame(columns=_INJURY_COLUMNS)
    ids = ",".join(str(int(p)) for p in player_ids)
    try:
        return pd.read_sql(
            f"SELECT {', '.join(_INJURY_COLUMNS)} FROM player_injuries "
            f"WHERE player_id IN ({ids})", get_engine())
    except Exception:                                # table not migrated yet
        return pd.DataFrame(columns=_INJURY_COLUMNS)


@_versioned()
def load_wage_framework() -> pd.DataFrame:
    return pd.read_sql("SELECT position_group, age_band, weekly_wage_ceiling_gbp FROM wage_framework",
                       get_engine())


# The 8 club Physical metrics with a short label + unit, for the raw cross-league comparison.

@_versioned()
def load_sc_teams() -> pd.DataFrame:
    """Team-level SkillCorner physical output: all 24 League One clubs."""
    try:
        teams = pd.read_sql("SELECT * FROM skillcorner_team_season", get_engine())
    except Exception:
        return pd.DataFrame()
    teams["display_name"] = teams["team_name"].str.replace(r"\s+FC$", "", regex=True)
    return teams


@_versioned()
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
    # A mid-season mover has one latest-season row per club, so dedupe to one
    # position per player or the join fans the 21-row squad table out with copies.
    positions = positions.drop_duplicates("player_id")
    return players.merge(positions, on="player_id", how="left")


@_versioned(with_scorecards=True)
def headline(season_id: int | None = None) -> tuple[int, int, int]:
    """Top-level counts for the KPI strip, for ONE season (from the combined table, so all 7
    leagues — not the EFL-only spine): (players with any data, players with a rating, leagues).

    Both player counts are returned because they differ by everyone under the minutes floor
    (4,376 vs 3,229 on 2025/26), and the Players table lists only the rated ones. Showing the
    wider count alone led a reader to divide a table count by it."""
    return headline_counts(get_engine(), season_id)


@_versioned()
def load_trajectory() -> pd.DataFrame:
    """Every season row per player, for the profile's season-by-season view.

    The dashboard's scores and prices are pinned to the latest season; earlier
    seasons exist purely to show direction (improving or declining). A mid-season
    mover has one row per league, deliberately: rates are league-relative.
    """
    # Minutes, goals and assists come from the Impect-spined combined table (the card's tiles
    # and header read it), falling back to the older table only where it has no row.
    # Assists were 4 here against 7 in the season tile: the older table's raw total is the
    # retired provider's; assists_p90 is Impect's, and Impect is the platform's definition.
    # Measured live: raw goals differ in 2% of rows, assists in 31%, minutes (>1) in 60%.
    raw = pd.read_sql(
        "SELECT m.player_id, m.competition_id, m.season_id, m.season_name, m.competition_name, "
        "m.team_name, m.minutes, m.goals, m.assists, m.np_xg_p90, m.xa_p90, "
        "m.save_pct, m.gk_saves_p90, m.tackles_p90, m.interceptions_p90, m.pass_completion_pct, "
        "n.minutes AS n_minutes, n.goals_p90 AS n_goals_p90, n.assists_p90 AS n_assists_p90 "
        "FROM player_season_metrics m LEFT JOIN player_metrics_neutral n "
        " ON n.player_id = m.player_id AND n.competition_id = m.competition_id "
        " AND n.season_id = m.season_id ORDER BY m.season_id DESC", get_engine())
    return trajectory_from_rows(raw)


def round_half_up(value) -> int:
    """Whole number, .5 rounds UP -- the one rule for every minutes / goals / assists figure
    on the card (Python round() and SQL ROUND on a double are half-to-even)."""
    return int(float(value) + 0.5)


def trajectory_from_rows(raw: pd.DataFrame) -> pd.DataFrame:
    """Prefer the combined table's minutes and its per-90 derived goals / assists totals;
    rows with no combined-table figures keep the older table's. Rounding is half-up, in
    Python, so it matches the card's tiles."""
    out = raw.copy()
    minutes = out["n_minutes"].astype(float)
    for col, rate in (("goals", "n_goals_p90"), ("assists", "n_assists_p90")):
        derived = (out[rate].astype(float) * minutes / 90).map(
            lambda v: round_half_up(v) if pd.notna(v) else float("nan"))
        out[col] = derived.where(derived.notna(), out[col])
    out["minutes"] = minutes.where(minutes.notna(), out["minutes"])
    return out.drop(columns=["n_minutes", "n_goals_p90", "n_assists_p90"])



_CURRENT_FORM_COLUMNS = ["player_id", "competition_id", "season_id", "minutes",
                         "goals_p90", "assists_p90"]


@_versioned()
def load_current_form() -> pd.DataFrame:
    """Every player's row(s) for the LIVE season (`settings.live_season_id`) -- minutes and
    the rates the counting stats are derived from -- for the profile's "current form" section.

    Reads `player_metrics_neutral` (the Impect-spined COMBINED table, all leagues), not
    `player_season_metrics`: the latter is the StatsBomb-era EFL-only spine and holds no
    season_id 319 rows at all (every 2026/27 league, EFL included, is Impect-sourced --
    `config.DEFAULT_IMPECT_TARGETS`). `player_metrics_neutral` has no raw season totals or a
    match-played count for the Impect-sourced leagues, only per-90 rates and minutes;
    `tabs/players.py::_current_form_summary` derives goals/assists totals from the rate the
    same way `_full_stats_table`/`_season_total` already do for non-EFL leagues elsewhere on
    this page, and does not invent an appearances count the data does not hold.

    This is never scored: 2026/27 has real data -- 1,771 players, 6 leagues -- but 85 minutes
    average and 207 top, nowhere near the 450-minute rankable threshold, so no composite
    exists here and none is invented. A player absent from this frame has no 2026/27 row at
    all (he has not appeared, or his league has not started), which the caller states plainly
    rather than showing zeros.

    600s (not the 60s used for assessment-derived caches): this reads pipeline output, which
    changes only when the live-season ingest runs, not while a scout is working.

    A well-formed empty frame (not a bare `pd.DataFrame()`) when no live season is configured
    (`LIVE_SEASON_ID` set to `None` out of season) so callers can filter/select columns on it
    unconditionally.
    """
    live = settings.live_season_id
    if live is None:
        return pd.DataFrame(columns=_CURRENT_FORM_COLUMNS)
    return pd.read_sql(
        f"SELECT {', '.join(_CURRENT_FORM_COLUMNS)} FROM player_metrics_neutral "
        f"WHERE season_id = {int(live)}", get_engine())


@_versioned()
def season_label() -> str:
    """The season shown in the KPI strip: the latest one in the data (e.g. '2025/26')."""
    name = pd.read_sql(
        "SELECT season_name FROM player_season_metrics "
        "WHERE season_id = (SELECT MAX(season_id) FROM player_season_metrics) LIMIT 1",
        get_engine())["season_name"]
    return str(name[0]).replace("/20", "/") if len(name) else "—"


@_versioned()
def max_minutes() -> int:
    """Data-driven top of the minutes slider (a season's real maximum, not a guess)."""
    value = pd.read_sql(
        "SELECT MAX(minutes) AS m FROM player_season_metrics "
        "WHERE season_id = (SELECT MAX(season_id) FROM player_season_metrics)",
        get_engine())["m"][0]
    return int(value) if pd.notna(value) else 3500


def competition_name_by_id() -> dict[int, str]:
    """competition_id -> clean league name, across BOTH StatsBomb-spined (EFL) and
    Impect-spined (Scottish/PL2) leagues, so every league in the combined table names."""
    # One source for every league name: the registry (lofc/leagues.py).
    from lofc.leagues import league_names
    return league_names()


@_versioned()
def league_names() -> list[str]:
    """ALL league names present in the combined table (EFL + Scottish/PL2). The Shortlist
    spans every league; players with no market value simply can't pass the money gates."""
    ids = pd.read_sql("SELECT DISTINCT competition_id FROM player_metrics_neutral",
                      get_engine())["competition_id"]
    name_by_id = competition_name_by_id()
    return [name_by_id.get(int(i), f"League {int(i)}") for i in sorted(ids)]


@_versioned(max_entries=256)  # keyed per player
def load_position_shares(player_id: int, competition_id: int, season_id: int):
    """How this player's minutes split across position groups, largest first.

    The platform names ONE position and scores him against that group's peers. For roughly
    one player in ten that label covers under half his season, so the split belongs beside
    the label rather than only on the exported report.

    Display only: nothing here feeds a score.
    """
    import pandas as pd
    return pd.read_sql(
        "SELECT position_group, minutes, share, goals, assists "
        "FROM player_position_shares "
        "WHERE player_id = %(p)s AND competition_id = %(c)s AND season_id = %(s)s "
        "ORDER BY share DESC",
        get_engine(), params={"p": int(player_id), "c": int(competition_id),
                              "s": int(season_id)})


@_versioned(with_scorecards=True)
def load_previous_ratings(season_id: int) -> pd.DataFrame:
    """Each player's rating in the PREVIOUS season (season_id - 1), one row per player.

    Columns: player_id, prev_composite (objective_composite), prev_physical (physical_band),
    prev_league (league name), prev_position (position group), prev_performance
    (performance_band; appended last so existing positional readers are unaffected). Merge on player_id ONLY: a
    player may have changed club, league or position since, and that is the point. Players
    with no previous-season rating are simply absent -- callers show a blank.

    A player who played in two leagues that season (a loan) has two scorecards; the one with
    the MOST minutes is kept (the same row the platform treats as his main season). Uses the
    'All Metrics' scorecard, as the Players list does. Reused by the Compare and Players pages.
    """
    df = pd.read_sql(
        "SELECT s.player_id, s.competition_id, s.objective_composite, s.physical_band, "
        "       s.performance_band, s.position_group, n.minutes "
        "FROM player_scorecards s "
        "JOIN player_metrics_neutral n ON n.player_id = s.player_id "
        " AND n.competition_id = s.competition_id AND n.season_id = s.season_id "
        "WHERE s.season_id = %(s)s AND s.archetype = 'All Metrics'",
        get_engine(), params={"s": int(season_id) - 1})
    cols = ["player_id", "prev_composite", "prev_physical", "prev_league", "prev_position",
            "prev_performance"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = (df.sort_values("minutes", ascending=False, na_position="last", kind="stable")
          .drop_duplicates(subset="player_id", keep="first"))
    df["prev_league"] = df["competition_id"].map(competition_name_by_id())
    df = df.rename(columns={"objective_composite": "prev_composite",
                            "physical_band": "prev_physical", "position_group": "prev_position",
                            "performance_band": "prev_performance"})
    return df[cols].reset_index(drop=True)


@_versioned(with_scorecards=True, max_entries=256)  # keyed per player
def load_other_league_seasons(player_id: int, competition_id: int, season_id: int):
    """The SAME player's other league-seasons in this season, with their composites.

    A player on loan can appear twice in one season -- a Spurs U21 winger with 783 minutes
    in PL2 and 1,074 in League Two gets a row and a score in each, because a percentile is
    only meaningful inside one league. Scanning a list, that reads as a duplicate.

    It is the opposite: the pair is one of the most useful signals the platform holds.
    Aaron Loupalo-Bi rates 3.96 against PL2 peers and 2.63 in senior League Two -- exactly
    the "does it hold up a level up?" question a loan is meant to answer. 116 players in
    25/26 have such a pair.
    """
    import pandas as pd
    return pd.read_sql(
        "SELECT s.competition_id, n.team_name, n.minutes, n.position_group, "
        "       s.objective_composite "
        "FROM player_scorecards s "
        "JOIN player_metrics_neutral n ON n.player_id = s.player_id "
        " AND n.competition_id = s.competition_id AND n.season_id = s.season_id "
        "WHERE s.player_id = %(p)s AND s.season_id = %(s)s "
        "  AND s.archetype = 'All Metrics' AND s.competition_id <> %(c)s "
        "ORDER BY n.minutes DESC",
        get_engine(), params={"p": int(player_id), "c": int(competition_id),
                              "s": int(season_id)})


# Kept as an alias: the function was private and is imported under the old name
# by tests and by dashboard modules written before the player card needed it.
_competition_name_by_id = competition_name_by_id


@_versioned()
def load_loans(season_id: int | None = None):
    """Every loan we hold, club by club, with parent club and loan end date.

    The January-window view: `loan_ends` is what separates a player going back to his
    parent club in the summer from one who is actually gettable now.
    """
    where = "WHERE season_id = %(s)s" if season_id else ""
    return pd.read_sql(
        "SELECT club_name, player_name, parent_club, loan_ends, competition_id, "
        "       player_id, tm_player_id, season_id "
        f"FROM player_loans {where} ORDER BY club_name, loan_ends NULLS LAST, player_name",
        get_engine(), params={"s": season_id} if season_id else None)


@_versioned(max_entries=256)  # keyed per player
def load_loan_for_player(player_id: int):
    """This player's CURRENT loan, or None.

    Not scoped to the season being VIEWED: "is he on loan right now" is a fact about
    today, exactly like his contract date, and it is what a January decision turns on. A
    recruiter looking at last season's performance still needs to know the player is
    currently on loan somewhere.
    """
    d = pd.read_sql(
        "SELECT club_name, parent_club, loan_ends, season_id FROM player_loans "
        "WHERE player_id = %(p)s ORDER BY season_id DESC LIMIT 1",
        get_engine(), params={"p": int(player_id)})
    return None if d.empty else d.iloc[0]


@_versioned(max_entries=256)  # keyed per player
def position_and_league_for(player_id: int, season_id: int):
    """(position_group, league) for a carried player in the RANKED season, or (None, None).

    Queried from the database rather than resolved against `search_index`, purely because
    of ordering: the sidebar's Position widget is instantiated long before search_index is
    built, and Streamlit forbids writing a widget's session_state key after the widget
    exists. Seeding Position from the page body raised
    "st.session_state.sidebar_position cannot be modified after the widget ... is
    instantiated" and broke the whole page for any carried player.

    Falls back to any league the player appeared in that season, because the squad view is
    current-season and he may since have moved.
    """
    d = pd.read_sql(
        "SELECT position_group, competition_id, minutes FROM player_metrics_neutral "
        "WHERE player_id = %(p)s AND season_id = %(s)s "
        "ORDER BY minutes DESC NULLS LAST LIMIT 1",
        get_engine(), params={"p": int(player_id), "s": int(season_id)})
    if d.empty:
        return None, None
    row = d.iloc[0]
    return str(row["position_group"]), competition_name_by_id().get(
        int(row["competition_id"]))


@_versioned()
def load_loan_status() -> pd.DataFrame:
    """One row per player currently on loan: `on_loan` and `loan_ends`, for the sidebar filter.

    Keyed on player_id ALONE, not on season: a loan is a fact about the player today, while
    the ranking beside it is last season's. Deliberate -- whether he is on loan now is what a
    January decision turns on -- and stated in the filter's help text.

    Where a player has more than one loan row we keep the one with the LATEST end date, so an
    old, expired loan cannot mask a live one -- and `loan_club`/`parent_club` come from that
    SAME row, never mixed across two loans.
    """
    live = settings.live_season_id
    and_season = f"AND season_id = {int(live)}" if live is not None else ""
    frame = pd.read_sql(
        "SELECT DISTINCT ON (player_id) player_id, loan_ends, "
        "       club_name AS loan_club, parent_club "
        f"FROM player_loans WHERE player_id IS NOT NULL {and_season} "
        "ORDER BY player_id, loan_ends DESC NULLS LAST",
        get_engine())
    frame["on_loan"] = True
    frame["loan_ends"] = pd.to_datetime(frame["loan_ends"], errors="coerce")
    return frame


@_versioned(with_scorecards=True)
def load_style_inputs(season_id: int) -> pd.DataFrame:
    """Every player of a season with his raw style signals and his rating, for the Style lab.
    Signals are stored long (player_style_signals) and pivoted here; percentiles are taken by
    the caller so they always use the current minutes and positions."""
    engine = get_engine()
    base = pd.read_sql(
        "SELECT n.player_id, n.competition_id, n.season_id, n.position_group, n.rankable, "
        "       n.player_name, n.team_name, s.objective_composite, s.performance_band "
        "FROM player_metrics_neutral n LEFT JOIN player_scorecards s "
        "  ON s.player_id = n.player_id AND s.competition_id = n.competition_id "
        " AND s.season_id = n.season_id AND s.archetype = 'All Metrics' "
        "WHERE n.season_id = %(s)s", engine, params={"s": int(season_id)})
    sig = _read_sql_copy("SELECT player_id, competition_id, signal, value "
                         f"FROM player_style_signals WHERE season_id = {int(season_id)}")
    if sig.empty:
        return base
    wide = sig.pivot_table(index=["player_id", "competition_id"], columns="signal",
                           values="value").reset_index()
    return base.merge(wide, on=["player_id", "competition_id"], how="left")


@_versioned()
def load_current_clubs() -> pd.DataFrame:
    """player_id -> `current_club`: where he is NOW (Impect), named clubs only. Empty if the
    table is not there yet, so the page never fails over a display extra."""
    try:
        return pd.read_sql("SELECT player_id, club_name AS current_club FROM player_current_club "
                           "WHERE club_name IS NOT NULL", get_engine())
    except Exception:                                         # noqa: BLE001
        return pd.DataFrame(columns=["player_id", "current_club"])


@_versioned(with_scorecards=True)
def load_style_labels(season_id: int) -> pd.DataFrame:
    """Every player's playing-style labels for a season (model/styles.py): `style_label`,
    `tier`, `strong_styles`, `leans_styles` and `fit.<style>`. Fixed thresholds -- the same
    label for every user; tuning happens in the Style lab only."""
    from lofc.model import styles
    frame = load_style_inputs(season_id)
    if frame.empty or not set(styles.SIGNALS) & set(frame.columns):
        return pd.DataFrame(columns=styles.KEY)
    return styles.assign_styles(styles.signal_percentiles(frame))
