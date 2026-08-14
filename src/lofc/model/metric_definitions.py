"""Resolve each of our metric names to Impect's EXACT official definition.

The requirement: every metric we display must carry Impect's own wording, not a
paraphrase. This module joins three things that already exist —
  registry (metric -> source)          : metric_registry
  metric -> underlying Impect column(s) : impect_map (numer/denom)
  Impect column -> official definition  : impect_definitions.load_definitions()
— and exposes describe(metric) for the dashboard.

For an Impect-sourced metric we return Impect's definition of each underlying KPI
(one for a direct rename like goals_p90 -> GOALS; the numerator + denominator KPIs
for a ratio like pass_completion_pct). For a non-Impect metric (SkillCorner or the
StatsBomb metrics not yet migrated) we fall back to the registry's own derivation
string, clearly labelled as ours, so nothing is ever shown without a definition.
"""

from __future__ import annotations

from dataclasses import dataclass

from lofc.ingest.impect_definitions import load_definitions
from lofc.ingest.impect_map import IMPECT_MAP
from lofc.model import metric_registry as reg


@dataclass(frozen=True)
class ColumnDefinition:
    column: str
    label: str
    definition: str
    meaning: str
    scoped_from: str = ""     # base KPI name when this is an inherited pitch/phase variant


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    source: str                       # registry source (impect / skillcorner / statsbomb_*)
    origin: str                       # "Impect glossary" or "LOFC derivation"
    impect_columns: list[ColumnDefinition]   # exact Impect wording, when Impect-sourced
    lofc_derivation: str              # how WE compute it (from the registry)


_MAP_BY_NAME = {m.name: m for m in IMPECT_MAP}


def _impect_columns(metric: str) -> list[str]:
    """The underlying Impect KPI columns for a metric (numerator then denominator)."""
    m = _MAP_BY_NAME.get(metric)
    if m is None or m.kind == "none":
        return []
    cols: list[str] = [c for c, _sign in m.numer]
    if getattr(m, "denom", None):
        cols += [c for c, _sign in m.denom if c not in cols]
    return cols


def describe(metric: str, defs: dict | None = None) -> MetricDefinition:
    """Full definition record for one metric, with Impect's exact wording when applicable."""
    defs = load_definitions() if defs is None else defs
    spec = reg.BY_NAME.get(metric)
    source = spec.source if spec else "unknown"
    derivation = spec.derivation if spec else ""

    cols: list[ColumnDefinition] = []
    if source == reg.IMPECT:
        for col in _impect_columns(metric):
            d = defs.get(col, {})
            cols.append(ColumnDefinition(
                column=col,
                label=d.get("label") or col,
                definition=d.get("definition") or "(definition not in glossary pull)",
                meaning=d.get("meaning") or "",
                scoped_from=d.get("parent_kpi") or "",
            ))
    origin = "Impect glossary" if cols else "LOFC derivation"
    return MetricDefinition(name=metric, source=source, origin=origin,
                            impect_columns=cols, lofc_derivation=derivation)


def main() -> None:
    """Print each registry metric with its resolved definition (audit view)."""
    defs = load_definitions()
    print(f"Loaded {len(defs)} Impect definitions.\n")
    for spec in reg.REGISTRY:
        md = describe(spec.name, defs)
        print(f"### {md.name}  [{md.source}] — {md.origin}")
        if md.impect_columns:
            for c in md.impect_columns:
                print(f"   {c.column} ({c.label}): {c.definition[:160]}")
        else:
            print(f"   {md.lofc_derivation[:160]}")
        print()


if __name__ == "__main__":
    main()
