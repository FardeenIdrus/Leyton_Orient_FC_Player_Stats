"""Reference page "What goes into each rating": per position, every metric in the rating,
whether it counts towards Performance or Physical, which archetypes use it, and a one-line
definition.

Built FROM the scoring code (_resolved_performance, PHYSICAL_METRICS, DIMENSION_WEIGHTS,
archetypes_for), so it can never disagree with the ratings. Recruiters asked repeatedly which
metrics make each rating and how archetypes are defined; the answers lived only in code.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.dashboard.glossary_data import PHYSICAL
from lofc.dashboard.labels import metric_label
from lofc.model import club_framework as cf
from lofc.model.scorecard import _resolved_performance

TICK = "✓"


def weights_line(position: str) -> str:
    """'Rating = Performance 57% · Physical 43%' -- the objective composite's real split."""
    w = cf.DIMENSION_WEIGHTS[position]
    perf, phys = w.get(cf.PERFORMANCE, 0.0), w.get(cf.PHYSICAL, 0.0)
    if not phys:
        return "Rating = Performance 100%"
    return (f"Rating = Performance {perf / (perf + phys):.0%} · "
            f"Physical {phys / (perf + phys):.0%}")


@st.cache_data(ttl=3600)
def _definitions() -> dict[str, str]:
    """metric key -> what it is built from, in the provider's own names: the Impect basis
    (e.g. 'Successful Passes · Opponent Box, per 90') or the SkillCorner definition. The
    full Impect definitions are on the Glossary page."""
    from lofc.dashboard.labels import LABELS, impect_basis
    from lofc.ingest.impect_definitions import load_definitions
    defs = load_definitions()
    out = {k: impect_basis(k, defs) for k in LABELS}
    out |= {k: text for k, (_, text) in PHYSICAL.items()}
    return out


def rating_ingredients(position: str, definitions: dict[str, str] | None = None) -> pd.DataFrame:
    """One row per metric in the position's rating, with its weight. Archetype columns (that
    archetype's weight; blank = left out) only for positions that have archetypes; an
    archetype changes Performance only, so every physical metric is in every archetype."""
    defs = _definitions() if definitions is None else definitions
    rows = [{"key": m, "Metric": metric_label(m), "Counts towards": "Performance"}
            for m in _resolved_performance(position)]
    rows += [{"key": m, "Metric": PHYSICAL[m][0], "Counts towards": "Physical"}
             for m in cf.PHYSICAL_METRICS[position]]
    table = pd.DataFrame(rows, columns=["key", "Metric", "Counts towards"])
    # Per-metric weights (formula meeting, 2026-11-02): Performance carries the club's
    # weights, per archetype; Physical is equal-weighted. An archetype column shows that
    # archetype's own weight, or nothing where it leaves the metric out.
    from lofc.model import performance_weights as pw
    for col, arch in [("Weight", cf.DEFAULT_ARCHETYPE)] + \
            [(a, a) for a in cf.archetypes_for(position)[1:]]:
        weights = pw.weights_for(position, arch) or {}
        table[col] = ["Equal" if c == "Physical" else
                      (f"{weights[k]:.2%}" if k in weights else "")
                      for k, c in zip(table["key"], table["Counts towards"])]
    table["How it's measured"] = [defs.get(k, "") for k in table["key"]]   # provider wording
    return table


_CSS = """<style>
.lofc-ref {width:100%; border-collapse:collapse; font-size:0.9rem; table-layout:auto;}
.lofc-ref th {text-align:left; font-weight:600; color:#555; padding:8px 10px;
              border-bottom:2px solid #E3E3E6; white-space:nowrap;}
.lofc-ref td {padding:8px 10px; border-bottom:1px solid #EFEFF2; vertical-align:top;
              white-space: normal; line-height:1.4;}
.lofc-ref tr:nth-child(even) td {background:#FAFAFB;}
.lofc-ref td.tick {text-align:center; color:#2E7D4F; font-weight:600;}
.lofc-ref td.metric {font-weight:600; white-space:nowrap;}
.lofc-ref td.group {color:#666; white-space:nowrap;}
</style>"""


def ingredients_html(table: pd.DataFrame) -> str:
    """The table as plain HTML whose cells WRAP -- st.dataframe cut long text off even on a
    full-width monitor. Every value is escaped."""
    import html as h
    cols = [c for c in table.columns if c != "key"]
    head = "".join(f"<th>{h.escape(c)}</th>" for c in cols)
    body = []
    for _, row in table.iterrows():
        cells = []
        for c in cols:
            cls = ("metric" if c == "Metric" else "group" if c == "Counts towards"
                   else "tick" if row[c] in (TICK, "") and c not in ("How it's measured",)
                   else "")
            cells.append(f'<td class="{cls}">{h.escape(str(row[c]))}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (_CSS + '<table class="lofc-ref"><tr>' + head + "</tr>" + "".join(body)
            + "</table>")


def ingredients_workbook(definitions: dict[str, str] | None = None) -> bytes:
    """The page as an Excel file for review (Head of Recruitment, 2026-10-26): a Weights tab,
    then one tab per position with exactly the page's columns plus an empty Comments column.
    Excel, not CSV: a CSV file cannot hold one tab per position. Opens in Google Sheets."""
    import datetime
    import io
    defs = _definitions() if definitions is None else definitions
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as xl:
        weights = pd.DataFrame(
            [{"Position": p, "Rating weights": weights_line(p),
              "Archetypes": ", ".join(cf.archetypes_for(p)[1:]) or "—"}
             for p in cf.PERFORMANCE_METRICS])
        weights.to_excel(xl, sheet_name="Weights", index=False)
        ws = xl.sheets["Weights"]
        ws.cell(row=len(weights) + 3, column=1,
                value=f"Generated {datetime.date.today():%d %b %Y} from the platform's scoring code.")
        for position in cf.PERFORMANCE_METRICS:
            table = rating_ingredients(position, defs).drop(columns="key")
            table["Comments"] = ""
            table.to_excel(xl, sheet_name=position, index=False)
        for sheet in xl.sheets.values():                     # readable column widths
            for col in sheet.columns:
                width = max(len(str(c.value or "")) for c in col)
                sheet.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 70)
            sheet.freeze_panes = "A2"
    return buffer.getvalue()


def render() -> None:
    st.markdown("### What goes into each rating")
    st.download_button(
        "Download as Excel", data=ingredients_workbook(),
        file_name="LOFC - what goes into each rating.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="One tab per position, with an empty Comments column for review. "
             "Opens in Excel or Google Sheets.")
    position = st.segmented_control("Position", list(cf.PERFORMANCE_METRICS),
                                    default="Centre Back", key="ref_position")
    if not position:
        return
    table = rating_ingredients(position)
    st.caption(weights_line(position) + " · each metric is a percentile against the same "
               "position in the same league")
    archetypes = cf.archetypes_for(position)[1:]
    st.markdown(ingredients_html(table), unsafe_allow_html=True)
    if archetypes:
        st.caption("Archetypes come from the club's positional workbook. A blank means the "
                   "archetype leaves that metric out.")
