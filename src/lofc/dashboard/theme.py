"""Brand chrome for the dashboard: Leyton Orient's colours, the page CSS and the header.

Pure presentation with no data or model dependencies, so every other dashboard module can
import it freely without risking an import cycle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

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

          /* The dataset info bar (players analysed / leagues / season): orienting context on
             every page, deliberately quiet so it never competes with the page beneath it. */
          .lofc-infobar {{
            text-align: center; font-size: .82rem; color: #6b6b6b;
            background: #FAFAFA; border: 1px solid #ECECEC; border-radius: 6px;
            padding: .4rem .75rem; margin: 0 0 1.1rem 0;
          }}
          .lofc-infobar-item b {{color: {DARK};}}
          .lofc-infobar-sep {{color: {RED}; margin: 0 .7rem; font-weight: 700;}}

          /* Top-right signed-in identity, in the header's right-hand column. */
          .st-key-topbar_identity {{display: flex; flex-direction: column; align-items: flex-end;}}
          .lofc-identity-name {{font-size: .85rem; font-weight: 700; color: {DARK}; text-align: right;}}
          .lofc-identity-role {{
            font-size: .68rem; color: #8a8a8a; text-transform: uppercase; letter-spacing: .05em;
            text-align: right; margin-bottom: .3rem;
          }}
          .st-key-topbar_identity [data-testid="stButton"] button {{
            font-size: .75rem; padding: .15rem .8rem; color: #6b6b6b; border-color: #ddd;
          }}

          /* Sidebar navigation: separate it visually from the filters that sit right beneath
             it, group the nine pages so they read as clusters rather than one flat list, and
             make the current page unmistakable (never colour alone -- weight + a left rule). */
          [data-testid="stSidebarNav"] {{
            border-bottom: 1px solid #E6E6E6; padding-bottom: .6rem; margin-bottom: .6rem;
          }}
          [data-testid="stSidebarNav"] [data-testid="stSidebarNavLink"] {{
            border-radius: 4px; font-weight: 500;
          }}
          [data-testid="stSidebarNav"] [data-testid="stSidebarNavLink"][aria-current="page"] {{
            background: #FCE8EB; font-weight: 700; color: {RED};
            border-left: 3px solid {RED};
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def header(identity_slot: Callable[[], None] | None = None) -> None:
    """The masthead: logo + title on the left, and -- once someone is signed in -- who they
    are on the right (`identity_slot`, a closure over `session.topbar_identity`; theme.py
    stays session-agnostic, so it takes a renderer rather than importing session). Called
    with `identity_slot=None` before login, so the signed-out screen shows the brand and the
    sign-in form only, never a name that isn't there yet."""
    left, title, identity = st.columns([1, 6, 2], vertical_alignment="center")
    with left:
        if LOGO.exists():
            st.image(str(LOGO), width=96)
    with title:
        st.markdown('<div class="lofc-title">Leyton Orient FC</div>'
                    '<div class="lofc-sub">Recruitment Intelligence</div>', unsafe_allow_html=True)
    with identity:
        if identity_slot is not None:
            identity_slot()
    st.markdown('<hr class="brand-rule">', unsafe_allow_html=True)
