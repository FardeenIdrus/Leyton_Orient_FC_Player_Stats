"""Every metric the platform shows has a glossary entry, in four short groups.

Found 2026-10-11: the glossary held 45 Impect entries and NONE for the physical metrics --
including the 8 that build the Physical rating -- the packing zones, the reception types or
the Impect scores, all of which are on screen. This test is the guard: add something to the
card, the table or the sliders without a definition, and it fails.

Wording rules: the provider's own definition where one exists (Impect's catalogue, SkillCorner's
published articles); facts we verified ourselves are stated as such (HSR 20-25 km/h, excluding
sprinting: high-intensity = HSR + sprint for 100% of 6,378 player-seasons); where a provider
publishes no definition, the entry says so rather than inventing one.
"""

import pytest

from lofc.dashboard import detail_section as ds
from lofc.dashboard import glossary_data as gd
from lofc.dashboard.metric_filters import PHYSICAL_SLIDERS
from lofc.ingest.impect_detail import AVAILABILITY, FAMILY_LABELS, MAP_FAMILIES, ZONE_LABELS
from lofc.model import club_framework as cf
from lofc.model.scorecard import _resolved_performance

DEFS = {  # a minimal stand-in for Impect's catalogue
    "OFFENSIVE_TOUCHES_IN_PACKING_ZONE_IB": {
        "label": "Offensive Touches", "definition": "Any touch where a teammate had the ball.",
        "context_name": "IB", "context_label": "In-Behind Central Zone",
        "context_definition": "The area behind the opponent's defence."},
}


@pytest.fixture
def entries():
    return gd.glossary_entries(DEFS)


def _keys(entries):
    return {e["key"] for e in entries}


def test_groups_are_the_four_short_sections(entries):
    assert {e["group"] for e in entries} == set(gd.GROUPS)
    assert gd.GROUPS == ["Performance", "Physical", "Packing zones", "Playing styles",
                         "Impect scores"]


def test_every_style_signal_has_an_entry_built_from_impects_words():
    """The Playing styles tab (2026-10-30): one entry per signal any style uses, giving the
    Impect metrics it is built from and Impect's definition of each."""
    from lofc.model import styles as st
    defs = {"PXT_DRIBBLE": {"label": "Dribbles", "definition": "The change in goal threat."},
            "SUCCESSFUL_PASSES_BY_ACTION_LOW_CROSS": {
                "label": "Successful Passes", "definition": "Any pass that reaches a teammate.",
                "context_label": "Low Cross", "context_definition": "A low cross from wide."}}
    by_key = {e["key"]: e for e in gd.glossary_entries(defs)}
    used = {s for g in st.STYLES.values() for styles in g.values() for sigs in styles.values()
            for s in sigs}
    assert {f"style.{s}" for s in used} <= set(by_key)
    carry = by_key["style.carry_value_p90"]
    assert carry["group"] == "Playing styles" and carry["source"] == "Impect"
    assert "**Built from (Impect):**" in carry["text"]
    assert "**Dribbles**: The change in goal threat." in carry["text"]
    cross = by_key["style.cross_attempts_per_touch"]["text"]
    assert "**Low Cross**: A low cross from wide." in cross
    assert "measures success" in by_key["style.xa_p90"]["text"]
    assert "measures success" not in cross


def test_every_scored_metric_has_an_entry(entries):
    scored = ({m for p in cf.PERFORMANCE_METRICS for m in _resolved_performance(p)}
              | {m for v in cf.PHYSICAL_METRICS.values() for m in v})
    assert scored <= _keys(entries)


def test_every_physical_metric_shown_has_an_entry(entries):
    shown = ({m for v in PHYSICAL_SLIDERS.values() for m in v}
             | {m for m, _ in ds.PHASE_METRICS} | {m for m, _, _ in ds.SPEED_METRICS})
    assert shown <= _keys(entries)


def test_every_packing_zone_item_shown_has_an_entry(entries):
    keys = _keys(entries)
    assert {f"family.{f}" for f in MAP_FAMILIES} <= keys
    assert {f"zone.{z}" for z in ZONE_LABELS} <= keys
    assert {f"avail.{a}" for a in AVAILABILITY} <= keys


def test_both_score_tiles_have_an_entry(entries):
    assert {f"score.{k}" for k in ds.SCORE_TILES} <= _keys(entries)


def test_zone_entries_use_impects_wording_when_available(entries):
    ib = next(e for e in entries if e["key"] == "zone.IB")
    assert ib["label"] == "In-Behind Central Zone"
    assert ib["text"] == "The area behind the opponent's defence."


def test_missing_provider_definitions_say_so_rather_than_invent(entries):
    """No catalogue entry for a zone -> an explicit 'not published', never a guess."""
    cb = next(e for e in entries if e["key"] == "zone.CB")
    assert "not" in cb["text"].lower() and "published" in cb["text"].lower()
    off = next(e for e in entries if e["key"] == "score.offensive")
    assert "does not publish" in off["text"]


def test_hsr_is_stated_as_the_verified_band(entries):
    hsr = next(e for e in entries if e["key"] == "hsr_distance_p90")
    assert "20–25 km/h" in hsr["text"]


def test_entries_are_short(entries):
    """Minimal by design: no essays. Impect's own multi-part definitions (e.g. Assists) are
    the only long ones and come from the provider."""
    for e in entries:
        if e["group"] != "Performance":
            assert len(e["text"]) <= 240, e["key"]


def test_labels_are_unique_within_a_group(entries):
    for g in gd.GROUPS:
        labels = [e["label"] for e in entries if e["group"] == g]
        assert len(labels) == len(set(labels)), g


def test_short_first_sentences_keep_the_next_one_when_it_fits():
    """'Sum of bypassed opponents.' alone does not say what bypassed means."""
    text = ("Sum of bypassed opponents. An opponent is bypassed if, after a pass or dribbling, "
            "they are further from the goal than the ball. Third sentence that is long enough "
            "to push the total well past the two hundred and forty character limit set here.")
    out = gd.first_sentence(text)
    assert out.startswith("Sum of bypassed opponents. An opponent is bypassed")
    assert "Third sentence" not in out


# --- 2026-10-12: Impect's own words only (owner: recruiters must be able to verify them) ---
# Each performance entry = the Impect metric(s) it is built from, named with Impect's own
# catalogue labels + context (e.g. "Successful Passes · Opponent Box"), then Impect's
# definition verbatim. The only thing we add is the arithmetic (per 90, ratio, minus).

from lofc.dashboard.labels import impect_basis, metric_glossary


def test_basis_uses_impects_labels_and_context():
    assert impect_basis("passes_into_box_p90") == "Successful Passes · Opponent Box, per 90"
    assert impect_basis("deep_progressions_p90") == "Bypassed Opponents · Final Third, per 90"


def test_ratios_and_exclusions_are_shown_as_arithmetic():
    assert impect_basis("aerial_win_pct") == \
        "Won Aerial Duels ÷ (Won Aerial Duels + Lost Aerial Duels)"
    assert impect_basis("np_xg_p90") == "Shot-based xG − Shot-based xG · Penalty, per 90"


def test_glossary_entries_lead_with_the_impect_basis_and_no_jargon():
    g = metric_glossary()
    for key, entry in g.items():
        assert entry["text"].startswith(f"**Built from (Impect):** {impect_basis(key)}"), key
        assert "scoped to this metric" not in entry["text"], key
