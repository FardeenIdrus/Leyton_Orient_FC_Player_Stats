"""Brand chrome for the dashboard: Leyton Orient's colours, the page CSS and the header.

Pure presentation with no data or model dependencies, so every other dashboard module can
import it freely without risking an import cycle.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

RED = "#C8102E"
DARK = "#1A1A1A"
COMPARE_COLOURS = [RED, "#2B2B2B", "#1F77B4"]
# Distinct, readable colours for the playing-style groups on the cluster scatter.
CLUSTER_COLOURS = [RED, "#1F77B4", "#2CA02C", "#9467BD", "#FF7F0E", "#8C564B"]
NONE_OPTION = "— none —"
LOGO = Path("assets/logo.png")


def style() -> None:
    st.markdown(
        f"""
        <style>
          /* Hide only the hamburger, footer and Deploy button. Crucially, do NOT hide the
             toolbar/header: the control that re-opens a collapsed sidebar lives there. */
          #MainMenu, footer {{visibility: hidden;}}
          [data-testid="stAppDeployButton"] {{display: none;}}
          [data-testid="stSidebarCollapsedControl"] {{visibility: visible !important; opacity: 1 !important;}}
          .block-container {{padding-top: 4rem; max-width: 1180px;}}
          .lofc-title {{font-size: 2.1rem; font-weight: 800; color: {RED}; line-height: 1.1; margin-bottom: .15rem;}}
          .lofc-sub {{font-size: .9rem; color: #6b6b6b; letter-spacing: .1em; text-transform: uppercase;}}
          .brand-rule {{border: none; border-top: 3px solid {RED}; margin: .6rem 0 1.2rem 0;}}
          .stTabs [data-baseweb="tab"] {{font-weight: 600;}}
          .stTabs [aria-selected="true"] {{color: {RED};}}
          [data-testid="stMetricValue"] {{color: {RED}; font-weight: 700;}}
          [data-testid="stMetricLabel"] {{text-transform: uppercase; letter-spacing: .04em; font-size: .72rem; color: #6b6b6b;}}
          /* Keep dropdown menus crisp and fully opaque (some browsers render them blurred). */
          [data-baseweb="popover"], [data-baseweb="menu"], [role="listbox"] {{
            backdrop-filter: none !important; -webkit-backdrop-filter: none !important; background-color: #ffffff !important;
          }}
          html, body {{ -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def header() -> None:
    left, right = st.columns([1, 8], vertical_alignment="center")
    with left:
        if LOGO.exists():
            st.image(str(LOGO), width=96)
    with right:
        st.markdown('<div class="lofc-title">Leyton Orient FC</div>'
                    '<div class="lofc-sub">Recruitment Intelligence</div>', unsafe_allow_html=True)
    st.markdown('<hr class="brand-rule">', unsafe_allow_html=True)
