"""The sign-off queue: one card per PLAYER, conflicts first, then the ordinary submitted
assessments awaiting approval.

Sign-off (and now reject, Problem 3) are the ONLY gated assessment actions (Decision 16). They
change no score directly and hide no player (Decision 14) -- they mark an assessment reviewed
or declined, and control what may leave the building as final rather than provisional.

Restructured (task: "the sign-off queue lists dimensions, not players") from one card per
ASSESSMENT to one card per PLAYER-SEASON: a player with a psychological and a medical
assessment used to appear twice, and a contested dimension with three competing assessments
appeared three times more -- the approver reassembled the player mentally across scattered
cards. Each card now shows a player-season's Psychological AND Medical state together, every
assessment on either dimension (via `dashboard/assessment_detail.py`, the same component the
player profile uses -- Problem 2, so the criterion-by-criterion detail behind "5, 5, 2" vs "4"
is never a click away on one screen and absent on the other), and whatever action each
dimension's current state calls for.

Decision 17 / task 10 Part B: a contested dimension (two or more unsigned assessments that
disagree) scores nothing until someone with sign-off rights decides. CONFLICTS ARE SHOWN
FIRST, above the ordinary queue -- at the PLAYER level: any player with at least one contested
dimension sorts into the Conflicts section, because a live disagreement is a real work item (a
choice to make), not a lower-priority version of the same review. Four actions per contested
or ordinary-pending dimension, all gated on `auth.can(role, "sign_off")`:

  1. Sign off one of the competing assessments -- that band scores; the others stay on the
     record, unsigned, attributed.
  2. Reject one (Problem 3) -- an optional reason, gated the same way; the assessment stays
     on the record, stops scoring, and leaves the queue. The scout sees why on the profile
     (or sees a plain "no reason recorded" note when none was given).
  3. Enter your own, pre-filled from either competing assessment or blank -- a NEW, separate
     assessment under the approver's own name, signed off in the same action.
  4. Leave it. The player keeps reading "assessments conflict -- not scored".

Layout (frontend-design skill, spec section 16): this is an internal tool with an established
visual language already (bold state-words, bordered containers, `badges.py`'s three-tone
system, `assessment_detail.py`'s tabular per-assessment view) -- extended here, not replaced,
because a working tool used daily benefits more from consistency than novelty. Every
competing assessment for a contested dimension still renders as a matched column inside one
bordered card -- a comparison a reader can take in at a glance -- but that card now sits
inside the player's own card alongside the OTHER dimension, so a reviewer working under time
pressure makes one pass over a player, not two-to-six passes over fragments.
"""

from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

from lofc.dashboard import assessment_detail, badges
from lofc.dashboard.auth import can
from lofc.dashboard.loaders import _competition_name_by_id
from lofc.dashboard.seasons import season_name_for
from lofc.dashboard.session import CurrentUser
from lofc.model import assessment_rules as rules
from lofc.model import club_criteria as cc
from lofc.model import scout_scores
from lofc.store import assessments as store_assess

_BAND_HELP = " · ".join(f"{n} {label}" for n, label in rules.BAND_LABELS.items())
_KEY_COLS = ["player_id", "competition_id", "season_id"]


def _band_select(label: str, key: str, default: int | None = None) -> float | None:
    options = [None] + list(rules.BAND_LABELS)
    index = options.index(default) if default in options else 0
    return st.selectbox(label, options, index=index, key=key,
                        format_func=lambda v: "—" if v is None
                        else f"{v} · {rules.BAND_LABELS[v]}", help=_BAND_HELP)


def _player_context(context: pd.DataFrame, player_id: int, competition_id: int,
                    season_id: int) -> tuple[str | None, int | None]:
    """(position_group, minutes) for one player-season, or (None, None) if this player has
    no Impect row for that triple (e.g. too few minutes to be rankable)."""
    match = context[(context["player_id"] == player_id) &
                    (context["competition_id"] == competition_id) &
                    (context["season_id"] == season_id)]
    if match.empty:
        return None, None
    row = match.iloc[0]
    minutes = row["minutes"]
    return row["position_group"], (int(minutes) if pd.notna(minutes) else None)


def _save_and_sign_off(engine, user: CurrentUser, *, player_id: int, competition_id: int,
                       season_id: int, dimension: str, band: float | None, notes: str | None,
                       criterion_scores: dict[str, int], criterion_passes: dict[str, bool],
                       screening_failed: bool, status: str) -> None:
    """B3: a NEW, separate assessment under the approver's own name -- nothing existing is
    edited or deleted -- signed off in the same action because this happens inside the
    conflict view. The caller only reaches here with `status == 'submitted'` (the button that
    calls this is disabled otherwise), so sign-off is never attempted on a draft.
    """
    try:
        assessment_id = store_assess.save(
            engine, player_id=player_id, competition_id=competition_id, season_id=season_id,
            dimension=dimension, author_id=user.id, band=band, notes=notes,
            criterion_scores=criterion_scores, criterion_passes=criterion_passes,
            screening_failed=screening_failed, status=status)
        if status == "submitted":
            store_assess.sign_off(engine, assessment_id, approver_id=user.id,
                                  now=datetime.datetime.now())
    except Exception as exc:
        st.error(f"Could not save and sign off: {exc}")
        return
    st.success(f"Entered and signed off by {user.full_name}.")
    st.rerun()


def _enter_own_form(engine, user: CurrentUser, player_id: int, competition_id: int,
                    season_id: int, dimension: str, position: str | None,
                    group: pd.DataFrame) -> None:
    """B3: choose a starting point (either competing assessment, or blank), pre-fill the
    form with its criterion scores, mark every changed value ("was 4, now 2"), and submit as
    a new assessment signed off in the same action."""
    if not position or position not in cc.POSITION_GROUPS:
        st.warning("No club criteria are configured for this player's position group, so a "
                   "new assessment cannot be entered from here.")
        return

    key_prefix = f"enterown_{player_id}_{competition_id}_{season_id}_{dimension}"
    starting_points: list[tuple[str, int | None]] = [("Blank", None)]
    for entry in group.itertuples():
        band_txt = "—" if entry.band is None else f"{entry.band:.2f}"
        starting_points.append((f"{entry.author_name} — band {band_txt}", int(entry.id)))
    labels = [label for label, _ in starting_points]
    chosen_label = st.selectbox("Start from", labels, key=f"{key_prefix}_start")
    chosen_id = dict(starting_points)[chosen_label]
    # Every field below is keyed on `chosen_id`, not just `key_prefix`: a Streamlit widget
    # keeps whatever value session_state already holds under its key even when a fresh
    # `index=`/`default=` is passed on a later rerun. Without this, switching "Start from"
    # would change the computed `default` but the widget would keep showing whatever was
    # selected under the OLD starting point -- the pre-fill would silently not apply.
    field_key_prefix = f"{key_prefix}_{chosen_id}"

    prefill_scores: dict[str, int] = {}
    prefill_passes: dict[str, bool] = {}
    prefill_band: float | None = None
    if chosen_id is not None:
        criteria = store_assess.criterion_scores_for(engine, chosen_id)
        for r in criteria.itertuples():
            if pd.notna(r.score):
                prefill_scores[r.criterion_key] = int(r.score)
            if pd.notna(r.passed):
                prefill_passes[r.criterion_key] = bool(r.passed)
        matched = group[group["id"] == chosen_id]
        if not matched.empty and pd.notna(matched.iloc[0]["band"]):
            prefill_band = float(matched.iloc[0]["band"])

    if dimension == scout_scores.PSYCHOLOGICAL:
        scores: dict[str, int] = {}
        for text in cc.PSYCHOLOGICAL_CRITERIA[position]:
            ck = rules.criterion_key(text)
            default = prefill_scores.get(ck)
            value = _band_select(text, key=f"{field_key_prefix}_{ck}", default=default)
            if value is not None:
                scores[ck] = value
            if default is not None and value != default:
                st.caption(f"*was {default}, now {'—' if value is None else value}*")
        band = rules.psychological_band(scores, position)
        status = rules.psychological_status(scores, position)
        if band is None:
            st.info(f"Scored {len(scores)} of {len(cc.PSYCHOLOGICAL_CRITERIA[position])} "
                    "criteria — every criterion must be scored before this can be entered "
                    "and signed off.")
        else:
            st.success(f"Band **{band:.2f}**.")
        notes = st.text_area("Notes (optional)", key=f"{field_key_prefix}_notes")
        if st.button("Enter and sign off", type="primary", key=f"{field_key_prefix}_submit",
                     disabled=(status != "submitted")):
            _save_and_sign_off(engine, user, player_id=player_id, competition_id=competition_id,
                               season_id=season_id, dimension=dimension, band=band,
                               notes=notes or None, criterion_scores=scores,
                               criterion_passes={}, screening_failed=False, status=status)
    else:
        passes: dict[str, bool] = {}
        opts = ["—", "Meets", "Does not meet"]
        for criterion in cc.MEDICAL_CRITERIA[position]:
            ck = rules.criterion_key(criterion.text)
            if criterion.kind == "screening":
                default_pass = prefill_passes.get(ck)
                default_label = ("—" if default_pass is None
                                 else ("Meets" if default_pass else "Does not meet"))
                answer = st.radio(criterion.text, opts, horizontal=True,
                                  index=opts.index(default_label),
                                  key=f"{field_key_prefix}_{ck}")
                if answer != "—":
                    passes[ck] = (answer == "Meets")
                if default_label != "—" and answer != default_label:
                    st.caption(f"*was {default_label}, now {answer}*")
            elif criterion.kind == "protocol":
                st.checkbox(f"{criterion.text} *(club process — not scored)*",
                            key=f"{field_key_prefix}_proto_{ck}", disabled=True)
            else:
                st.caption(f"{criterion.text} *(shown as evidence — see the player's profile)*")

        default_band = int(prefill_band) if prefill_band is not None else None
        band = _band_select("Medical band", key=f"{field_key_prefix}_band", default=default_band)
        st.caption(rules.MEDICAL_CEILING_NOTE)
        if default_band is not None and band != default_band:
            st.caption(f"*was {default_band}, now {'—' if band is None else band}*")

        failed = rules.screening_failed(passes, position)
        if failed:
            st.warning("**One or more screening criteria are not met.** This is a flag, "
                       "not a cap — the band stands unchanged.")
        notes = st.text_area("Notes" + (" (required — a screening criterion failed)"
                                        if failed else " (optional)"),
                             key=f"{field_key_prefix}_notes")
        status = rules.medical_status(band, passes, position)
        if status != "submitted":
            st.caption("A band, and an answer for every screening criterion, are required "
                       "before this can be entered and signed off.")
        blocked = (status != "submitted") or (failed and not (notes or "").strip())
        if st.button("Enter and sign off", type="primary", key=f"{field_key_prefix}_submit",
                     disabled=blocked):
            _save_and_sign_off(engine, user, player_id=player_id, competition_id=competition_id,
                               season_id=season_id, dimension=dimension,
                               band=float(band) if band else None, notes=notes or None,
                               criterion_scores={}, criterion_passes=passes,
                               screening_failed=failed, status=status)


def _reject_control(engine, user: CurrentUser, entry) -> None:
    """Problem 3: reject, gated the same way sign-off is. The reason is OPTIONAL -- a
    reviewer must be able to decline an assessment without being forced to type an
    explanation -- but the field stays prominent because a reason is still the more useful
    outcome. Nothing is deleted -- the assessment stays on the record, attributed, and just
    stops scoring and leaves this queue. `store.assessments.reject` accepts a blank reason
    too, so this is not the only thing standing between a reviewer and a reason-less reject."""
    with st.expander(f"Reject {entry.author_name}'s assessment"):
        st.caption("Stays on the record, attributed — it stops scoring and leaves this "
                   "queue. The scout sees the reason on the player's profile (or sees a "
                   "plain note that none was given) and can submit a fresh assessment.")
        reason = st.text_area("Reason for rejecting (optional)",
                              key=f"reject_reason_{entry.id}")
        if st.button("Confirm reject", key=f"reject_confirm_{entry.id}"):
            try:
                store_assess.reject(engine, entry.id, approver_id=user.id,
                                    reason=reason.strip() or None, now=datetime.datetime.now())
            except ValueError:
                # Someone else acted on it (signed it off, or rejected it) since the page
                # loaded -- not a bug, just a race on a shared queue. Stashed for `render` to
                # show on the next run -- see MINOR 6 below.
                st.session_state["signoff_error"] = (
                    "This assessment is no longer awaiting sign-off — most likely someone "
                    "else already acted on it. Refreshing the queue.")
            st.rerun()


def _dimension_block(engine, user: CurrentUser, player_id: int, competition_id: int,
                     season_id: int, dimension: str, frame: pd.DataFrame,
                     position: str | None, now: datetime.datetime) -> None:
    """One dimension's whole state inside a player's card: every assessment ever entered for
    it (table + per-criterion detail via `assessment_detail`, exactly as the profile shows
    it), followed by whatever action its current state calls for -- sign off, reject, choose
    among several, or nothing if nothing is pending."""
    dim_rows = frame[frame["dimension"] == dimension]
    st.markdown(f"**{dimension}**")
    if dim_rows.empty:
        st.caption("Not assessed.")
        return

    entries = list(dim_rows.itertuples())
    st.dataframe(assessment_detail.entries_table(dim_rows), hide_index=True, width="stretch",
                key=f"queue_table_{player_id}_{competition_id}_{season_id}_{dimension}")
    assessment_detail.render_flags(entries)
    assessment_detail.render_criterion_detail(engine, position, dimension, entries)

    submitted = dim_rows[dim_rows["status"] == "submitted"]
    if submitted.empty:
        return  # signed off, rejected, draft-only -- nothing awaiting a decision right now

    # NOT `len(submitted) > 1` -- a signed-off row beside several newer submitted
    # re-assessments is not a conflict (Decision 17); `dimension_status` is the one function
    # that knows that.
    is_conflict = assessment_detail.dimension_status(frame, dimension) == scout_scores.CONFLICT
    waiting = int((now - submitted["created_at"].min()).days)
    if is_conflict:
        badges.render(badges.for_status(scout_scores.CONFLICT))
        st.caption(f"Waiting {waiting} day{'s' if waiting != 1 else ''} for a decision — "
                   "measured from the older of the disagreeing assessments.")
    else:
        st.caption(f"Waiting {waiting} day{'s' if waiting != 1 else ''} for sign-off.")

    if not can(user.role, "sign_off"):
        return

    if len(submitted) > 1:
        cols = st.columns(len(submitted))
        for col, entry in zip(cols, submitted.itertuples()):
            with col:
                band_txt = "—" if pd.isna(entry.band) else f"{entry.band:.2f}"
                st.markdown(f"Band **{band_txt}** — {entry.author_name} ({entry.author_role})")
                if st.button("Sign off this one", key=f"conflict_signoff_{entry.id}"):
                    try:
                        store_assess.sign_off(engine, entry.id, approver_id=user.id, now=now)
                    except ValueError:
                        st.session_state["signoff_error"] = (
                            "This was just resolved by someone else. Refreshing.")
                    st.rerun()
                _reject_control(engine, user, entry)
        with st.expander("Enter my own"):
            _enter_own_form(engine, user, player_id, competition_id, season_id, dimension,
                            position, submitted)
    else:
        entry = next(submitted.itertuples())
        if entry.author_name == user.full_name:
            st.caption("You entered this assessment. Approving it is permitted and will be "
                       "recorded as **self-approved**.")
        signoff_col, reject_col = st.columns(2)
        with signoff_col:
            if st.button("Sign off", key=f"signoff_{entry.id}", type="primary"):
                # Two reviewers can work the queue at once, or one person can double-click
                # before Streamlit reruns -- sign_off then raises because the row is no
                # longer 'submitted'. Not a bug to crash the page over.
                try:
                    store_assess.sign_off(engine, entry.id, approver_id=user.id, now=now)
                except ValueError:
                    st.session_state["signoff_error"] = (
                        "This assessment is no longer awaiting sign-off — most likely "
                        "someone else just approved it. Refreshing the queue.")
                st.rerun()
        with reject_col:
            _reject_control(engine, user, entry)


def _player_card(engine, user: CurrentUser, player_names: dict[int, str],
                 context: pd.DataFrame, key: tuple[int, int, int],
                 now: datetime.datetime) -> None:
    """One player-season, both dimensions together -- the approver's whole picture of this
    player in one pass, rather than reassembled across separate psychological/medical
    cards."""
    player_id, competition_id, season_id = key
    name = player_names.get(player_id, f"Player {player_id}")
    comp_name = _competition_name_by_id().get(competition_id, f"League {competition_id}")
    position, _minutes = _player_context(context, player_id, competition_id, season_id)
    frame = store_assess.load_for_player(engine, player_id, competition_id, season_id)

    with st.container(border=True):
        st.markdown(f"**{name}** — {comp_name}, {season_name_for(season_id)}")
        for dimension in (scout_scores.PSYCHOLOGICAL, scout_scores.MEDICAL):
            _dimension_block(engine, user, player_id, competition_id, season_id, dimension,
                             frame, position, now)


def render(engine, user: CurrentUser, player_names: dict[int, str],
          context: pd.DataFrame | None = None) -> None:
    st.subheader("Sign-off queue")

    if not can(user.role, "sign_off"):
        st.info("Sign-off is restricted to the Head of Recruitment and administrators. "
                "You can still assess any player — sign-off is the only gated action.")
        return

    # MINOR 6: `st.rerun()` raises immediately, discarding everything this run already queued
    # for display -- an `st.error(...)` called right before it never reaches the screen, so a
    # losing race on the queue looked like the button silently did nothing. The handlers above
    # stash their message here and rerun; this reads and clears it on the NEXT run, so it is
    # shown exactly once.
    pending_error = st.session_state.pop("signoff_error", None)
    if pending_error:
        st.error(pending_error)

    st.caption("Signing off does not change any score and does not hide any player. It "
               "marks the assessment reviewed, so it can be exported as final rather than "
               "provisional. Rejecting stops an assessment scoring and removes it from this "
               "queue — it stays on the record, attributed, and the scout can see why on the "
               "player's profile.")

    if context is None:
        context = pd.DataFrame(columns=["player_id", "competition_id", "season_id",
                                        "position_group", "minutes"])

    conflicts = store_assess.conflicts(engine)
    pending = store_assess.pending_signoff(engine)

    if conflicts.empty and pending.empty:
        st.success("Nothing awaiting sign-off.")
        return

    now = datetime.datetime.now()

    conflict_keys: set[tuple[int, int, int]] = set()
    if not conflicts.empty:
        conflict_keys = {tuple(row) for row in
                         conflicts[_KEY_COLS].drop_duplicates().itertuples(index=False)}
    pending_keys: set[tuple[int, int, int]] = set()
    if not pending.empty:
        pending_keys = {tuple(row) for row in
                        pending[_KEY_COLS].drop_duplicates().itertuples(index=False)}

    if conflict_keys:
        # B2: conflicts first -- a player with at least one contested dimension is a real
        # work item (a choice to make), not a lower-priority version of the ordinary queue
        # below. Longest-waiting player first.
        waiting_by_key = conflicts.groupby(_KEY_COLS)["waiting_days"].max()
        n_dimensions = len(conflicts.groupby(_KEY_COLS + ["dimension"]))
        ordered_conflict_keys = sorted(conflict_keys,
                                       key=lambda k: waiting_by_key.loc[k], reverse=True)

        st.markdown(f"#### Conflicts — {len(ordered_conflict_keys)} player"
                    f"{'s' if len(ordered_conflict_keys) != 1 else ''}, {n_dimensions} "
                    f"dimension{'s' if n_dimensions != 1 else ''} contested")
        st.caption("Two or more assessments disagree on the same dimension and nobody has "
                   "signed one off. Choose one, reject one, enter your own, or leave it — "
                   "the player reads 'assessments conflict — not scored' until you do.")
        for key in ordered_conflict_keys:
            _player_card(engine, user, player_names, context, key, now)
        st.divider()

    # The ordinary section excludes any player already shown above -- a player's whole card,
    # both dimensions, already rendered once (Decision 17: a conflicted dimension is not
    # eligible for a separate one-click sign-off card of its own).
    ordinary_keys = pending_keys - conflict_keys
    if not ordinary_keys:
        if conflict_keys:
            st.caption("Nothing else awaiting sign-off.")
        return

    earliest_by_key = pending.groupby(_KEY_COLS)["created_at"].min()
    ordered_ordinary_keys = sorted(ordinary_keys, key=lambda k: earliest_by_key.loc[k])

    st.markdown(f"#### Awaiting sign-off — {len(ordered_ordinary_keys)} player"
                f"{'s' if len(ordered_ordinary_keys) != 1 else ''}")
    st.caption("Oldest first.")
    for key in ordered_ordinary_keys:
        _player_card(engine, user, player_names, context, key, now)
