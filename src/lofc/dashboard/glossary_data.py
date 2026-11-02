"""The glossary's content: one short entry for every metric the platform shows.

Five groups -- Performance, Physical, Packing zones, Playing styles, Impect scores. Wording rules:
  * the provider's own definition where one exists (Impect's catalogue, read from Postgres;
    SkillCorner's published articles), first sentence only outside Performance;
  * facts we verified ourselves are stated plainly (e.g. HSR is 20-25 km/h and excludes
    sprinting: high-intensity = HSR + sprint for 100% of 6,378 player-seasons, 2026-10-11);
  * where a provider publishes no definition the entry says so -- nothing is invented.

SkillCorner sources: skillcorner.com articles on Peak Velocity (PSV-99), Change of Direction
metrics and Explosive Accelerations. Not published there: the medium/high acceleration and
deceleration thresholds, and the running-speed lower bound.
"""

from __future__ import annotations

import re

from lofc.dashboard.labels import clean_definition, metric_glossary
from lofc.ingest.impect_detail import (AVAILABILITY, FAMILY_LABELS, MAP_FAMILIES, SCORES,
                                       ZONE_FAMILIES, ZONE_LABELS, ZONES)

GROUPS = ["Performance", "Physical", "Packing zones", "Playing styles", "Impect scores"]

NOT_PUBLISHED = "Not published by {provider} in the data or documentation we hold."

# metric -> (label, definition). Per 90 = per 90 minutes played (converted from SkillCorner's
# per-appearance figures, 2026-10-04).
PHYSICAL: dict[str, tuple[str, str]] = {
    # Verified 2026-10-16 against per-match data: season psv99 = mean of every match's PSV-99;
    # psv99_top5 = mean of his 5 fastest matches. "Top speed" is the latter (Head of Recruitment).
    "top5_psv99_kmh": ("Top speed", "Average of his 5 fastest matches' top speeds (SkillCorner PSV-99 Top 5). A match's top speed is the 99th percentile of his movement above 15 km/h. km/h."),
    "psv99_kmh": ("Average match top speed", "Average of his top speed across all his matches (SkillCorner PSV-99). km/h."),
    "distance_p90": ("Distance", "Total distance covered, per 90 minutes."),
    "meters_per_minute": ("Metres per minute", "Distance covered per minute on the pitch. Equals distance per 90 ÷ 90."),
    "running_distance_p90": ("Running distance", "Distance at running speed, below 20 km/h, per 90. SkillCorner does not publish the lower bound."),
    "hsr_distance_p90": ("High-speed running distance", "Distance at 20–25 km/h, per 90. Excludes sprinting."),
    "hsr_count_p90": ("High-speed runs", "Number of runs at 20–25 km/h, per 90."),
    # hi = HSR + sprint, checked 2026-11-02 on 5,809 player-seasons with all four figures:
    # distance never differs by more than 0.09 m, count by more than 0.09 (rounding).
    "hi_distance_p90": ("High-intensity distance", "Distance above 20 km/h (high-speed running plus sprinting), per 90."),
    "sprint_distance_p90": ("Sprint distance", "Distance above 25 km/h, per 90."),
    "sprint_count_p90": ("Sprints", "Number of runs above 25 km/h, per 90."),
    "medium_accel_count_p90": ("Medium accelerations", "Accelerations SkillCorner classes as medium, per 90. Threshold not published."),
    "high_accel_count_p90": ("High accelerations", "Accelerations SkillCorner classes as high, per 90. Threshold not published."),
    "medium_decel_count_p90": ("Medium decelerations", "Decelerations SkillCorner classes as medium, per 90. Threshold not published."),
    "high_decel_count_p90": ("High decelerations", "Decelerations SkillCorner classes as high, per 90. Threshold not published."),
    "explosive_accel_to_hsr_p90": ("Explosive accelerations to HSR", "High accelerations (3 m/s² for over 0.7 s) from below 9 km/h that reach 20 km/h, per 90."),
    "explosive_accel_to_sprint_p90": ("Explosive accelerations to sprint", "High accelerations (3 m/s² for over 0.7 s) from below 9 km/h that reach 25 km/h, per 90."),
    "hi_count_p90": ("High-intensity runs", "Number of runs above 20 km/h (high-speed runs plus sprints), per 90."),
    "cod_count_p90": ("Changes of direction", "Intense changes of direction, whatever the movement, per 90."),
    "time_to_hsr": ("Time to HSR", "Seconds to reach 20 km/h, average of his 3 quickest. Lower is better."),
    "time_to_sprint": ("Time to sprint", "Seconds to reach 25 km/h, average of his 3 quickest. Lower is better."),
    "time_to_hsr_post_cod": ("Time to HSR after a change of direction", "Seconds to reach 20 km/h from 9 km/h straight after a change of direction, average of his 3 quickest. Lower is better."),
    "time_to_sprint_post_cod": ("Time to sprint after a change of direction", "Seconds to reach 25 km/h from 9 km/h straight after a change of direction, average of his 3 quickest. Lower is better."),
    "agility_505_90": ("505 agility, 90°", "Seconds to cover the last 5 m before and first 5 m after a ~90° turn. Lower is better."),
    "agility_505_180": ("505 agility, 180°", "Seconds to cover the last 5 m before and first 5 m after a ~180° turn. Lower is better."),
    "possession_split": ("In / out of possession", "Physical output split by whether his team or the opponent had the ball. Per 90 minutes played."),
}

_DIRECTION = {"_from": " From zone: where the action started.",
              "_to": " To zone: where it ended."}


def first_sentence(text: str | None, limit: int = 240) -> str:
    """The provider's own wording, cleaned of HTML: as many whole sentences as fit in
    `limit` characters (at least one, cut at a word if even that is too long)."""
    text = clean_definition(text or "").strip()
    sentences = re.findall(r".+?(?:[.!?](?=\s|$)|$)", text, flags=re.S)
    out = ""
    for s in (x.strip() for x in sentences if x.strip()):
        candidate = f"{out} {s}".strip()
        if out and len(candidate) > limit:
            break
        out = candidate
    return out if len(out) <= limit else out[: limit - 1].rsplit(" ", 1)[0] + "…"


def _impect(defs: dict, column: str) -> dict | None:
    d = defs.get(column)
    return d if d and d.get("definition") else None


def glossary_entries(defs: dict | None = None) -> list[dict]:
    """[{key, group, label, source, text}] for every metric the platform shows."""
    if defs is None:
        from lofc.ingest.impect_definitions import load_definitions
        defs = load_definitions()
    out: list[dict] = []

    for key, g in metric_glossary().items():
        out.append({"key": key, "group": "Performance", "label": g["label"],
                    "source": "Impect", "text": g["text"]})

    for key, (label, text) in PHYSICAL.items():
        out.append({"key": key, "group": "Physical", "label": label,
                    "source": "SkillCorner", "text": text})

    # Packing zones: the metrics on the map, the zones, the reception types.
    for fam in MAP_FAMILIES:
        if fam == "total_touches":
            text = "Offensive plus defensive touches."
        else:
            template = ZONE_FAMILIES[fam][0]
            found = next((d for z in ZONES if (d := _impect(defs, template.format(z)))), None)
            text = first_sentence(found["definition"]) if found else \
                NOT_PUBLISHED.format(provider="Impect")
            text += next((t for suffix, t in _DIRECTION.items() if fam.endswith(suffix)), "")
        out.append({"key": f"family.{fam}", "group": "Packing zones",
                    "label": FAMILY_LABELS[fam], "source": "Impect", "text": text})
    contexts = {d["context_name"]: d for d in defs.values()
                if d.get("context_name") and d.get("context_definition")}
    for zone in ZONES:
        ctx = contexts.get(zone)
        out.append({"key": f"zone.{zone}", "group": "Packing zones",
                    "label": ctx["context_label"] if ctx else ZONE_LABELS[zone],
                    "source": "Impect",
                    "text": first_sentence(ctx["context_definition"]) if ctx
                    else NOT_PUBLISHED.format(provider="Impect")})
    for code, (column, label) in AVAILABILITY.items():
        d = defs.get(column) or {}
        text = d.get("context_definition") or d.get("definition")
        out.append({"key": f"avail.{code}", "group": "Packing zones", "label": label,
                    "source": "Impect",
                    "text": first_sentence(text) if text else NOT_PUBLISHED.format(provider="Impect")})

    out += style_entries(defs)

    for key in ("offensive", "defensive"):
        side = "attacking" if key == "offensive" else "defensive"
        out.append({"key": f"score.{key}", "group": "Impect scores", "label": SCORES[key][1],
                    "source": "Impect",
                    "text": f"Impect's rating of his {side} actions. Impect does not publish "
                            "how it is calculated."})
    return out


def style_entries(defs: dict) -> list[dict]:
    """Playing styles: one entry per signal a style uses -- the Impect metrics it is built
    from, then Impect's definition of each metric and of each context (e.g. Low Cross), once."""
    from lofc.model import styles as st
    used = [s for g in st.STYLES.values() for styles in g.values() for sigs in styles.values()
            for s in sigs]
    out = []
    for sig in dict.fromkeys(used):
        built, columns = st.SIGNAL_SOURCES[sig]
        parts, seen = [f"**Built from (Impect):** {built}"], set()
        for col in columns:
            d = defs.get(col) or {}
            for label, text in ((d.get("label"), d.get("definition")),
                                (d.get("context_label"), d.get("context_definition"))):
                if label and text and label not in seen:
                    seen.add(label)
                    parts.append(f"**{label}**: {clean_definition(text)}")
        if sig in st.QUALITY_SIGNALS:
            parts.append("⚑ This signal measures success, not only what he attempts.")
        out.append({"key": f"style.{sig}", "group": "Playing styles",
                    "label": st.SIGNAL_LABELS[sig], "source": "Impect",
                    "text": "\n\n".join(parts)})
    return out


def rating_metrics() -> set[str]:
    """The 39 metrics that build the rating: every position's Performance metrics (as the
    scoring resolves them) plus the Physical ones. Straight from the scoring code."""
    from lofc.model import club_framework as cf
    from lofc.model.scorecard import _resolved_performance
    return ({m for p in cf.PERFORMANCE_METRICS for m in _resolved_performance(p)}
            | {m for v in cf.PHYSICAL_METRICS.values() for m in v})
