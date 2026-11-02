"""The Glossary page: every metric the platform shows, with the provider's own definition.

Four tabs (Performance, Physical, Packing zones, Impect scores), one search box, compact rows.
Metrics that build the rating carry an "In rating" tag. Content: glossary_data.glossary_entries
(Impect's catalogue wording; SkillCorner's published definitions; "not published" where a
provider gives none). Deliberately not on the player card, which stays a decision surface.
"""

from __future__ import annotations

import html
import re

import streamlit as st

from lofc.dashboard.glossary_data import GROUPS, glossary_entries, rating_metrics

_CSS = """<style>
.g-row {padding: 10px 2px; border-bottom: 1px solid #EFEFF2;}
.g-head {display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 3px;}
.g-name {font-weight: 600; font-size: 1rem;}
.g-tag {font-size: .72rem; font-weight: 600; color: #2E7D4F; border: 1px solid #A9D3B9;
        border-radius: 10px; padding: 1px 8px; letter-spacing: .02em;}
.g-src {font-size: .78rem; color: #8A919B;}
.g-text {font-size: .92rem; color: #333A43; line-height: 1.5; max-width: 900px;}
</style>"""


def search(entries: list[dict], query: str) -> list[dict]:
    """Entries whose name or definition contains `query` (case-insensitive)."""
    q = (query or "").strip().lower()
    if not q:
        return list(entries)
    return [e for e in entries if q in e["label"].lower() or q in e["text"].lower()]


def _to_html(text: str) -> str:
    """Definition text (with **bold** and blank-line paragraphs) as safe HTML."""
    out = html.escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    return out.replace("\n\n", "<br><br>").replace("\n", "<br>")


def _rows(entries: list[dict], scored: set[str]) -> str:
    rows = []
    for e in sorted(entries, key=lambda x: x["label"].lower()):
        tag = '<span class="g-tag">In rating</span>' if e["key"] in scored else ""
        rows.append(f'<div class="g-row"><div class="g-head"><span class="g-name">'
                    f'{html.escape(e["label"])}</span>{tag}<span class="g-src">'
                    f'{html.escape(e["source"])}</span></div>'
                    f'<div class="g-text">{_to_html(e["text"])}</div></div>')
    return _CSS + "".join(rows)


@st.cache_data(ttl=3600)
def _entries() -> list[dict]:
    return glossary_entries()


def _glossary(tab) -> None:
    with tab:
        st.markdown("### Glossary")
        st.caption("Every metric on the platform, in the provider's own words. "
                   "\"In rating\" marks the 39 metrics that build the rating.")
        query = st.text_input("Search", placeholder="e.g. ball wins, sprint, in-behind",
                              key="glossary_search", label_visibility="collapsed")
        entries = search(_entries(), query)
        if not entries:
            st.info("No metric matches that search.")
            return
        scored = rating_metrics()
        groups = [g for g in GROUPS if any(e["group"] == g for e in entries)]
        tabs = st.tabs([f"{g} ({sum(e['group'] == g for e in entries)})" for g in groups])
        for t, g in zip(tabs, groups):
            with t:
                st.markdown(_rows([e for e in entries if e["group"] == g], scored),
                            unsafe_allow_html=True)
