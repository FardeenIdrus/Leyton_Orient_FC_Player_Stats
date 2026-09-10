"""The player report page: pick a player, see the report, download it.

The download is the point. The chairman and the manager do not log in, so the deliverable is
a file that opens anywhere -- self-contained HTML, printable to a landscape PDF, with the
stylesheet and every chart embedded. `scripts/report_to_pdf.py` turns it into a PDF in one
command if a true PDF is wanted.

This module is a thin render layer: the report itself is assembled by `report/data.py` and
laid out by `report/render.py`, both of which are pure and tested.
"""

from __future__ import annotations

import re

import streamlit as st

from lofc.dashboard.search import filter_labels, search_options
from lofc.dashboard.session import CurrentUser
from lofc.report.data import build
from lofc.report.render import to_html


def _safe_filename(name: str, season_label: str) -> str:
    """A filename that survives being emailed: no spaces, no punctuation, no accents lost."""
    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{name}_{season_label}").strip("_")
    return f"{stem}_report.html"


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

    if query and not shortlist:
        st.info("No player matches that name in the selected season.")
        return
    if not query:
        st.caption("⬆️ Search for a player to build their report.")
        return

    picked = st.selectbox("Player", shortlist, index=0, key="report_pick")
    if not picked or picked not in by_label:
        return

    # `by_label` maps a label to an .iloc POSITION IN THE INDEX FRAME -- see
    # search.search_options. Using .loc, or indexing a different frame with it, silently
    # returns a different player, which is exactly what happened here before.
    row = search_index.iloc[by_label[picked]]
    try:
        data = build(engine, int(row["player_id"]), int(row["competition_id"]), season_id)
    except ValueError as exc:
        st.error(f"That player has no data for the selected season. {exc}")
        return
    except Exception as exc:                                   # noqa: BLE001
        st.error(f"The report could not be built: {exc}")
        return

    html = to_html(data)

    left, right = st.columns([3, 1])
    with left:
        st.markdown(f"**{data.player_name}** — {data.stamp}")
    with right:
        st.download_button("⬇ Download report", data=html.encode("utf-8"),
                           file_name=_safe_filename(data.player_name, data.season_label),
                           mime="text/html", use_container_width=True,
                           help="A self-contained page. Open it and print to PDF, or run "
                                "scripts/report_to_pdf.py to convert it.")

    # Rendered at the page's own scale so what is on screen is what prints.
    st.components.v1.html(html, height=820, scrolling=True)
