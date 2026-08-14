"""Sidebar widgets whose slider and number-box stay in sync.

Pure Streamlit state handling: each control takes its bounds as arguments and returns a
value, so nothing here touches the database or the model.
"""

from __future__ import annotations

import streamlit as st

def synced_budget() -> float:
    """A transfer-budget control with a slider and a number box kept in sync. Returns euros."""
    st.session_state.setdefault("budget_slider", 5.0)
    st.session_state.setdefault("budget_number", 5.0)

    def from_slider():
        st.session_state.budget_number = st.session_state.budget_slider

    def from_number():
        st.session_state.budget_slider = st.session_state.budget_number

    st.sidebar.slider("Transfer budget (€m)", 0.0, 150.0, step=0.5,
                      key="budget_slider", on_change=from_slider)
    st.sidebar.number_input("…or type it (€m)", 0.0, 150.0, step=0.5,
                            key="budget_number", on_change=from_number)
    return st.session_state.budget_slider * 1_000_000


def synced_wage_budget(prime_ceiling: float) -> float:
    """Wage cap shown two synced ways: a slider (× club ceiling) and a £/week box.

    The £ box is the cap for a prime-age player in the selected position; the slider is the same
    value as a multiple of the club's modelled ceiling. Whichever you change, the other follows.
    Returns the exact multiplier the gate applies to each age band's ceiling, so a typed figure
    like £11,500 is used precisely even though the slider can only snap to its nearest 0.5 step.
    """
    st.session_state.setdefault("wage_pounds", int(round(prime_ceiling)))  # default = ceiling (1×)

    def from_slider():
        # Slider moved: set the £ box to the wage that multiple implies for a prime-age player.
        st.session_state.wage_pounds = int(round(st.session_state.wage_slider * prime_ceiling))

    # Keep the slider in step with the £ cap and the current position's ceiling (the £ box wins).
    implied_x = min(25.0, max(0.5, st.session_state.wage_pounds / prime_ceiling))
    st.session_state.wage_slider = round(implied_x / 0.5) * 0.5  # snap to the slider's 0.5 step

    st.sidebar.slider(
        "Wage budget (× club ceiling)", 0.5, 25.0, step=0.5,
        key="wage_slider", on_change=from_slider,
        help="1× = Leyton Orient's modelled weekly-wage ceiling for each position and age band. "
             "Slide up to model a bigger wage budget and see who that would make affordable. "
             "On this top-flight demo data the real (1×) ceiling is far below most players' wages, "
             "so this is the control that opens up the shortlist. Wages are modelled estimates.")
    st.sidebar.number_input(
        "…or type a max weekly wage (£)", min_value=0, max_value=200_000, step=500, key="wage_pounds",
        help="A specific weekly wage cap for a prime-age player in this position. The slider above is "
             "the same cap, expressed as a multiple of the club's modelled ceiling.")
    return st.session_state.wage_pounds / prime_ceiling


def synced_min_minutes(max_mins: int) -> int:
    """A minimum-minutes control with a slider and a number box kept in sync.

    The floor is 450 (the rankable threshold: per-90 numbers below that are noise)
    and the top is the real maximum minutes in the data, not a guess. Values are
    clamped so a stored setting survives a switch to a dataset with a lower maximum.
    """
    st.session_state.setdefault("minutes_slider", 450)
    st.session_state.setdefault("minutes_number", 450)
    st.session_state.minutes_slider = min(max(st.session_state.minutes_slider, 450), max_mins)
    st.session_state.minutes_number = min(max(st.session_state.minutes_number, 450), max_mins)

    def from_slider():
        st.session_state.minutes_number = st.session_state.minutes_slider

    def from_number():
        st.session_state.minutes_slider = st.session_state.minutes_number

    st.sidebar.slider("Minimum minutes", 450, max_mins, step=10,
                      key="minutes_slider", on_change=from_slider)
    st.sidebar.number_input("…or type the minutes", 450, max_mins, step=10,
                            key="minutes_number", on_change=from_number)
    st.sidebar.caption("450 = the minimum sample to be ranked; per-90 numbers below that are noise.")
    return int(st.session_state.minutes_slider)
