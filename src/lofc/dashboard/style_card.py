"""The player card's Style pills and Style fit section (approved design, 2026-10-23).

Solid pill = Strong, dashed outline = Leans. Style fit shows one bar per style of the
player's position -- a winger's grouped "Where he plays" / "What he does" -- with markers at
the Leans and Strong lines and the signals behind each bar written underneath, so a label
can always be traced to what was measured. Pure: returns HTML; the card renders it.
"""

from __future__ import annotations

import html as _html

import pandas as pd

from lofc.model import styles as st

_GROUP_TITLES = {"Where": "Where he plays", "What": "What he does", "Style": "Style"}
_PEERS = {"Full Back": "full backs", "Centre Back": "centre backs",
          "Central midfield": "central midfielders", "Attacking Mid": "attacking midfielders",
          "Winger": "wingers", "Centre Forward": "centre forwards"}

CSS = """
<style>
.style-pill{display:inline-block;border-radius:999px;padding:3px 12px;font-size:.85rem;
  font-weight:600;line-height:1.4;white-space:nowrap;margin-right:6px}
.style-pill.strong{background:#1A1A1A;color:#FFFFFF;border:1px solid #1A1A1A}
.style-pill.leans{background:#FFFFFF;color:#4A4A4A;border:1px dashed #8A8A8A}
.style-none{font-size:.9rem;color:#6B6B6B}
.style-fit{border:1px solid #E6E6E6;border-radius:12px;padding:18px 22px;margin:8px 0 16px}
.style-fit h5{margin:0;font-size:1.05rem;font-weight:700}
.style-fit .sub{font-size:.8rem;color:#6B6B6B}
.style-fit .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
  gap:28px;margin-top:14px}
.style-fit .gtitle{font-size:.75rem;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;color:#6B6B6B;margin-bottom:10px}
.style-fit .row{margin-bottom:14px}
.style-fit .head{display:flex;justify-content:space-between;align-items:center;
  font-size:.95rem;font-weight:600}
.style-fit .tag{font-size:.8rem;color:#6B6B6B;font-weight:600}
.style-fit .tag.strong{color:#1A1A1A;font-weight:700}
.style-fit .track{position:relative;height:12px;background:#F0F0F2;border-radius:6px;
  margin:5px 0 4px}
.style-fit .fill{position:absolute;left:0;top:0;bottom:0;border-radius:6px}
.style-fit .m50{position:absolute;left:50%;top:-3px;width:1px;height:18px;background:#8A8A8A}
.style-fit .m70{position:absolute;left:70%;top:-3px;width:2px;height:18px;background:#1A1A1A}
.style-fit .sig{font-size:.75rem;color:#6B6B6B}
.style-fit .key{display:flex;gap:18px;flex-wrap:wrap;font-size:.75rem;color:#4A4A4A;
  border-top:1px solid #F0F0F0;padding-top:10px;margin-top:4px}
</style>
"""


def _e(text) -> str:
    return _html.escape(str(text))


def pills_html(strong: list[str], leans: list[str], label: str | None = None) -> str:
    """Solid pills for Strong styles, outlined for Leans; "No standout style" as plain text."""
    pills = ([f'<span class="style-pill strong">{_e(s)}</span>' for s in strong]
             + [f'<span class="style-pill leans">{_e(s)}</span>' for s in leans])
    if pills:
        return "".join(pills)
    return f'<span class="style-none">{_e(label)}</span>' if label else ""


def _fill(v: float) -> str:
    return "#1A1A1A" if v >= st.STRONG else ("#9A9AA2" if v >= st.FLOOR else "#D3D3D8")


def _tag(v: float) -> str:
    if v >= st.STRONG:
        return f'<span class="tag strong">{v:.0f} · Strong</span>'
    if v >= st.FLOOR:
        return f'<span class="tag">{v:.0f} · Leans</span>'
    return f'<span class="tag">{v:.0f}</span>'


def fit_html(row, league: str, season: str) -> str:
    """The Style fit section, or "" when the player has no style fits (no minutes, or a
    position without styles)."""
    groups = st.STYLES.get(st.style_group(row.get("position_group")))
    if not groups:
        return ""
    fits = {s: row.get(f"fit.{s}") for g in groups.values() for s in g}
    if all(v is None or pd.isna(v) for v in fits.values()):
        return ""
    cols = []
    for gname, styles in groups.items():
        rows = []
        for style, sigs in styles.items():
            v = fits.get(style)
            if v is None or pd.isna(v):
                continue
            signals = " · ".join(st.SIGNAL_LABELS[s] for s in sigs)
            rows.append(
                f'<div class="row"><div class="head"><span>{_e(style)}</span>{_tag(v)}</div>'
                f'<div class="track"><div class="fill" style="width:{v:.0f}%;'
                f'background:{_fill(v)}"></div><div class="m50"></div><div class="m70"></div>'
                f'</div><div class="sig">{_e(signals)}</div></div>')
        title = _GROUP_TITLES.get(gname, gname) if len(groups) > 1 else ""
        head = f'<div class="gtitle">{_e(title)}</div>' if title else ""
        cols.append(f"<div>{head}{''.join(rows)}</div>")
    return (f'{CSS}<div class="style-fit"><div style="display:flex;justify-content:space-between;'
            f'align-items:baseline;gap:16px;flex-wrap:wrap"><h5>Style fit</h5>'
            f'<span class="sub">vs {_e(league)} {_e(_PEERS.get(st.style_group(row.get("position_group")), "players"))}, '
            f'{_e(season)} · how he plays, not how well</span></div>'
            f'<div class="grid">{"".join(cols)}</div>'
            f'<div class="key"><span>▮ {st.STRONG:.0f} · Strong</span><span>│ {st.FLOOR:.0f} · Leans</span>'
            f"<span>Fit = average percentile of the style's signals, against players in the same "
            f"position, league and season.</span></div></div>")
