"""The Glossary tab: every metric with its exact definition, searchable.

The single home for metric definitions -- deliberately NOT on the player card, so a card
stays a decision surface rather than a reference manual."""

from __future__ import annotations

import streamlit as st

from lofc.dashboard.labels import metric_glossary


def _glossary(tab) -> None:
    """Searchable metric glossary: every metric with its exact definition and, for a
    substitute, the StatsBomb stat it stands in for. This is the single home for metric
    definitions (they no longer sit on the player card)."""
    with tab:
        st.markdown("### Metric glossary")
        st.markdown("Every metric the platform uses, with its **exact definition** — Impect's own "
                    "glossary wording for Impect metrics, our documented derivation for the rest. "
                    "Where a metric **substitutes** a StatsBomb stat the club used to track, it is named "
                    "for what it truly is and the StatsBomb lineage is shown, so nothing is dressed up "
                    "as a stat it is not.")
        sc1, sc2 = st.columns([6, 1], vertical_alignment="bottom")
        query = sc1.text_input("Search metrics", placeholder="e.g. ball wins, packing, save, cross",
                               key="glossary_search").strip().lower()
        sc2.button("✕ Clear", key="glossary_clear", width="stretch",
                   on_click=lambda: st.session_state.update(glossary_search=""),
                   disabled=not st.session_state.get("glossary_search"),
                   help="Clear the search box.")
        glossary = metric_glossary()

        def matches(g: dict) -> bool:
            if not query:
                return True
            hay = " ".join([g["label"], g["source"], g["text"], g["stands_in_for"], g["lineage"]]).lower()
            return query in hay

        # Group by provider so a reader can scan Impect vs StatsBomb vs SkillCorner.
        by_source: dict[str, list[dict]] = {}
        for g in glossary.values():
            if matches(g):
                by_source.setdefault(g["source"], []).append(g)
        if not any(by_source.values()):
            st.info("No metric matches that search.")
            return
        total = sum(len(v) for v in by_source.values())
        st.caption(f"Showing **{total}** metric{'s' if total != 1 else ''}"
                   + (f" matching “{query}”." if query else " across all providers."))
        for source in ["Impect", "StatsBomb", "SkillCorner", "—"]:
            items = by_source.get(source)
            if not items:
                continue
            st.markdown(f"#### {source}")
            for g in sorted(items, key=lambda x: x["label"]):
                with st.container(border=True):
                    st.markdown(f"**{g['label']}**  ·  _{g['source']}_")
                    if g["stands_in_for"]:
                        st.markdown(f"↳ *Substitute for* **{g['stands_in_for']}** — {g['lineage']}")
                    st.markdown(g["text"])
