"""Tests for the Impect definitions layer: the glossary flatten (incl. parent-KPI
inheritance) and the metric -> exact-definition resolver. No network, no database."""

import pandas as pd

from lofc.ingest.impect_definitions import _flatten
from lofc.model import metric_definitions as md
from lofc.model import metric_registry as reg


def test_flatten_uses_own_definition_when_present():
    kpis = [{"name": "GOALS", "inverted": False,
             "details": {"label": "Goals", "definition": "Goal", "meaning": "scored"},
             "parentKpi": None}]
    df = _flatten(kpis)
    row = df[df["column"] == "GOALS"].iloc[0]
    assert row["official_definition"] == "Goal"
    assert row["parent_kpi"] is None


def test_flatten_inherits_parent_definition_for_variants():
    # A pitch-position variant has no definition of its own; it inherits the base KPI's.
    kpis = [{"name": "SUCCESSFUL_PASSES_TO_PITCH_POSITION_OPPONENT_BOX", "inverted": False,
             "details": {"label": None, "definition": None, "meaning": None},
             "parentKpi": {"id": 90, "name": "SUCCESSFUL_PASSES", "label": "Successful Passes",
                           "definition": "A successful pass reaches a teammate.", "meaning": "reaches teammate"}}]
    df = _flatten(kpis)
    row = df.iloc[0]
    assert row["official_definition"] == "A successful pass reaches a teammate."
    assert row["parent_kpi"] == "SUCCESSFUL_PASSES"     # records that it was inherited
    assert row["label"] == "Successful Passes"


def test_describe_impect_metric_returns_glossary_definition():
    defs = {"GOALS": {"label": "Goals", "definition": "Goal", "meaning": "", "parent_kpi": None}}
    out = md.describe("goals_p90", defs)
    assert out.source == reg.IMPECT
    assert out.origin == "Impect glossary"
    assert out.impect_columns[0].column == "GOALS"
    assert out.impect_columns[0].definition == "Goal"


def test_describe_ratio_metric_includes_numerator_and_denominator_columns():
    # pass_completion_pct is a ratio of SUCCESSFUL / (SUCCESSFUL + UNSUCCESSFUL) passes:
    # both underlying KPIs must surface so the definition is complete.
    defs = {c: {"label": c, "definition": f"def {c}", "meaning": "", "parent_kpi": None}
            for c in ("SUCCESSFUL_PASSES", "UNSUCCESSFUL_PASSES")}
    out = md.describe("pass_completion_pct", defs)
    cols = {c.column for c in out.impect_columns}
    assert {"SUCCESSFUL_PASSES", "UNSUCCESSFUL_PASSES"} <= cols


def test_describe_non_impect_metric_falls_back_to_lofc_derivation():
    out = md.describe("tackles_p90", {})
    assert out.source == reg.SB_COMPUTED
    assert out.origin == "LOFC derivation"
    assert out.impect_columns == []
    assert "Tackle" in out.lofc_derivation


def test_describe_records_scoped_from_for_inherited_variants():
    defs = {"SUCCESSFUL_PASSES_TO_PITCH_POSITION_OPPONENT_BOX":
            {"label": "Successful Passes", "definition": "reaches a teammate",
             "meaning": "", "parent_kpi": "SUCCESSFUL_PASSES"}}
    out = md.describe("passes_into_box_p90", defs)
    assert out.impect_columns[0].scoped_from == "SUCCESSFUL_PASSES"
