#!/usr/bin/env python3
"""Browser test harness for the new web front end (docs/frontend.md, "Testing").

Logs in with a throwaway TEST ACCOUNT, loads each page, clicks / selects / toggles every
visible control from a fresh page state, and fails on console errors, failed requests,
"None/nan/undefined" text, overflow beyond a card, overlapping radar labels, tiny key
numbers, slow actions and unexpected full-page reloads.

SETUP (once, on the Mac host -- NOT in Docker; the harness drives the Mac's own Chrome):
    python3 -m venv <somewhere>/webvenv
    <somewhere>/webvenv/bin/pip install playwright pytest
    # Do NOT run `playwright install`: the harness uses the installed Google Chrome
    # (channel="chrome"), headless.

RUN (the `web` service must be up: `docker compose up -d web`, and the `app` container too):
    <venv>/bin/python scripts/web_check.py                         # every implemented page
    <venv>/bin/python scripts/web_check.py --pages players,compare --quick
    options: --base http://localhost:8600  --widths 1280,1440,1920  --out DIR  --role ROLE
             --allow-writes (also click save/delete-like buttons)  --max-actions N

LOGIN WITHOUT CREDENTIALS: nobody's password is used. The harness creates a test account
`webcheck_<random>` in the Mac's LOCAL database via `docker compose exec app python` using
`lofc.store.users.create_user`, with a random per-run password handed over in the process
environment only (never printed, never written to disk), and deletes the account at the end
(falling back to deactivating it if rows reference it). It refuses any base URL that is not
localhost, and blocks every request to another host.

Exit code 1 on any failure. Results: stdout tables + <out>/results.json + screenshots.

Pure helpers (overlap, text scan, timing, option sampling) sit at the top and import without
playwright so tests/test_web_check.py can run anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------------------

WARM_ACTION_LIMIT_S = 1.0     # docs/frontend.md: every warm click < 1 s
FIRST_LOAD_LIMIT_S = 3.0      # first load of a page < 3 s warm
MIN_CHIP_PX = 22.0            # rating chips inside a .tile
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}

# Words that mean a blank leaked into the UI (blanks must show an em dash).
# "None of our wingers…" is a real sentence, so "None" followed by " of" is not a blank.
_BAD_TOKENS = re.compile(r"(?<![\w.])(None(?! of\b)|nan|NaN|undefined|null|\[object Object\])(?![\w])")


def is_local_base(url: str) -> bool:
    """True only for http(s) URLs whose host is the local machine."""
    p = urlparse(url)
    return p.scheme in ("http", "https") and (p.hostname or "") in LOCAL_HOSTS | {"::1"}


def scan_bad_text(text: str, context: int = 25) -> list[str]:
    """Snippets of visible text containing a leaked blank ('None', 'nan', 'NaN', 'undefined',
    'null', '[object Object]') as a whole word. Empty list = clean."""
    out = []
    for m in _BAD_TOKENS.finditer(text or ""):
        a, b = max(0, m.start() - context), min(len(text), m.end() + context)
        out.append(f"{m.group(1)!r} in ...{text[a:b].replace(chr(10), ' ')}...")
    return out


def misaligned_columns(cols: list[dict], tol: float = 4.0) -> list[str]:
    """Columns whose first body cell's content does not sit under its heading: the two x-ranges
    must overlap, and in a centred (chip) column the centres must be within `tol` px.
    cols: {name, head: {x, w}, cell: {x, w}, centred}."""
    out = []
    for c in cols:
        h, d = c["head"], c["cell"]
        if min(h["x"] + h["w"], d["x"] + d["w"]) - max(h["x"], d["x"]) <= 0:
            out.append(f"column {c['name']!r}: value has no overlap with its heading")
        elif c.get("centred") and abs((h["x"] + h["w"] / 2) - (d["x"] + d["w"] / 2)) > tol:
            out.append(f"column {c['name']!r}: value centre {abs((h['x'] + h['w'] / 2) - (d['x'] + d['w'] / 2)):.0f}px off its heading's centre")
    return out


def radar_sibling_overlaps(cards: list[dict]) -> list[str]:
    """Radars that cover another element of their own card (e.g. a sticky radar sliding over
    the notes under it). cards: {name, radar: {x,y,w,h}, siblings: [{text,x,y,w,h}]}."""
    out = []
    for c in cards:
        for sib in c["siblings"]:
            if rects_overlap(c["radar"], sib, tol=1.0):
                out.append(f"radar in {c['name']!r} overlaps {sib.get('text', '')[:40]!r}")
    return out


def clipped_tables(items: list[dict], tol: float = 1.0) -> list[str]:
    """Tables (or their scroll wrappers) inside a card whose content is wider than their box:
    columns are hidden or need a sideways scroll. items: {name, scrollWidth, clientWidth}."""
    return [f"table wider than its box by {it['scrollWidth'] - it['clientWidth']:.0f}px: {it['name']}"
            for it in items if it["scrollWidth"] > it["clientWidth"] + tol and not it.get("scroll_ok")]


def rects_overlap(a: dict, b: dict, tol: float = 0.5) -> bool:
    """Do two {x,y,w,h} boxes intersect by more than `tol` px in BOTH axes?"""
    ix = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    iy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    return ix > tol and iy > tol


def find_overlaps(items: list[dict], tol: float = 0.5) -> list[tuple[str, str]]:
    """Pairs of labels whose boxes intersect. Each item: {text, x, y, w, h}."""
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if rects_overlap(items[i], items[j], tol):
                pairs.append((items[i]["text"], items[j]["text"]))
    return pairs


def classify_timing(elapsed_s: float, first_visit: bool = False) -> str:
    """'ok' or 'slow' against the brief: 1.0 s for a warm action, 3.0 s for a page's first
    load. Exactly on the limit is ok."""
    limit = FIRST_LOAD_LIMIT_S if first_visit else WARM_ACTION_LIMIT_S
    return "ok" if elapsed_s <= limit else "slow"


def sample_options(options: list, cap: int) -> list:
    """At most `cap` options, always including the first and last, the rest evenly spread.
    Deterministic, order preserved, no duplicates."""
    n = len(options)
    if cap <= 0:
        return []
    if n <= cap:
        return list(options)
    if cap == 1:
        return [options[0]]
    idx = sorted({round(i * (n - 1) / (cap - 1)) for i in range(cap)})
    return [options[i] for i in idx]


def sample_controls(controls: list[dict], per_group: int = 2, max_total: int = 60) -> list[dict]:
    """Collapse repeated controls (200 identical 'Add' buttons, 500 table rows) to a few per
    (kind, label) group, then cap the total, keeping page order."""
    groups: dict[tuple, list[dict]] = {}
    for c in controls:
        groups.setdefault((c["kind"], c["label"]), []).append(c)
    keep = set()
    for g in groups.values():
        for c in sample_options(g, per_group):
            keep.add(c["idx"])
    kept = [c for c in controls if c["idx"] in keep]
    return sample_options(kept, max_total) if len(kept) > max_total else kept


def is_destructive(label: str) -> bool:
    """Buttons the exerciser must not press by default: they end the session or write
    (adding to / removing from the watchlist writes a row; a plain "Watchlist" nav link
    only navigates)."""
    return bool(re.search(r"\b(log ?out|sign ?out|delete|remove|deactivate|reactivate|reset|discard|"
                          r"clear lockout|unlock|"
                          r"save|submit|approve|reject|publish|create|add user|change password|"
                          r"(add to|on|from) watchlist|refresh|sync)\b",
                          label or "", re.I))


def is_external(label: str) -> bool:
    """Buttons never pressed, not even with --allow-writes: Scout reports "Refresh" reads the
    club's Google scouting sheet (and writes the result to the database)."""
    return bool(re.search(r"\b(refresh|sync)\b", label or "", re.I))


def summarize(durations: list[float]) -> tuple[float, float]:
    """(slowest, median) of action durations; zeros when empty."""
    if not durations:
        return 0.0, 0.0
    return max(durations), statistics.median(durations)


def new_password() -> str:
    # urlsafe token is far over the 12-char minimum in dashboard.auth.PASSWORD_MIN_LENGTH.
    return "Wc1-" + secrets.token_urlsafe(24)


# ---------------------------------------------------------------------------------------
# In-page JavaScript
# ---------------------------------------------------------------------------------------

INIT_JS = r"""
(() => {
  window.__wcToken = Math.random().toString(36).slice(2);   // lost on a full page load
  window.__wcMut = performance.now();
  const start = () => {
    new MutationObserver(ms => {
      if (ms.some(m => m.attributeName !== 'data-wc-idx')) window.__wcMut = performance.now();
    }).observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
  };
  if (document.documentElement) start(); else document.addEventListener('DOMContentLoaded', start);
})();
"""

_MAIN = "(document.querySelector('main, [role=main], #main, .main, .content') || document.body)"

DISCOVER_JS = r"""
() => {
  const main = %(main)s;
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
      && !e.closest('[hidden],[aria-hidden=true]'); };
  document.querySelectorAll('[data-wc-idx]').forEach(e => e.removeAttribute('data-wc-idx'));
  const out = []; const seen = new Set(); let i = 0;
  const cur = location.pathname;
  const add = (e, kind, extra) => {
    if (seen.has(e) || !vis(e) || e.disabled) return; seen.add(e);
    // form fields are named by their <label>/aria-label/name, not by their current value
    const field = ['select', 'text', 'checkbox', 'radio', 'range'].includes(kind);
    const label = ((e.getAttribute('aria-label') || (field && e.labels && e.labels[0] && e.labels[0].innerText)
      || (field ? (e.placeholder || e.name || e.id) : (e.innerText || e.value))
      || e.getAttribute('data-action') || e.name || e.id || e.tagName) + '').trim()
      .replace(/\s+/g, ' ').slice(0, 40);
    e.setAttribute('data-wc-idx', i);
    out.push(Object.assign({idx: i++, kind, label, tag: e.tagName.toLowerCase()}, extra || {}));
  };
  main.querySelectorAll('select').forEach(e => add(e, 'select', {
    options: [...e.options].filter(o => !o.disabled).map(o => ({value: o.value, text: o.text.trim()})),
    current: e.value}));
  main.querySelectorAll('input').forEach(e => {
    const t = (e.type || 'text').toLowerCase();
    if (t === 'checkbox' || t === 'radio') add(e, t);
    else if (t === 'range') add(e, 'range', {min: +e.min || 0, max: +e.max || 100});
    else if (['text', 'search', 'number', 'email', 'tel', 'url'].includes(t))
      add(e, 'text', {num: t === 'number', min: e.min, max: e.max});
  });
  main.querySelectorAll('textarea').forEach(e => add(e, 'text'));
  // a row with data-href opens another page (a player's card): navigation is its job
  main.querySelectorAll('[data-href], tr[onclick], [data-row]').forEach(e => {
    const h = e.getAttribute('data-href');
    add(e, 'row', h ? {allowNav: new URL(h, location.href).pathname !== cur} : {});
  });
  main.querySelectorAll('button, [role=button], [data-action], summary, [onclick]').forEach(e => {
    if (!e.closest('select')) add(e, 'button');
  });
  main.querySelectorAll('a[href]').forEach(e => {
    const h = e.getAttribute('href') || '';
    if (h.startsWith('javascript:') || h.startsWith('mailto:') || e.target === '_blank') return;
    const u = new URL(h, location.href);
    if (u.origin !== location.origin) return;
    add(e, 'link', {href: u.pathname + u.search, allowNav: u.pathname !== cur});
  });
  return out;
}
""" % {"main": _MAIN}

STATIC_JS = r"""
() => {
  const main = %(main)s;
  const res = {text: main.innerText || '', overflow: [], radar: [], tiny: []};
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const name = e => e.tagName.toLowerCase() + (e.className && e.className.baseVal === undefined
    ? '.' + String(e.className).trim().split(/\s+/).slice(0, 2).join('.') : '')
    + ' "' + (e.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 30) + '"';
  const clipped = (e, card) => {          // inside a scroll / clip container below the card?
    for (let p = e.parentElement; p && p !== card; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if (o === 'auto' || o === 'scroll' || o === 'hidden' || o === 'clip') return true;
    }
    return false;
  };
  document.querySelectorAll('.card').forEach(card => {
    if (!vis(card)) return;
    const cr = card.getBoundingClientRect();
    if (card.scrollWidth > card.clientWidth + 1 && !/auto|scroll/.test(getComputedStyle(card).overflowX))
      res.overflow.push('card scrollWidth ' + card.scrollWidth + ' > ' + card.clientWidth + ': ' + name(card));
    card.querySelectorAll('*').forEach(e => {
      if (e instanceof SVGElement && e.tagName.toLowerCase() !== 'svg') return;
      if (!vis(e) || getComputedStyle(e).position === 'fixed') return;
      const s = getComputedStyle(e);
      if (e.clientWidth > 0 && e.scrollWidth > e.clientWidth + 1
          && !/auto|scroll/.test(s.overflowX)
          && !(s.overflowX === 'hidden' && s.textOverflow === 'ellipsis'))
        res.overflow.push('scrollWidth ' + e.scrollWidth + ' > clientWidth ' + e.clientWidth + ': ' + name(e));
      const r = e.getBoundingClientRect();
      if ((r.right > cr.right + 1 || r.left < cr.left - 1) && !clipped(e, card))
        res.overflow.push('beyond card by ' + Math.round(Math.max(r.right - cr.right, cr.left - r.left))
          + 'px: ' + name(e));
    });
  });
  document.querySelectorAll('svg').forEach((svg, k) => {
    const items = [];
    svg.querySelectorAll('text').forEach(t => {
      const r = t.getBoundingClientRect(); const s = getComputedStyle(t);
      if (r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
          && (t.textContent || '').trim())
        items.push({text: t.textContent.trim().slice(0, 30), x: r.x, y: r.y, w: r.width, h: r.height});
    });
    if (items.length > 1) res.radar.push({svg: k, items});
  });
  res.tables = [];
  document.querySelectorAll('.card table').forEach(t => {
    if (!vis(t)) return;
    const box = t.parentElement;
    const id = (t.id ? '#' + t.id : '') || (box && box.id ? '#' + box.id : '')
      || (t.closest('[id]') ? '#' + t.closest('[id]').id : '');
    const name = 'table ' + id + ' "' + (t.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40) + '"';
    const scroll_ok = !!t.closest('[data-scroll-x]');
    res.tables.push({name, scroll_ok, scrollWidth: Math.round(t.getBoundingClientRect().width), clientWidth: box.clientWidth});
    for (let p = box; p && !p.classList.contains('card'); p = p.parentElement)
      if (p.scrollWidth > p.clientWidth + 1) { res.tables.push({name: 'wrapper of ' + name, scroll_ok, scrollWidth: p.scrollWidth, clientWidth: p.clientWidth}); break; }
  });
  document.querySelectorAll('.tile .chip, .tile [class*="chip"]').forEach(e => {
    if (!vis(e) || !(e.innerText || '').trim()) return;
    const fs = parseFloat(getComputedStyle(e).fontSize);
    if (fs < %(min)s) res.tiny.push(fs + 'px: ' + name(e));
  });
  return res;
}
""" % {"main": _MAIN, "min": MIN_CHIP_PX}

RADAR_SIBLINGS_JS = r"""
() => {
  const out = [];
  document.querySelectorAll('main .card').forEach((card, k) => {
    const rd = card.querySelector('.rdr');
    if (!rd || !rd.offsetParent) return;
    const r = rd.getBoundingClientRect();
    const sibs = [];
    card.querySelectorAll('h2, .sub, p, .note, .rdr-note, table, .rkey').forEach(e => {
      if (rd.contains(e) || e.contains(rd) || !e.offsetParent) return;
      const b = e.getBoundingClientRect();
      if (b.width && b.height) sibs.push({text: (e.innerText || '').trim().slice(0, 40), x: b.x, y: b.y, w: b.width, h: b.height});
    });
    out.push({name: card.id || ('card' + k), radar: {x: r.x, y: r.y, w: r.width, h: r.height}, siblings: sibs});
  });
  return out;
}
"""

ALIGN_JS = r"""
() => {
  const out = [];
  const box = n => { const r = document.createRange(); r.selectNodeContents(n); const b = r.getBoundingClientRect(); return {x: b.x, w: b.width}; };
  document.querySelectorAll('main table').forEach((t, k) => {
    const tr = t.getBoundingClientRect();
    if (!tr.width || !t.offsetParent) return;
    const hr = t.tHead && t.tHead.rows.length ? t.tHead.rows[t.tHead.rows.length - 1] : null;
    if (!hr || [...hr.cells].some(c => c.colSpan > 1)) return;
    const body = [...(t.tBodies[0] ? t.tBodies[0].rows : [])].find(r => !r.classList.contains('sec')
      && r.cells.length === hr.cells.length && ![...r.cells].some(c => c.colSpan > 1));
    if (!body) return;
    const id = t.id || (t.closest('[id]') || {}).id || ('table' + k);
    [...hr.cells].forEach((th, i) => {
      const td = body.cells[i], h = box(th), d = box(td);
      if (!h.w || !d.w || !(th.innerText || '').trim()) return;
      out.push({name: id + ' / ' + th.innerText.trim().replace(/\s+/g, ' ').slice(0, 30), head: h, cell: d,
                centred: !!td.querySelector('.chip')});
    });
  });
  return out;
}
"""

SNAPSHOT_JS = r"""
() => {
  const main = %(main)s; const o = {};
  main.querySelectorAll('select, input, textarea').forEach((e, i) => {
    const k = (e.name || e.id || e.getAttribute('aria-label') || e.placeholder || 'c' + i);
    o[k] = (e.type === 'checkbox' || e.type === 'radio') ? e.checked : e.value;
  });
  return {q: location.search, controls: o};
}
""" % {"main": _MAIN}


# ---------------------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------------------

@dataclass
class ActionResult:
    page: str
    desc: str
    seconds: float
    failures: list[str] = field(default_factory=list)
    skipped: str = ""


class Recorder:
    """Collects browser-side events for one page object between drains."""

    def __init__(self, page, base_host: str):
        self.page, self.base_host = page, base_host
        self.console, self.pageerrors, self.bad_responses, self.failed = [], [], [], []
        self.external, self.navs = [], 0
        self.pending, self.last_net = 0, time.perf_counter()
        self.allow_status: set[int] = set()
        page.on("console", self._console)
        page.on("pageerror", lambda e: self.pageerrors.append(str(e)))
        page.on("request", self._req)
        page.on("requestfinished", self._done)
        page.on("requestfailed", self._fail)
        page.on("response", self._resp)
        page.on("framenavigated", lambda f: self._nav(f))

    def _console(self, m):
        if m.type != "error":
            return
        # Chrome logs "Failed to load resource ... status of 401" for every 4xx; a status the
        # test deliberately provokes (allow_status) must not also count as a console error.
        mm = re.search(r"status of (\d+)", m.text)
        if mm and int(mm.group(1)) in self.allow_status:
            return
        self.console.append(m.text)

    def _nav(self, f):
        if f == self.page.main_frame:
            self.navs += 1
            # A navigation aborts whatever was in flight; in a routed context Playwright then
            # emits neither "finished" nor "failed" for it, so the count would stay above zero
            # for the rest of the run and every later settle() would time out at 8 s.
            self.pending = 0

    def _req(self, r):
        self.pending += 1
        self.last_net = time.perf_counter()

    def _done(self, r):
        self.pending = max(0, self.pending - 1)
        self.last_net = time.perf_counter()

    def _fail(self, r):
        self.pending = max(0, self.pending - 1)
        self.last_net = time.perf_counter()
        err = (r.failure or "")
        if "ERR_ABORTED" in err:       # cancelled by navigation / our own external block
            if urlparse(r.url).hostname not in LOCAL_HOSTS:
                self.external.append(r.url)
            return
        self.failed.append(f"{r.method} {r.url} -> {err}")

    def _resp(self, r):
        if r.status >= 400 and r.status not in self.allow_status:
            self.bad_responses.append(f"{r.status} {r.request.method} {r.url}")

    def drain(self) -> list[str]:
        out = ([f"console error: {m}" for m in self.console]
               + [f"page error: {m}" for m in self.pageerrors]
               + [f"HTTP {m}" for m in self.bad_responses]
               + [f"request failed: {m}" for m in self.failed]
               + [f"external request blocked: {u}" for u in sorted(set(self.external))])
        self.console, self.pageerrors, self.bad_responses = [], [], []
        self.failed, self.external, self.navs = [], [], 0
        return out


# ---------------------------------------------------------------------------------------
# Test account (local database, via the app container)
# ---------------------------------------------------------------------------------------

_CREATE = """
import os
from sqlalchemy import text
from lofc.store.load import get_engine
from lofc.store.users import create_user
e = get_engine()
uid = create_user(e, os.environ['WC_USER'], 'Web Check', os.environ['WC_ROLE'], os.environ['WC_PW'])
with e.begin() as c:   # a fresh account is forced to change its password; the harness skips that
    c.execute(text('update users set must_change_password = false where id = :i'), {'i': uid})
print(uid)
"""
_REMOVE = """
import os
from sqlalchemy import text
from lofc.store.load import get_engine
from lofc.store.users import set_active
e = get_engine()
u = os.environ['WC_USER']
if not u.startswith('webcheck_'):
    raise SystemExit('refusing to touch a non-harness account')
try:
    with e.begin() as c:
        c.execute(text('delete from users where username = :u'), {'u': u})
    print('deleted')
except Exception:
    with e.begin() as c:
        uid = c.execute(text('select id from users where username = :u'), {'u': u}).scalar()
    set_active(e, uid, False)
    print('deactivated')
"""


def _compose(code: str, env: dict) -> str:
    # `-e NAME` (no value) makes docker copy the variable from OUR environment, so the
    # password never appears on a command line.
    cmd = ["docker", "compose", "exec", "-T"]
    for k in env:
        cmd += ["-e", k]
    cmd += ["app", "python", "-c", code]
    r = subprocess.run(cmd, cwd=REPO, env={**os.environ, **env}, capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        raise RuntimeError("test-account command failed: " + " | ".join(tail))
    return r.stdout.strip()


# ---------------------------------------------------------------------------------------
# Browser session
# ---------------------------------------------------------------------------------------

class Session:
    """One page, reused. `step()` is the unit of testing: do something, wait for the page to
    settle, then run every check and record one ActionResult."""

    def __init__(self, page, base: str, out: Path, widths: list[int], quick: bool,
                 allow_writes: bool, max_actions: int):
        self.page, self.base, self.out = page, base.rstrip("/"), out
        self.widths, self.quick, self.allow_writes = widths, quick, allow_writes
        self.max_actions = max_actions
        self.rec = Recorder(page, urlparse(base).hostname or "")
        self.results: list[ActionResult] = []
        self.cur_page = ""
        self.cur_path = "/"
        self.visited: set[str] = set()
        self.seen_static: set[str] = set()   # a defect already reported on this page is not repeated
        self.shots: list[str] = []
        page.on("dialog", lambda d: d.accept())
        page.context.on("page", lambda p: p.close() if p.opener() is not None else None)  # stray popups

    # -- waiting ------------------------------------------------------------------------
    def settle(self, t0: float, timeout: float = 8.0, quiet: float = 0.15) -> float:
        """Seconds from t0 until the last network event or DOM mutation, once both have been
        quiet for `quiet` s and no request is pending. `timeout` if it never settles."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            try:
                mut_age = self.page.evaluate("performance.now() - (window.__wcMut || 0)") / 1000.0
            except Exception:       # mid-navigation; try again
                time.sleep(0.03)
                continue
            now = time.perf_counter()
            if self.rec.pending == 0 and now - self.rec.last_net >= quiet and mut_age >= quiet:
                end = max(t0, self.rec.last_net, now - mut_age)
                return end - t0
            time.sleep(0.025)
        return timeout

    # -- navigation ---------------------------------------------------------------------
    def forget_pages(self):
        """Drop every page's remembered settings ('lofc.<page>.last', owner 2026-11-13) so a
        bare URL opens on its defaults, as each scenario expects. Drafts etc. are kept."""
        try:
            if self.page.url.startswith(self.base):
                self.page.evaluate("""() => { try { for (const k of Object.keys(localStorage))
                    if (/^lofc\\.[\\w-]+\\.last$/.test(k)) localStorage.removeItem(k); } catch (e) {} }""")
        except Exception:
            pass

    def goto(self, path: str, check: bool = True, desc: str | None = None, label: str = "load",
             forget: bool = True):
        if forget:
            self.forget_pages()
        first = path not in self.visited
        self.visited.add(path)
        self.rec.drain()
        t0 = time.perf_counter()
        resp = self.page.goto(self.base + path, wait_until="load")
        secs = self.settle(t0)
        secs = max(secs, 0.0)
        # settle() measures to the last activity; a slow response without activity is covered
        # by wall time to `load`.
        secs = max(secs, time.perf_counter() - t0 - 0.15) if secs >= 8.0 else secs
        if not check:
            return resp, secs
        fails = self.rec.drain()
        if resp is not None and resp.status >= 400 and resp.status not in self.rec.allow_status:
            fails.append(f"HTTP {resp.status} on {path}")
        fails += self.static_checks(new_only=True)
        if classify_timing(secs, first_visit=True) == "slow" and first:
            fails.append(f"slow first load {secs:.2f}s (limit {FIRST_LOAD_LIMIT_S}s)")
        elif classify_timing(secs, first_visit=True) == "slow":
            fails.append(f"slow load {secs:.2f}s (limit {FIRST_LOAD_LIMIT_S}s)")
        self.results.append(ActionResult(self.cur_page, desc or f"{label} {path}", secs, fails))
        return resp, secs

    # -- checks -------------------------------------------------------------------------
    def static_checks(self, new_only: bool = False) -> list[str]:
        fails = self._static_checks()
        if not new_only:
            return fails
        fresh = [f for f in fails if (self.cur_page, f) not in self.seen_static]
        self.seen_static.update((self.cur_page, f) for f in fails)
        return fresh

    def _static_checks(self) -> list[str]:
        try:
            r = self.page.evaluate(STATIC_JS)
        except Exception as e:
            return [f"static checks could not run: {e}"]
        fails = [f"visible bad text: {s}" for s in scan_bad_text(r["text"])[:5]]
        fails += [f"overflow: {s}" for s in r["overflow"][:5]]
        for g in r["radar"]:
            for a, b in find_overlaps(g["items"])[:5]:
                fails.append(f"overlapping SVG labels (svg #{g['svg']}): {a!r} / {b!r}")
        fails += [f"tiny key number {s}" for s in r["tiny"][:5]]
        fails += clipped_tables(r.get("tables", []))[:5]
        return fails

    def snapshot(self) -> dict:
        return self.page.evaluate(SNAPSHOT_JS)

    # -- the unit of testing ------------------------------------------------------------
    def step(self, desc: str, fn, expect_nav: bool = False, limit: float | None = None):
        """Run fn(page) as one action. Records timing and every failure."""
        self.rec.drain()
        self.page.evaluate("window.__wcMut = performance.now()")
        token = self.page.evaluate("window.__wcToken")
        t0 = time.perf_counter()
        fails: list[str] = []
        try:
            fn(self.page)
        except Exception as e:
            fails.append(f"action failed: {str(e).splitlines()[0][:160]}")
        secs = self.settle(t0)
        navs = self.rec.navs
        fails += self.rec.drain()
        try:
            same = self.page.evaluate("window.__wcToken") == token
        except Exception:
            same = False
        if not same and not expect_nav:
            fails.append("full page navigation/reload for an in-page control")
        fails += self.static_checks(new_only=True)
        lim = limit or (FIRST_LOAD_LIMIT_S if expect_nav else WARM_ACTION_LIMIT_S)
        if secs > lim:
            fails.append(f"slow action {secs:.2f}s (limit {lim}s)")
        res = ActionResult(self.cur_page, desc, secs, fails)
        self.results.append(res)
        return res

    def note(self, desc: str, failure: str | None = None, skipped: str = ""):
        """Record a scenario assertion (no action performed)."""
        self.results.append(ActionResult(self.cur_page, desc, 0.0,
                                         [failure] if failure else [], skipped))

    def shot(self, name: str, width: int, full: bool = False):
        self.out.mkdir(parents=True, exist_ok=True)
        p = self.out / f"{self.cur_page}_{name}_{width}.png"
        try:
            self.page.screenshot(path=str(p), full_page=full)
            self.shots.append(str(p))
        except Exception as e:
            self.note(f"screenshot {p.name}", f"screenshot failed: {e}")

    # -- locating form controls by their visible label -----------------------------------
    def control(self, label: str, kind: str = "select"):
        """A visible control in <main> whose label / name / id / placeholder matches `label`
        (case-insensitive substring), or None."""
        p = self.page
        tag = {"select": "select", "text": "input:not([type=checkbox]):not([type=radio]):not([type=range])"}[kind]
        loc = p.get_by_label(re.compile(label, re.I))
        try:
            cand = loc.locator(f"xpath=self::{tag.split(':')[0]}")
            if cand.count():
                return cand.first
        except Exception:
            pass
        for sel in (f'{tag}[name*="{label}" i]', f'{tag}[id*="{label}" i]',
                    f'{tag}[aria-label*="{label}" i]', f'{tag}[placeholder*="{label}" i]'):
            c = p.locator(sel)
            if c.count():
                return c.first
        return None

    # -- generic exerciser --------------------------------------------------------------
    def exercise(self, path: str):
        """Discover every control on `path`; run each from a fresh load."""
        self.goto(path, check=False)
        controls = self.page.evaluate(DISCOVER_JS)
        n_all = len(controls)
        skip_d = [c for c in controls if c["kind"] in ("button", "link", "row")
                  and (is_external(c["label"]) or (not self.allow_writes and is_destructive(c["label"])))]
        controls = [c for c in controls if c not in skip_d]
        cap = min(self.max_actions, 20 if self.quick else 60)
        chosen = sample_controls(controls, per_group=1 if self.quick else 2, max_total=cap)
        for c in skip_d:
            self.note(f"{c['kind']} '{c['label']}'", skipped=(
                "reads the club's scouting sheet: never pressed" if is_external(c["label"])
                else "write/sign-out control (use --allow-writes)"))
        opt_cap = 3 if self.quick else 6
        url_checks = 0
        for c in chosen:
            for desc, fn, expect_nav in self._plan(c, opt_cap):
                self.goto(path, check=False)
                fresh = self.page.evaluate(DISCOVER_JS)       # re-tag data-wc-idx on this load
                tgt = next((x for x in fresh if x["idx"] == c["idx"] and x["label"] == c["label"]
                            and x["kind"] == c["kind"]), None) \
                    or next((x for x in fresh if x["label"] == c["label"] and x["kind"] == c["kind"]), None)
                if tgt is None:
                    self.note(desc, skipped="control not present on fresh load")
                    continue
                loc = self.page.locator(f'[data-wc-idx="{tgt["idx"]}"]')
                before = self.page.url
                res = self.step(desc, lambda p, l=loc, f=fn: f(l), expect_nav=expect_nav or tgt.get("allowNav", False))
                if self.page.url != before and not res.failures and url_checks < (3 if self.quick else 8) \
                        and urlparse(self.page.url).path == urlparse(before).path:
                    url_checks += 1
                    self._url_roundtrip(desc, before)
        return n_all

    def _plan(self, c: dict, opt_cap: int):
        k, lab = c["kind"], c["label"]
        if k == "select":
            others = [o for o in c["options"] if o["value"] != c["current"]]
            for o in sample_options(others, opt_cap):
                yield (f"select '{lab}' = {o['text'][:30]!r}",
                       lambda l, v=o["value"]: l.select_option(value=v, timeout=3000), False)
        elif k in ("checkbox", "radio"):
            yield (f"toggle {k} '{lab}'", lambda l: l.click(timeout=3000), False)
        elif k == "range":
            lo, hi = c["min"], c["max"]
            for name, v in (("min", lo), ("mid", (lo + hi) / 2), ("max", hi)):
                yield (f"range '{lab}' {name}", lambda l, v=v: l.evaluate(
                    "(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true}));"
                    " e.dispatchEvent(new Event('change', {bubbles: true})); }", v), False)
        elif k == "text":
            vals = ["1"] if c.get("num") else ["a", "zzzz-no-such-player"]
            for v in vals[:1 if self.quick else 2]:
                yield (f"type '{lab}' = {v!r}", lambda l, v=v: (l.fill(v, timeout=3000), l.press("Enter")), False)
        elif k == "link":
            yield (f"click link '{lab}'", lambda l: l.click(timeout=3000), c.get("allowNav", False))
        else:
            yield (f"click {k} '{lab}'", lambda l: l.click(timeout=3000), c.get("allowNav", False))

    def _url_roundtrip(self, desc: str, before_url: str):
        """After a control changed the URL: back restores it, and the new URL reproduces the
        same controls when opened fresh (shareable)."""
        after_url = self.page.url
        snap = self.snapshot()
        self.page.go_back()
        self.settle(time.perf_counter())
        ok_back = self.page.url == before_url
        self.note(f"back after {desc}", None if ok_back else
                  f"browser back gave {self.page.url}, expected {before_url}")
        self.page.go_forward()
        self.settle(time.perf_counter())
        if self.page.url != after_url:
            self.note(f"forward after {desc}", f"forward gave {self.page.url}, expected {after_url}")
        fresh = self.page.context.new_page()
        try:
            snap2 = open_fresh(fresh, after_url)
        finally:
            fresh.close()
        self.note(f"shareable URL after {desc}",
                  None if snap2["controls"] == snap["controls"] else
                  f"controls differ when {after_url} is opened fresh: "
                  f"{ {k: (snap['controls'][k], snap2['controls'].get(k)) for k in snap['controls'] if snap['controls'][k] != snap2['controls'].get(k)} }")
        self.forget_pages()
        self.page.goto(self.base + self.cur_path)


# ---------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------

def open_fresh(page, url: str) -> dict:
    """Open `url` in a new tab and snapshot its controls once the page has finished drawing
    (network idle). A fixed 0.4 s wait compared a half-drawn page whenever its first requests
    took longer -- a race in the check, not a URL-state bug; load speed is timed elsewhere."""
    page.goto(url, wait_until="load")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    time.sleep(0.2)
    return page.evaluate(SNAPSHOT_JS)


def login(s: Session, user: str, pw: str):
    p = s.page
    p.goto(s.base + "/login", wait_until="load")
    p.locator('input[name="username"], input[type="text"]').first.fill(user)
    p.locator('input[type="password"]').first.fill(pw)
    p.locator('button[type="submit"], input[type="submit"], form button').first.click()
    try:
        p.wait_for_url(lambda u: "/login" not in u, timeout=10000)
    except Exception:
        raise RuntimeError("login with the test account did not leave /login "
                           "(forced password change, lockout, or a broken login?)")


def align_checks(s: "Session", path: str) -> None:
    """Every table's values sit under their headings at 1024 / 1280 / 1440 / 1920 and after a
    live resize from 1920 to 1100 (owner bug 2026-11-09: chips drifting from their headings)."""
    def check(label):
        try:
            s.page.wait_for_timeout(250)
            cols = s.page.evaluate(ALIGN_JS)
        except Exception as e:
            return s.note(f"table alignment {label}", f"check could not run: {e}")
        s.note(f"table alignment {label}", "; ".join(misaligned_columns(cols)[:4]) or None)
    for w in (1024, 1280, 1440, 1920):
        s.page.set_viewport_size({"width": w, "height": 900})
        s.goto(path, check=False, desc=f"alignment @{w}")
        check(f"@{w}")
    s.page.set_viewport_size({"width": 1100, "height": 900})     # live resize, no reload
    check("after resize 1920 -> 1100")
    s.page.set_viewport_size({"width": 1440, "height": 900})
    s.goto(path, check=False, desc="radar siblings @1440")
    radar_scroll_check(s, path)


def radar_scroll_check(s: "Session", label: str) -> None:
    """Scroll the current page top to bottom; at each step no radar may cover another element of
    its own card (owner bug 2026-11-09, Compare: a sticky radar slid over its notes)."""
    try:
        height = s.page.evaluate("document.body.scrollHeight")
        fails, seen = [], 0
        for y in range(0, int(height) + 300, 150):
            s.page.evaluate(f"window.scrollTo(0, {y})")
            s.page.wait_for_timeout(40)
            cards = s.page.evaluate(RADAR_SIBLINGS_JS)
            seen = max(seen, len(cards))
            fails += radar_sibling_overlaps(cards)
        s.page.evaluate("window.scrollTo(0, 0)")
        if seen:
            s.note(f"radar never covers a note while scrolling ({label})",
                   "; ".join(sorted(set(fails))[:4]) or None)
    except Exception as e:
        s.note(f"radar never covers a note while scrolling ({label})", f"check could not run: {e}")

def run_page(s: Session, name: str, spec: dict, widths: list[int], primary: int):
    s.cur_page, s.cur_path = name, spec["path"]
    s.page.set_viewport_size({"width": primary, "height": 900})
    s.visited.discard(spec["path"])
    resp, _ = s.goto(spec["path"], check=True, desc=f"load {spec['path']} @{primary}")
    if resp is not None and resp.status == 404:
        s.results = [r for r in s.results if r.page != name]
        return False
    for w in widths:                                  # layout checks + screenshots per width
        s.page.set_viewport_size({"width": w, "height": 900})
        s.goto(spec["path"], check=True, desc=f"layout @{w}")
        s.shot("page", w)
        s.shot("page_full", w, full=True)
        tog = s.page.locator('main button, main summary, [role=main] button').filter(
            has_text=re.compile("filter", re.I))
        if spec.get("exercise", True) and tog.count():
            def open_filters(p, t=tog):
                for i in range(min(t.count(), 3)):
                    t.nth(i).click(timeout=2000)
            s.step(f"open filter fold-outs @{w}", open_filters)
            s.shot("filters_open", w)
    align_checks(s, spec["path"])
    s.page.set_viewport_size({"width": primary, "height": 900})
    if spec.get("exercise", True):
        s.exercise(spec["path"])
    for scen in spec.get("scenarios", []):
        s.page.set_viewport_size({"width": primary, "height": 900})
        s.goto(spec["path"], check=False)
        try:
            scen(s, primary)
        except Exception as e:
            s.note(f"scenario {scen.__name__}", f"scenario crashed: {str(e).splitlines()[0][:200]}")
    return True


def report(results: list[ActionResult], implemented: list[str], missing: list[str]) -> int:
    fails = 0
    print(f"\n{'page':<14}{'actions':>8}{'skipped':>8}{'failures':>9}{'slowest s':>10}{'median s':>9}")
    for pg in implemented:
        rs = [r for r in results if r.page == pg]
        done = [r for r in rs if not r.skipped]
        nf = sum(1 for r in done if r.failures)
        fails += nf
        slow, med = summarize([r.seconds for r in done if r.seconds > 0])
        print(f"{pg:<14}{len(done):>8}{len(rs) - len(done):>8}{nf:>9}{slow:>10.2f}{med:>9.2f}")
    if missing:
        print("not implemented (404/unreachable), skipped:", ", ".join(missing))
    bad = [r for r in results if r.failures]
    if bad:
        print("\nFAILURES")
        for r in bad:
            print(f"- [{r.page}] {r.desc}  ({r.seconds:.2f}s)")
            for f in r.failures:
                print(f"    {f}")
    skipped = [r for r in results if r.skipped]
    if skipped:
        print(f"\n{len(skipped)} control(s) intentionally skipped, e.g. "
              + "; ".join(f"[{r.page}] {r.desc}" for r in skipped[:4]))
    print("\nRESULT:", "FAIL" if fails else "PASS", f"({fails} failing action(s))")
    return fails


def main(argv=None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from web_check_pages import PAGES, login_scenarios

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pages", default="", help="comma list; default every implemented page")
    ap.add_argument("--base", default="http://localhost:8600")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=str(REPO / "club_docs/design/web_shots"))
    ap.add_argument("--widths", default="1280,1440,1920")
    ap.add_argument("--role", default="head_of_recruitment")
    ap.add_argument("--allow-writes", action="store_true")
    ap.add_argument("--max-actions", type=int, default=60)
    ap.add_argument("--only", default="", help="comma list of scenario names: run just those (no layout pass or exerciser); for iterating")
    a = ap.parse_args(argv)

    if not is_local_base(a.base):
        print(f"refusing to run: {a.base} is not localhost", file=sys.stderr)
        return 2
    widths = [int(w) for w in a.widths.split(",") if w]
    if a.quick:
        widths = widths[1:2] or widths[:1]
    primary = 1440 if 1440 in widths else widths[0]
    wanted = [p for p in a.pages.split(",") if p] or list(PAGES)
    unknown = [p for p in wanted if p not in PAGES and p != "login"]
    if unknown:
        print("unknown page(s):", ", ".join(unknown), "- known:", ", ".join(PAGES), file=sys.stderr)
        return 2

    import urllib.request
    try:
        urllib.request.urlopen(a.base + "/healthz", timeout=5).read()
    except Exception as e:
        print(f"{a.base}/healthz not reachable ({e}); start it with: docker compose up -d web",
              file=sys.stderr)
        return 2

    from playwright.sync_api import sync_playwright

    user, pw = "webcheck_" + secrets.token_hex(4), new_password()
    env = {"WC_USER": user, "WC_PW": pw, "WC_ROLE": a.role}
    _compose(_CREATE, env)
    print("test account:", user, f"(role {a.role}); removed at the end")
    out = Path(a.out)
    results: list[ActionResult] = []
    implemented, missing = [], []
    try:
        with sync_playwright() as pw_:
            browser = pw_.chromium.launch(channel="chrome", headless=True)
            try:
                def make_ctx():
                    ctx = browser.new_context(viewport={"width": primary, "height": 900})
                    ctx.add_init_script(INIT_JS)
                    base_host = urlparse(a.base).hostname
                    ctx.route("**/*", lambda route: route.continue_()
                              if urlparse(route.request.url).hostname in LOCAL_HOSTS | {base_host}
                              or route.request.url.startswith(("data:", "blob:"))
                              else route.abort())
                    return ctx

                # Unauthenticated: the login page itself, including a deliberate 401/failed login.
                if "login" in wanted or not a.pages:
                    ctx = make_ctx()
                    s = Session(ctx.new_page(), a.base, out, widths, a.quick, a.allow_writes, a.max_actions)
                    s.cur_page = "login"
                    s.rec.allow_status = {401, 403, 429}
                    s.goto("/login", check=True)
                    for w in widths:
                        s.page.set_viewport_size({"width": w, "height": 900})
                        s.goto("/login", check=True, desc=f"layout @{w}")
                        s.shot("page", w)
                    login_scenarios(s)
                    results += s.results
                    implemented.append("login")
                    ctx.close()

                ctx = make_ctx()
                s = Session(ctx.new_page(), a.base, out, widths, a.quick, a.allow_writes, a.max_actions)
                login(s, user, pw)
                for name in wanted:
                    if name == "login":
                        continue
                    try:
                        spec = PAGES[name]
                        if a.only:
                            keep = [x for x in a.only.split(",") if x]
                            spec = {**spec, "exercise": False,
                                    "scenarios": [f for f in spec.get("scenarios", []) if f.__name__ in keep]}
                        ok = run_page(s, name, spec, [] if a.only else widths, primary)
                    except Exception as e:      # a harness/browser crash is a failure, not a pass
                        s.cur_page = name
                        s.note("harness crashed", f"{type(e).__name__}: {str(e).splitlines()[0][:200]}")
                        ok = True
                    (implemented if ok else missing).append(name)
                results += s.results
            finally:
                browser.close()
    finally:
        try:
            print("test account", _compose(_REMOVE, env))
        except Exception as e:
            print(f"WARNING: could not remove test account {user}: {e}", file=sys.stderr)

    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(
        [r.__dict__ for r in results], indent=1))
    fails = report(results, implemented, missing)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
