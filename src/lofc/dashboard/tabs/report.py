"""The player report page: pick a player, see the report, download it.

The download is the point. The chairman and the manager do not log in, so the deliverable is
a file that opens anywhere -- self-contained HTML, printable to a landscape PDF, with the
stylesheet and every chart embedded. `scripts/report_to_pdf.py` turns it into a PDF in one
command if a true PDF is wanted.

This module is a thin render layer: the report itself is assembled by `report/data.py` and
laid out by `report/render.py`, both of which are pure and tested.

The "Write your report" form shapes what is RENDERED and downloaded. Nothing is stored: the
page writes nothing to the database, and the author's Psychological / Medical figures never
reach scout_assessments or any rating.
"""

from __future__ import annotations

import streamlit as st

from lofc.core import report_page as rp
from lofc.dashboard.search import filter_labels, search_options
from lofc.dashboard.session import CurrentUser
from lofc.model import club_criteria as cc
from lofc.report.data import authored_from_inputs, build

# Lifted to lofc.core.report_page (TASKS 2.36) so the web Report page shares them.
_safe_filename = rp.safe_filename
_SCREEN_CHOICES = rp.SCREEN_CHOICES


def _preselected(search_index, by_label):
    """See `report_page.preselected_label` (reads ?player_id=&competition_id=[&season_id=])."""
    return rp.preselected_label(search_index, by_label, st.query_params)


@st.cache_data(ttl=60, show_spinner="Building report…")
def _cached_build(_engine, player_id: int, competition_id: int, season_id: int):
    """The base report, read from the database once per player-season per minute (short:
    it carries scout assessments, which users save at any time).
    The engine is excluded from the cache key (leading underscore); ReportData is a frozen
    dataclass of plain values and pickles fine."""
    return build(_engine, player_id, competition_id, season_id)


def _form(data, user, key: str):
    """The optional author form. Returns the Authored override, or None if all blank."""
    st.markdown("##### Write your report")
    st.caption("Your Psychological and Medical are your view on this report only. "
               "They never change any rating.")
    summary = st.text_area("Summary", key=f"{key}_sum", height=100)
    why_sign = st.text_area("Why sign?", key=f"{key}_why", height=80)
    considerations = st.text_area("Considerations", key=f"{key}_con", height=80)

    scores: dict[str, int | None] = {}
    left, right = st.columns(2)
    with left:
        st.markdown("**Psychological**")
        for n, text in enumerate(cc.PSYCHOLOGICAL_CRITERIA.get(data.position, [])):
            scores[text] = st.selectbox(text, [None, 1, 2, 3, 4, 5], key=f"{key}_ps{n}",
                                        format_func=lambda v: "—" if v is None else str(v))
        st.caption(rp.psych_band_caption(scores))
    with right:
        st.markdown("**Medical**")
        screening: dict[str, str] = {}
        for n, crit in enumerate(cc.MEDICAL_CRITERIA.get(data.position, [])):
            if crit.kind == "screening":
                answer = st.radio(crit.text, ["—", *_SCREEN_CHOICES], horizontal=True,
                                  key=f"{key}_ms{n}")
                if answer in _SCREEN_CHOICES:
                    screening[crit.text] = answer
            else:
                st.caption(crit.text)
        medical_band = st.selectbox("Medical band", [None, 1, 2, 3, 4, 5], key=f"{key}_mb",
                                    format_func=lambda v: "—" if v is None else str(v))
    return authored_from_inputs(author_name=user.full_name, author_role=user.role,
                                summary=summary, why_sign=why_sign,
                                considerations=considerations, psych_scores=scores,
                                medical_band=medical_band, screening=screening)


def render(engine, user: CurrentUser, search_index, season_id: int) -> None:
    """`search_index` is the SEASON-scoped index built in app.py from the unfiltered
    candidates -- not the sidebar-filtered pool. The report must reach any player in the
    season regardless of which position or league the sidebar happens to be showing, and
    passing the filtered frame made most players unfindable."""
    st.subheader("Player report")
    st.caption("A one-page report for the Head of Recruitment, the manager and the chairman. "
               "Download it and send it — nobody needs an account to read it. Where a scout "
               "has written an assessment, their summary appears on the page; where none "
               "exists, the report says so and presents the data alone.")

    if search_index is None or search_index.empty:
        st.info("No player data for the selected season.")
        return

    labels, by_label = search_options(search_index)
    query = st.text_input("Find a player", key="report_search",
                          placeholder="Any player, any position, any league…")
    shortlist = filter_labels(labels, query) if query else []
    if not query:
        pre = _preselected(search_index, by_label)
        if pre:
            shortlist = [pre]

    if query and not shortlist:
        st.info("No player matches that name in the selected season.")
        return
    if not shortlist:
        st.caption("⬆️ Search for a player to build their report.")
        return

    picked = st.selectbox("Player", shortlist, index=0, key="report_pick")
    if not picked or picked not in by_label:
        return

    # `by_label` maps a label to an .iloc POSITION IN THE INDEX FRAME -- see
    # search.search_options. Using .loc, or indexing a different frame with it, silently
    # returns a different player, which is exactly what happened here before.
    row = search_index.iloc[by_label[picked]]
    pid, comp = int(row["player_id"]), int(row["competition_id"])
    try:
        base = _cached_build(engine, pid, comp, season_id)
    except ValueError as exc:
        st.error(f"That player has no data for the selected season. {exc}")
        return
    except Exception as exc:                                   # noqa: BLE001
        st.error(f"The report could not be built: {exc}")
        return

    authored = _form(base, user, key=f"rep_{pid}_{comp}_{season_id}")
    # Variants are derived from the one base report (no further database read). All-blank
    # inputs leave the report exactly as today.
    data, html, data_only_html = rp.variants(base, authored)

    name = _safe_filename(data.player_name, data.season_label)
    st.markdown(f"**{data.player_name}** — {data.stamp}")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇ Download report", data=html.encode("utf-8"),
                           file_name=name, mime="text/html", use_container_width=True)
    with c2:
        st.download_button("⬇ Download data-only report",
                           data=data_only_html.encode("utf-8"),
                           file_name=rp.data_only_filename(name),
                           mime="text/html", use_container_width=True)

    # Rendered at the page's own scale so what is on screen is what prints.
    st.components.v1.html(html, height=820, scrolling=True)
