"""Pull Impect's official KPI definitions (the glossary), so every Impect-sourced
metric in our system can display Impect's EXACT wording, not a paraphrase.

Source of truth: the Impect customer API's KPI endpoint
(https://api.impect.com/v5/customerapi/kpis), which returns ~1,458 KPIs, each with
its official label, definition and interpretive "meaning", plus an `inverted` flag
(lower-is-better). This is licensed Impect IP: the landed JSON lives under the
gitignored data/raw/impect/, and the flattened reference CSV is gitignored too —
we may DISPLAY it in our own licensed tool, but not republish the glossary.

Idempotent: the landed file is reused unless --force. The reference CSV is always
rebuilt from whatever is landed (cheap, deterministic).

Run with:  python -m lofc.ingest.impect_definitions [--force]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from lofc.config import settings
from lofc.ingest import landing
from lofc.ingest.impect import _token, impect_root

KPI_ENDPOINT = "https://api.impect.com/v5/customerapi/kpis"


def definitions_raw_path() -> Path:
    return impect_root() / "kpi_definitions.json"


def reference_csv_path() -> Path:
    return Path(settings.reference_data_dir) / "impect_definitions.csv"


def pull_definitions(token: str, force: bool = False) -> bool:
    """Land the raw KPI-definitions payload. Return True if pulled, False if skipped."""
    path = definitions_raw_path()
    if landing.exists(path) and not force:
        return False
    import requests
    resp = requests.get(KPI_ENDPOINT, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    kpis = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not kpis:
        raise RuntimeError("Impect KPI endpoint returned no definitions; not persisting.")
    landing.write_json(path, kpis, force=True)
    return True


def _flatten(kpis: list[dict]) -> pd.DataFrame:
    """One row per KPI: name + official label/definition/meaning.

    Pitch-position and phase VARIANTS (e.g. SUCCESSFUL_PASSES_TO_PITCH_POSITION_
    OPPONENT_BOX) carry no definition of their own — Impect defines the base KPI and
    the variant inherits it via `parentKpi` (a full nested record). So the effective
    definition is the variant's own text when present, else the parent's; `parent_kpi`
    records the base KPI name whenever the definition was inherited, so the display
    can say "Successful Passes, scoped to the opponent box".
    """
    rows = []
    for k in kpis:
        details = k.get("details") or {}
        parent = k.get("parentKpi") or {}
        own_def = details.get("definition")
        inherited = not own_def and bool(parent.get("definition"))
        rows.append({
            "column": k.get("name"),
            "label": details.get("label") or parent.get("label"),
            "official_definition": own_def or parent.get("definition"),
            "meaning": details.get("meaning") or parent.get("meaning"),
            "parent_kpi": parent.get("name") if inherited else None,
            "inverted": k.get("inverted"),
        })
    return pd.DataFrame(rows).dropna(subset=["column"]).drop_duplicates("column")


def build_reference_csv() -> int:
    """Rebuild the flattened reference CSV from the landed raw definitions."""
    raw = definitions_raw_path()
    if not landing.exists(raw):
        raise SystemExit(f"no landed KPI definitions at {raw}; run the pull first.")
    kpis = json.loads(raw.read_text())
    frame = _flatten(kpis)
    out = reference_csv_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out, index=False)
    return len(frame)


def load_definitions() -> dict[str, dict]:
    """column -> {label, definition, meaning, inverted}, from the reference CSV.

    Empty dict if the CSV is absent (definitions are optional to the pipeline: the
    dashboard degrades to showing no glossary text rather than crashing).
    """
    path = reference_csv_path()
    if not path.exists():
        return {}
    # Empty cells read back as float NaN; coerce to None so callers get clean strings.
    df = pd.read_csv(path).astype(object).where(lambda d: d.notna(), None)
    return {
        r["column"]: {
            "label": r["label"],
            "definition": r["official_definition"],
            "meaning": r["meaning"],
            "parent_kpi": r.get("parent_kpi"),
            "inverted": r["inverted"],
        }
        for _, r in df.iterrows()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-pull even if landed")
    args = parser.parse_args()
    token = _token()
    pulled = pull_definitions(token, force=args.force)
    n = build_reference_csv()
    print(f"Impect KPI definitions: {'pulled' if pulled else 'reused landed'}; "
          f"reference CSV rebuilt with {n} definitions at {reference_csv_path()}")


if __name__ == "__main__":
    main()
