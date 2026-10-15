"""Impect's KPI definitions live in Postgres, not only in a CSV under data/.

Found 2026-10-09: data/ is excluded from the Docker image (.dockerignore) and the production
dashboard mounts no data, so load_definitions() returned {} there and every glossary entry
read "(definition not in glossary pull)". The dashboard reads only Postgres in production;
the definitions must be there too. The CSV stays as a fallback for local use.

The zone `context` (e.g. IBWL = "In-Behind Wide Left Zone" + Impect's definition) is kept so
the glossary can define the zones and reception types shown on the player card.
"""

import pandas as pd
from sqlalchemy import create_engine

from lofc.ingest import impect_definitions as idf
from lofc.store.models import Base, ImpectDefinition

KPIS = [
    {"name": "BALL_WIN_NUMBER", "details": {"label": "Ball Win Number",
     "definition": "Number of possession regains that take at least one opponent out.",
     "meaning": "Regains."}, "inverted": False},
    {"name": "OFFENSIVE_TOUCHES_IN_PACKING_ZONE_IBWL", "details": None,
     "parentKpi": {"name": "OFFENSIVE_TOUCHES", "label": "Offensive Touches",
                   "definition": "Any touch where a teammate was previously on the ball."},
     "context": {"name": "IBWL", "label": "In-Behind Wide Left Zone",
                 "definition": "Behind or next to the opponent's defensive line."},
     "inverted": False},
]


def _engine():
    e = create_engine("sqlite://")
    Base.metadata.create_all(e, tables=[ImpectDefinition.__table__])
    return e


def test_flatten_keeps_the_zone_context():
    row = idf._flatten(KPIS).set_index("column").loc["OFFENSIVE_TOUCHES_IN_PACKING_ZONE_IBWL"]
    assert row["context_name"] == "IBWL"
    assert row["context_label"] == "In-Behind Wide Left Zone"
    assert row["context_definition"].startswith("Behind or next to")


def test_definitions_round_trip_through_the_database():
    e = _engine()
    assert idf.write_definitions_to_db(e, idf._flatten(KPIS)) == 2
    defs = idf.load_definitions(engine=e)
    assert defs["BALL_WIN_NUMBER"]["definition"].startswith("Number of possession regains")
    assert defs["OFFENSIVE_TOUCHES_IN_PACKING_ZONE_IBWL"]["context_label"] == "In-Behind Wide Left Zone"


def test_rewriting_replaces_rather_than_duplicates():
    e = _engine()
    idf.write_definitions_to_db(e, idf._flatten(KPIS))
    idf.write_definitions_to_db(e, idf._flatten(KPIS))
    assert pd.read_sql("SELECT COUNT(*) AS n FROM impect_definitions", e)["n"][0] == 2


def test_empty_database_falls_back_to_the_csv(tmp_path, monkeypatch):
    e = _engine()
    csv = tmp_path / "impect_definitions.csv"
    idf._flatten(KPIS).to_csv(csv, index=False)
    monkeypatch.setattr(idf, "reference_csv_path", lambda: csv)
    assert "BALL_WIN_NUMBER" in idf.load_definitions(engine=e)
