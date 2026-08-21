"""The sign-off queue: conflicts first, then the ordinary submitted assessments awaiting
approval.

Sign-off is the ONLY gated assessment action (Decision 16). It changes no number and hides
no player (Decision 14) -- it marks an assessment reviewed, and controls what may leave the
building as final rather than provisional.

Decision 17 / task 10 Part B: a contested dimension (two or more unsigned assessments that
disagree) scores nothing until someone with sign-off rights decides. This is the screen where
that decision happens -- CONFLICTS ARE SHOWN FIRST, above the ordinary queue, because they are
a real work item (a choice to make), not a lower-priority version of the same review. Three
actions per conflict, all gated on `auth.can(role, "sign_off")`:

  1. Sign off one of the competing assessments -- that band scores; the others stay on the
     record, unsigned, attributed.
  2. Enter your own, pre-filled from either competing assessment or blank -- a NEW, separate
     assessment under the approver's own name, signed off in the same action.
  3. Leave it. The player keeps reading "assessments conflict -- not scored".

Layout (frontend-design skill, spec section 16): this is an internal tool with an established
visual language already (bold state-words, bordered containers, `badges.py`'s three-tone
system) -- extended here, not replaced, because a working tool used daily benefits more from
consistency than novelty. The one deliberate addition is the conflict card's signature device:
every competing assessment for a contested dimension renders as a matched column inside one
bordered card, a comparison a reader can take in at a glance rather than a scroll -- so "both
sides legible at once" is a property of the layout, not something the reader has to piece
together. Decision/evidence ordering carries over from the existing queue: each card leads
with WHO/WHAT/HOW LONG (the decision to make), then the competing bands with their provenance,
then the actions -- so a reviewer working under time pressure never has to hunt for the thing
that matters.
"""

from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

from lofc.dashboard import badges
from lofc.dashboard.auth import can
from lofc.dashboard.session import CurrentUser
from lofc.model import assessment_rules as rules
from lofc.model import club_criteria as cc
from lofc.model import scout_scores
from lofc.store import assessments as store_assess

_BAND_HELP = " · ".join(f"{n} {label}" for n, label in rules.BAND_LABELS.items())


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


def _conflict_card(engine, user: CurrentUser, player_names: dict[int, str],
                   context: pd.DataFrame, key: tuple, group: pd.DataFrame) -> None:
    """One contested (player, competition, season, dimension): the decision first (who,
    which dimension, how long it has waited), then every competing assessment SIDE BY SIDE
    so the approver is choosing, not rubber-stamping one side."""
    player_id, competition_id, season_id, dimension = key
    name = player_names.get(player_id, f"Player {player_id}")
    waiting = int(group["waiting_days"].iloc[0])
    position, _minutes = _player_context(context, player_id, competition_id, season_id)

    with st.container(border=True):
        st.markdown(f"**{name}** — {dimension}")
        badges.render(badges.for_status(scout_scores.CONFLICT))
        st.caption(f"Waiting {waiting} day{'s' if waiting != 1 else ''} for a decision — "
                   "measured from the older of the disagreeing assessments.")

        cols = st.columns(len(group))
        for col, entry in zip(cols, group.itertuples()):
            with col:
                band_txt = "—" if entry.band is None else f"{entry.band:.2f}"
                st.markdown(f"Band **{band_txt}**")
                st.caption(f"Entered by **{entry.author_name}** ({entry.author_role}), "
                           f"{entry.created_at:%d %b %Y}")
                if can(user.role, "sign_off"):
                    if st.button("Sign off this one", key=f"conflict_signoff_{entry.id}"):
                        try:
                            store_assess.sign_off(engine, entry.id, approver_id=user.id,
                                                  now=datetime.datetime.now())
                        except ValueError:
                            # Someone else resolved it, or signed off a competing one, since
                            # the page loaded -- not a bug, just a race on a shared queue.
                            # Stashed for `render` to show on the next run -- see MINOR 6.
                            st.session_state["signoff_error"] = (
                                "This conflict was just resolved by someone else. "
                                "Refreshing.")
                        st.rerun()

        if can(user.role, "sign_off"):
            with st.expander("Enter my own"):
                _enter_own_form(engine, user, player_id, competition_id, season_id, dimension,
                                position, group)


def render(engine, user: CurrentUser, player_names: dict[int, str],
          context: pd.DataFrame | None = None) -> None:
    st.subheader("Sign-off queue")

    if not can(user.role, "sign_off"):
        st.info("Sign-off is restricted to the Head of Recruitment and administrators. "
                "You can still assess any player — sign-off is the only gated action.")
        return

    # MINOR 6: `st.rerun()` raises immediately, discarding everything this run already queued
    # for display -- an `st.error(...)` called right before it never reaches the screen, so a
    # losing race on the queue looked like the button silently did nothing. The two handlers
    # below stash their message here and rerun; this reads and clears it on the NEXT run, so
    # it is shown exactly once.
    pending_error = st.session_state.pop("signoff_error", None)
    if pending_error:
        st.error(pending_error)

    st.caption("Signing off does not change any score and does not hide any player. It "
               "marks the assessment reviewed, so it can be exported as final rather than "
               "provisional.")

    if context is None:
        context = pd.DataFrame(columns=["player_id", "competition_id", "season_id",
                                        "position_group", "minutes"])

    conflicts = store_assess.conflicts(engine)
    pending = store_assess.pending_signoff(engine)

    if conflicts.empty and pending.empty:
        st.success("Nothing awaiting sign-off.")
        return

    if not conflicts.empty:
        # B2: conflicts first, longest-waiting first -- a real work item, not a lower
        # priority version of the ordinary queue below.
        groups = list(conflicts.groupby(
            ["player_id", "competition_id", "season_id", "dimension"], sort=False))
        groups.sort(key=lambda kv: kv[1]["waiting_days"].iloc[0], reverse=True)

        st.markdown(f"#### Conflicts — {len(groups)} dimension"
                    f"{'s' if len(groups) != 1 else ''} contested, {len(conflicts)} "
                    "assessments involved")
        st.caption("Two or more assessments disagree on the same dimension and nobody has "
                   "signed one off. Choose one, enter your own, or leave it — the player "
                   "reads 'assessments conflict — not scored' until you do.")
        conflict_ids = set(conflicts["id"])
        for key, group in groups:
            _conflict_card(engine, user, player_names, context, key, group)
        st.divider()
    else:
        conflict_ids = set()

    # The ordinary queue excludes anything already shown above as a conflict -- both draw
    # from 'submitted' assessments, and showing a conflicted row twice (once as a choice to
    # make, once as a plain approval) would contradict Decision 17: a conflicted assessment
    # is not eligible for an ordinary one-click sign-off.
    ordinary = pending[~pending["id"].isin(conflict_ids)]
    if ordinary.empty:
        if not conflicts.empty:
            st.caption("Nothing else awaiting sign-off.")
        return

    st.markdown("#### Awaiting sign-off")
    st.caption(f"{len(ordinary)} awaiting review, oldest first.")
    for row in ordinary.itertuples():
        name = player_names.get(row.player_id, f"Player {row.player_id}")
        with st.container(border=True):
            head, action = st.columns([4, 1])
            with head:
                band = "—" if row.band is None else f"{row.band:.2f}"
                st.markdown(f"**{name}** — {row.dimension} — Band **{band}**")
                st.caption(f"Entered by **{row.author_name}** ({row.author_role}) "
                           f"on {row.created_at:%d %b %Y}")
                if row.screening_failed:
                    st.warning("**A screening criterion was not met — the band above is "
                               "unchanged.** This flag records the assessor's disagreement "
                               "for you to weigh; it does not cap or alter the figure.")
                if pd.notna(row.notes) and (row.notes or "").strip():
                    st.caption(f"Notes: {row.notes}")
                if row.author_name == user.full_name:
                    st.caption("You entered this assessment. Approving it is permitted and "
                               "will be recorded as **self-approved**.")
            with action:
                if st.button("Sign off", key=f"signoff_{row.id}", type="primary"):
                    # Two reviewers can work the queue at once, or one person can double-
                    # click before Streamlit reruns -- sign_off then raises because the
                    # row is no longer 'submitted'. That is not a bug to crash the page
                    # over; it means someone else got there first, so say so and refresh.
                    try:
                        store_assess.sign_off(engine, row.id, approver_id=user.id,
                                              now=datetime.datetime.now())
                    except ValueError:
                        # Stashed for `render` to show on the next run -- see MINOR 6.
                        st.session_state["signoff_error"] = (
                            "This assessment is no longer awaiting sign-off — most "
                            "likely someone else just approved it. Refreshing the "
                            "queue.")
                    st.rerun()
