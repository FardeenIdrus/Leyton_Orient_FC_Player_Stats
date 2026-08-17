"""The assessment form: the club's criteria for a player's position, scored by a person.

Decision 16: ANY authenticated user may enter EITHER band. The role is recorded and shown
beside the band rather than restricting who may enter it. Sign-off is the only gated action,
and it lives in tabs/signoff.py.

Decision 13: a failed screening criterion warns. Nothing here caps, clamps or overwrites the
band the assessor entered.

Layout (frontend-design skill, spec section 16): draft/submitted state is carried in WORDS,
not colour alone (a blue "draft" info box vs a green "submitted" success box, each naming the
state explicitly) -- the same convention `evidence.py` already established for the
availability caption, so the whole form reads as one language rather than two. The evidence
panel sits BESIDE the Medical inputs in a two-column split, in view while the assessor
decides, and the ceiling note sits directly under the band input it qualifies, never in a
footer. The screening warning leads with a bolded sentence stating in words that the band
stands unchanged, matching Decision 13.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.dashboard import evidence, transparency
from lofc.dashboard.session import CurrentUser
from lofc.model import assessment_rules as rules
from lofc.model import club_criteria as cc
from lofc.model import scout_scores
from lofc.store import assessments as store_assess

_BAND_HELP = " · ".join(f"{n} {label}" for n, label in rules.BAND_LABELS.items())


def _band_select(label: str, key: str) -> float | None:
    """A 1-5 band input that starts EMPTY. Defaulting to 3 would silently score every player
    a scout opened and abandoned."""
    options = [None] + list(rules.BAND_LABELS)
    return st.selectbox(
        label, options, key=key, format_func=lambda v: "—" if v is None
        else f"{v} · {rules.BAND_LABELS[v]}", help=_BAND_HELP)


def _psychological_form(engine, user: CurrentUser, player_id: int, competition_id: int,
                        season_id: int, position: str) -> None:
    st.markdown("##### Psychological")
    st.caption("The club's criteria for this position, each scored 1–5. The band is their "
               "equal-weighted mean. Every criterion must be scored before it submits.")

    scores: dict[str, int] = {}
    for text in cc.PSYCHOLOGICAL_CRITERIA[position]:
        key = rules.criterion_key(text)
        value = _band_select(text, key=f"psych_{player_id}_{key}")
        if value is not None:
            scores[key] = value

    band = rules.psychological_band(scores, position)
    status = rules.psychological_status(scores, position)
    notes = st.text_area("Notes (optional)", key=f"psych_notes_{player_id}")

    if band is None:
        st.info(f"Scored {len(scores)} of {len(cc.PSYCHOLOGICAL_CRITERIA[position])} "
                "criteria. Saving now keeps this as a **draft**, which does not score.")
    else:
        st.success(f"Band **{band:.2f}** — the mean of "
                   f"{len(cc.PSYCHOLOGICAL_CRITERIA[position])} criteria. Saving submits "
                   "it, and it scores immediately.")

    if st.button("Save psychological assessment", type="primary",
                 key=f"save_psych_{player_id}"):
        # A store failure (a dropped connection, a stale foreign key) must show as a
        # message, not crash the page -- see tabs/signoff.py's sign_off for the same
        # convention.
        try:
            store_assess.save(engine, player_id=player_id, competition_id=competition_id,
                              season_id=season_id, dimension=scout_scores.PSYCHOLOGICAL,
                              author_id=user.id, band=band, notes=notes or None,
                              criterion_scores=scores, criterion_passes={},
                              screening_failed=False, status=status)
        except Exception as exc:
            st.error(f"Could not save this assessment: {exc}")
        else:
            st.success(f"Saved as **{status}**.")


def _medical_form(engine, user: CurrentUser, player_id: int, competition_id: int,
                  season_id: int, position: str, minutes_played: int | None) -> None:
    st.markdown("##### Medical")
    st.caption("There is no formula here. You enter the band, having read the evidence "
               "beside it. The platform never converts injury data into this score.")

    left, right = st.columns([1, 1])

    with right:
        # The evidence sits BESIDE the input, in view while the assessor decides.
        evidence.render(engine, player_id, competition_id, season_id, minutes_played)

    with left:
        passes: dict[str, bool] = {}
        for criterion in cc.MEDICAL_CRITERIA[position]:
            key = rules.criterion_key(criterion.text)
            if criterion.kind == "screening":
                answer = st.radio(criterion.text, ["—", "Meets", "Does not meet"],
                                  horizontal=True, key=f"med_{player_id}_{key}")
                if answer != "—":
                    passes[key] = (answer == "Meets")
            elif criterion.kind == "protocol":
                st.checkbox(f"{criterion.text} *(club process — not scored)*",
                            key=f"med_proto_{player_id}_{key}", disabled=True)
            else:
                st.caption(f"{criterion.text} *(shown as evidence — see the panel)*")

        band = _band_select("Medical band", key=f"med_band_{player_id}")
        st.caption(rules.MEDICAL_CEILING_NOTE)

        failed = rules.screening_failed(passes, position)
        if failed:
            st.warning("**One or more screening criteria are not met.** This is a flag, "
                       "not a cap — the band you enter stands unchanged, and the "
                       "disagreement is shown to whoever signs off. Please say why in the "
                       "notes.")

        notes = st.text_area("Notes" + (" (required — a screening criterion failed)"
                                        if failed else " (optional)"),
                             key=f"med_notes_{player_id}")
        status = rules.medical_status(band, passes, position)

        blocked = failed and not (notes or "").strip()
        if blocked:
            st.error("A reason is required when a screening criterion is not met.")
        if st.button("Save medical assessment", type="primary",
                     key=f"save_med_{player_id}", disabled=blocked):
            try:
                store_assess.save(engine, player_id=player_id, competition_id=competition_id,
                                  season_id=season_id, dimension=scout_scores.MEDICAL,
                                  author_id=user.id, band=float(band) if band else None,
                                  notes=notes or None, criterion_scores={},
                                  criterion_passes=passes, screening_failed=failed,
                                  status=status)
            except Exception as exc:
                st.error(f"Could not save this assessment: {exc}")
            else:
                st.success(f"Saved as **{status}**.")


def render(engine, user: CurrentUser, player_id: int, player_name: str,
           competition_id: int, season_id: int, position: str,
           minutes_played: int | None) -> None:
    """The assessment page for one player-season."""
    st.subheader(f"Assess — {player_name}")
    st.caption(f"{position} · signed in as {user.full_name} ({user.role}). Your name and "
               "role are recorded against anything you save.")

    if position not in cc.POSITION_GROUPS:
        # Spec section 18: never scored against no criteria.
        st.error(f"No club criteria exist for the position group {position!r}, so this "
                 "player cannot be assessed. Check the player's position group.")
        return

    transparency.render_panel()
    psych_tab, med_tab = st.tabs(["Psychological", "Medical"])
    with psych_tab:
        _psychological_form(engine, user, player_id, competition_id, season_id, position)
    with med_tab:
        _medical_form(engine, user, player_id, competition_id, season_id, position,
                      minutes_played)


def _assess(tab, engine, user: CurrentUser, pool: pd.DataFrame) -> None:
    """Tab wiring: find a player from the current sidebar-filtered pool, then hand off to
    `render`. Kept thin and Streamlit-only, matching the rest of `dashboard/tabs/` -- the
    scoring rules and the disclosure wording live in `assessment_rules.py` and
    `transparency.py`, tested without Streamlit.
    """
    with tab:
        if pool.empty:
            st.info("No players match the current filters. Adjust the sidebar (season, "
                    "position, league) to find a player to assess.")
            return
        labels = [f"{r['player_name']} — {r['team_name']}" for _, r in pool.iterrows()]
        by_label = dict(zip(labels, pool.index))
        picked = st.selectbox("Player to assess", labels, index=None,
                              placeholder="Search for a player…", key="assess_search")
        if not picked:
            st.caption("⬆️ Search for a player to open the assessment form.")
            return
        row = pool.loc[by_label[picked]]
        minutes = row.get("minutes")
        render(engine, user, int(row["player_id"]), str(row["player_name"]),
              int(row["competition_id"]), int(row["season_id"]), str(row["position_group"]),
              int(minutes) if pd.notna(minutes) else None)
