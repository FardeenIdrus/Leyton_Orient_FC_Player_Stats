"""Per-page definitions for scripts/web_check.py.

PAGES maps a page name (the `--pages` value) to:
  path       URL path of the page
  exercise   True (default): the generic exerciser clicks every discovered control
  scenarios  functions scenario(s, width) that script a multi-step journey

A page builder adds an entry here when a page ships (paths are best guesses from
docs/frontend.md; a path that 404s is reported as "not implemented", not as a failure).
A scenario that cannot find a control records a SKIPPED note rather than failing, so a
renamed label shows up in the summary instead of silently passing -- fix the label here.

Scenarios use `s.step(desc, fn)` (one timed, fully-checked action), `s.control(label)` to find
a select/input by its label, `s.snapshot()` (all control values + query string), and
`s.note(desc, failure)` for assertions.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse


def _radar_scroll(s, label):
    from web_check import radar_scroll_check     # lazy: web_check imports this module
    radar_scroll_check(s, label)


def _first_row(s):
    """First clickable result row / player link in the main ranking, or None."""
    for sel in ("main tr[data-href]", "main [data-href]", "main table tbody tr",
                "main a[href*='player']"):
        loc = s.page.locator(sel)
        if loc.count():
            return loc.first
    return None


def _pick_other(s, sel, desc):
    """Change a select to its first option that differs from the current one."""
    cur = sel.input_value()
    opts = sel.evaluate("e => [...e.options].filter(o => !o.disabled).map(o => o.value)")
    other = next((o for o in opts if o != cur), None)
    if other is None:
        s.note(desc, skipped="only one option")
        return False
    s.step(desc, lambda p: sel.select_option(value=other, timeout=3000))
    return True


def _need(s, label, kind="select"):
    c = s.control(label, kind)
    if c is None:
        s.note(f"find control '{label}'", skipped=f"no {kind} labelled {label!r} (update web_check_pages.py?)")
    return c


# -- Players ----------------------------------------------------------------------------

def _fold(s, name):
    """Open a filter fold-out ('more filters' / 'metric filters') if it is closed."""
    b = s.page.get_by_role("button", name=re.compile(name, re.I)).first
    if b.count() and b.get_attribute("aria-expanded") != "true":
        s.step(f"players: open {name}", lambda p: b.click(timeout=3000))


def _go_card(s, desc, click):
    """Click something that opens the player card and wait for it. The card is another page
    (checked by its own entry); here only the hand-off is asserted: it opens, with a way back."""
    s.rec.drain()
    t0 = time.perf_counter()
    try:
        click()
        s.page.wait_for_url(re.compile(r"/player/\d+/\d+/\d+"), timeout=6000)
    except Exception as e:
        return s.note(desc, f"did not reach the card: {str(e).splitlines()[0][:120]}")
    secs = s.settle(t0)
    s.rec.drain()
    s.note(desc, None if re.search(r"back=", s.page.url) else f"no back link in {s.page.url}")
    return secs


def _rows(s):
    return s.page.locator("#pl-body tr[data-href]").count()


def players_exercise_controls(s, w):
    """The generic exerciser over every filter control. Table rows are excluded from its
    sampling (there are ~1,000 of them and each click leaves the page for the card); rows are
    covered by the open/back scenarios below."""
    g = s.exercise.__globals__
    orig = g["sample_controls"]
    g["sample_controls"] = lambda cs, **kw: orig([c for c in cs if c["kind"] != "row"], **kw)
    try:
        s.exercise("/players?season=318&position=Winger")
    finally:
        g["sample_controls"] = orig


def players_first_view(s, w):
    """The ranking is visible without scrolling at 1440x900: the first rows sit inside the
    viewport, and the page opens on the live season like Streamlit."""
    s.goto("/players?position=Winger", check=False)
    first = s.page.locator("#pl-body tr[data-href]").first
    box = first.bounding_box() if first.count() else None
    if box is None:
        return s.note("players: ranking visible without scrolling", skipped="no ranking row")
    s.note("players: first ranked row inside the 1440x900 viewport",
           None if box["y"] + box["height"] <= 900 else
           f"first row ends at y={box['y'] + box['height']:.0f}px (viewport 900)")
    third = s.page.locator("#pl-body tr[data-href]").nth(4)
    if third.count() and w == 1440:
        b5 = third.bounding_box()
        s.note("players: at least five rows visible without scrolling",
               None if b5 and b5["y"] + b5["height"] <= 900 else f"5th row at y={b5 and b5['y']}")


def players_layout_widths(s, w):
    """Nothing overflows with both fold-outs open (and affordability on) at every width."""
    for width in s.widths:
        s.page.set_viewport_size({"width": width, "height": 900})
        s.goto("/players?season=318&position=Winger&money=1", check=True, desc=f"players: layout, money on @{width}")
        for name in ("more filters", "metric filters"):
            _fold(s, name)
        s.step(f"players: folds open @{width}", lambda p: p.wait_for_timeout(200))
        s.shot("filters_open", width)
    s.page.set_viewport_size({"width": w, "height": 900})


def players_position_season_open_back(s, w):
    """change position -> season -> open a player -> browser back keeps both choices."""
    pos, sea = _need(s, "position"), _need(s, "season")
    if pos is None or sea is None:
        return
    _pick_other(s, pos, "players: change position")
    _pick_other(s, sea, "players: change season")
    snap = s.snapshot()
    row = _first_row(s)
    if row is None:
        return s.note("players: open a player", skipped="no ranking row found")
    _go_card(s, "players: row opens the player card with a way back", lambda: row.click(timeout=3000))
    s.shot("card_open", w)
    s.step("players: browser back", lambda p: p.go_back(), expect_nav=True)
    snap2 = s.snapshot()
    s.note("players: back restores filters",
           None if snap2 == snap else f"before {snap} / after {snap2}")


def players_filter_open_back(s, w):
    """a More-filters choice, then open a player, then back: the filter is still applied."""
    s.goto("/players?season=318&position=Winger", check=False)
    _fold(s, "more filters")
    ct = s.control("contract")
    if ct is None:
        return s.note("players: filter -> open -> back", skipped="no Contract expiry select")
    _pick_other(s, ct, "players: change contract expiry")
    snap = s.snapshot()
    row = _first_row(s)
    if row is None:
        return s.note("players: filter -> open -> back", skipped="no ranking row")
    _go_card(s, "players: open from the filtered list", lambda: row.click(timeout=3000))
    s.step("players: back from card", lambda p: p.go_back(), expect_nav=True)
    s.note("players: filter kept after back", None if s.snapshot() == snap
           else f"before {snap} / after {s.snapshot()}")


def players_leagues(s, w):
    """Leagues pop-over: untick a league -> chip + URL + shorter or equal list; 'All leagues' resets."""
    s.goto("/players?season=318&position=Winger", check=False)
    btn = s.page.get_by_role("button", name=re.compile(r"^(All leagues|.+ leagues?)\b.*"), exact=False)
    btn = s.page.locator("#leagues-btn")
    before = _rows(s)
    s.step("players: open Leagues", lambda p: btn.click(timeout=3000))
    boxes = s.page.locator("#leagues-list input[type=checkbox]")
    if boxes.count() < 2:
        return s.note("players: leagues", skipped="fewer than two leagues")
    target = s.page.locator("#leagues-list input[value='League Two']")
    target = target if target.count() else boxes.nth(1)
    s.step("players: untick all leagues", lambda p: p.locator("#leagues-none").click(timeout=3000))
    s.step("players: tick one league", lambda p: target.check(timeout=3000))
    s.note("players: leagues in the URL", None if "leagues=" in s.page.url else f"url {s.page.url}")
    s.note("players: list narrowed to the league", None if 0 < _rows(s) <= before else f"{before} -> {_rows(s)}")
    chips = s.page.inner_text("#active")
    s.note("players: active-filter chip names the league", None if target.get_attribute("value") in chips else chips)
    s.step("players: All leagues resets", lambda p: p.locator("#leagues-all").click(timeout=3000))
    s.note("players: reset restores the list", None if _rows(s) == before else f"{before} -> {_rows(s)}")


def players_chip_remove(s, w):
    """A removable chip undoes its filter without a reload."""
    s.goto("/players?season=318&position=Winger&max_age=22", check=False)
    chip = s.page.locator("#active [data-remove='max_age']")
    if not chip.count():
        return s.note("players: remove a chip", skipped="no Max age chip")
    n = _rows(s)
    s.step("players: remove the Max age chip", lambda p: chip.click(timeout=3000))
    s.note("players: URL no longer has max_age", None if "max_age" not in s.page.url else s.page.url)
    s.note("players: list grows when the cap is removed", None if _rows(s) > n else f"{n} -> {_rows(s)}")


def players_search_other_position(s, w):
    """search finds a player from another position's pool; picking him opens his card with
    the Position switched in the way back."""
    s.goto("/players?season=318&position=Winger", check=False)
    box = s.control("search", "text")
    if box is None:
        return s.note("players: search another position", skipped="no search box")
    s.step("players: search a defender", lambda p: box.fill("Mendez", timeout=3000))
    res = s.page.locator("#search-results [data-action=pick]")
    try:
        res.first.wait_for(timeout=4000)
    except Exception:
        pass
    if not res.count():
        return s.note("players: search another position", skipped="no result for 'Mendez'")
    positions = {t.split("·")[-2].strip() for t in res.all_inner_texts() if t.count("·") >= 2}
    s.note("players: results span more than one position", None if len(positions) >= 2 else f"only {positions}")
    other = next((r for r in res.all() if "Winger" not in r.inner_text()), res.first)
    _go_card(s, "players: picking a result opens his card", lambda: other.click(timeout=3000))
    s.note("players: back link returns to /players",
           None if re.search(r"back=%2Fplayers", s.page.url) else s.page.url)
    s.step("players: back to the list", lambda p: p.go_back(), expect_nav=True)


def players_clear_search(s, w):
    s.goto("/players", check=False)
    box = s.control("search", "text")
    clear = s.page.locator("#search-clear")
    if box is None:
        return s.note("players: clear search", skipped="no search box")
    s.note("players: Clear is disabled when the box is empty", None if clear.is_disabled() else "enabled")
    s.step("players: type", lambda p: box.fill("ab", timeout=3000))
    s.step("players: Clear", lambda p: clear.click(timeout=3000))
    s.note("players: Clear empties the box", None if box.input_value() == "" else box.input_value())


def players_sort(s, w):
    """Header click sorts (asc, desc, then back to the ranking) via the API, no reload."""
    s.goto("/players?season=318&position=Winger", check=False)
    head = s.page.locator("#pl-head [data-sort='Age']")
    if not head.count():
        return s.note("players: sort", skipped="no Age header")
    s.step("players: sort by Age (asc)", lambda p: head.click(timeout=3000))
    ages = [t for t in s.page.locator("#pl-body tr td:nth-child(6)").all_inner_texts()[:40] if t != "—"]
    vals = [float(a) for a in ages]
    s.note("players: Age ascending", None if vals == sorted(vals) else f"{vals[:8]}")
    s.step("players: sort by Age (desc)", lambda p: head.click(timeout=3000))
    s.step("players: sort off", lambda p: head.click(timeout=3000))
    s.note("players: sort off clears the URL", None if "sort=" not in s.page.url else s.page.url)


def players_money(s, w):
    """Affordability on: money columns, budget/wage controls (wage slider and GBP box stay in
    step), signable switch, info-bar count; off removes them again."""
    s.goto("/players?season=318&position=Winger", check=False)
    _fold(s, "more filters")
    sw = s.page.get_by_label("Show affordability (modelled)")
    s.step("players: affordability on", lambda p: sw.check(timeout=3000))
    head = s.page.inner_text("#pl-head")
    s.note("players: money columns appear", None if all(k in head for k in (
        "Market value", "Est. wage", "Below fair value", "Fee in budget", "Wages in budget")) else head)
    s.note("players: count line has the budget breakdown",
           None if "affordable on both" in s.page.inner_text("#count-cap") else s.page.inner_text("#count-cap"))
    s.note("players: info bar gains 'affordable now'",
           None if "affordable now" in s.page.inner_text("#infobar") else "missing")
    wage_before = s.page.locator("#f-wage").input_value()
    s.step("players: wage slider to 3x", lambda p: p.locator("#f-wagex").evaluate(
        "(e) => { e.value = 3; e.dispatchEvent(new Event('input', {bubbles: true})); "
        "e.dispatchEvent(new Event('change', {bubbles: true})); }"))
    s.page.wait_for_timeout(400)
    wage_after = s.page.locator("#f-wage").input_value()
    s.note("players: GBP box follows the wage slider",
           None if wage_after and wage_after != wage_before and int(wage_after) == 3 * int(wage_before) else f"{wage_before} -> {wage_after}")
    s.step("players: budget to 20", lambda p: (p.locator("#f-budget-num").fill("20"), p.locator("#f-budget-num").press("Enter")))
    s.note("players: budget slider follows the number box",
           None if s.page.locator("#f-budget").input_value() == "20" else s.page.locator("#f-budget").input_value())
    sig = s.page.get_by_label("Only signable players")
    s.step("players: signable off", lambda p: sig.uncheck(timeout=3000))
    s.step("players: affordability off", lambda p: sw.uncheck(timeout=3000))
    s.note("players: money columns gone", None if "Market value" not in s.page.inner_text("#pl-head") else "still there")


def players_metric_filters(s, w):
    """Metric filters: a Performance slider narrows the list, a physical one can hide players
    with no value (and says so), Reset restores."""
    s.goto("/players?season=318&position=Winger", check=False)
    _fold(s, "metric filters")
    n = _rows(s)
    first = s.page.locator("#pf-sliders input[type=range]").first
    if not first.count():
        return s.note("players: metric filters", skipped="no Performance sliders")
    s.step("players: Performance slider to 70", lambda p: first.evaluate(
        "(e) => { e.value = 70; e.dispatchEvent(new Event('input', {bubbles: true})); "
        "e.dispatchEvent(new Event('change', {bubbles: true})); }"))
    s.note("players: list narrowed", None if 0 < _rows(s) < n else f"{n} -> {_rows(s)}")
    s.note("players: button counts active filters",
           None if "1 active" in s.page.inner_text("#mf-btn") else s.page.inner_text("#mf-btn"))
    tab = s.page.locator("#ph-tabs button", has_text="Speed")
    if tab.count():
        s.step("players: Speed tab", lambda p: tab.first.click(timeout=3000))
        sl = s.page.locator("#ph-sliders [data-group]:not([hidden]) input[type=range]").first
        s.step("players: Top speed minimum to max", lambda p: sl.evaluate(
            "(e) => { e.value = e.max; e.dispatchEvent(new Event('input', {bubbles: true})); "
            "e.dispatchEvent(new Event('change', {bubbles: true})); }"))
        s.note("players: hidden-for-no-data notice is large and plain or absent",
               None if not s.page.locator("#pl-hidden .notice").count()
               or re.search(r"^\d+ hidden: no data for an active metric filter\.$",
                            s.page.inner_text("#pl-hidden .notice").strip()) else s.page.inner_text("#pl-hidden"))
    s.step("players: Reset metric filters", lambda p: p.locator("#mf-reset").click(timeout=3000))
    s.note("players: reset restores the list", None if _rows(s) == n else f"{n} -> {_rows(s)}")


def players_assessed(s, w):
    s.goto("/players?season=318&position=Winger", check=False)
    sw = s.page.get_by_label("Rank on scout-verified rating")
    s.step("players: scout-verified ranking on", lambda p: sw.check(timeout=3000))
    s.note("players: column renamed", None if "Scout-verified rating" in s.page.inner_text("#pl-head") else s.page.inner_text("#pl-head"))
    signed = s.page.get_by_label("Signed-off assessments only")
    s.step("players: signed-off only", lambda p: signed.check(timeout=3000))
    s.step("players: scout-verified ranking off", lambda p: sw.uncheck(timeout=3000))
    s.note("players: signed-off switch hidden again", None if signed.is_hidden() else "visible")


def players_download(s, w):
    s.goto("/players?season=318&position=Winger", check=False)
    link = s.page.locator("#csv")
    href = link.get_attribute("href") or ""
    s.note("players: CSV link carries the filters", None if "position=Winger" in href and "season=318" in href else href)
    got = s.page.evaluate("(h) => fetch(h).then(r => r.text().then(t => [r.status, t.split('\\n')[0]]))", href)
    s.note("players: CSV downloads with today's header", None if got[0] == 200 and got[1].startswith("#,Player,Club,League") else str(got))


def players_history_and_url(s, w):
    """two changes, back x2, forward x2 restore state; the final URL reopens identically."""
    s.goto("/players", check=False)
    pos, sea = s.control("position"), s.control("season")
    if pos is None or sea is None:
        return s.note("players: history", skipped="position / season selects not found")
    states = [s.snapshot()]
    for sel, d in ((pos, "position"), (sea, "season")):
        if _pick_other(s, sel, f"players: history change {d}"):
            states.append(s.snapshot())
    if len(states) < 3:
        return
    for i in (1, 0):
        s.step(f"players: back to state {i}", lambda p: p.go_back())
        s.note(f"players: back restores state {i}", None if s.snapshot() == states[i]
               else f"expected {states[i]}, got {s.snapshot()}")
    for i in (1, 2):
        s.step(f"players: forward to state {i}", lambda p: p.go_forward())
        s.note(f"players: forward restores state {i}", None if s.snapshot() == states[i]
               else f"expected {states[i]}, got {s.snapshot()}")
    url = s.page.url
    other = s.page.context.new_page()
    try:
        from web_check import open_fresh
        got = open_fresh(other, url)
    finally:
        other.close()
    s.note("players: URL is shareable", None if got == states[2]
           else f"{url} reopened as {got}, expected {states[2]}")


# -- Login (not authenticated) ----------------------------------------------------------

def login_scenarios(s):
    """A wrong password is rejected with a visible message and no console errors; the 401 is
    deliberate. Uses a random non-existent username, so no real account is ever locked."""
    s.rec.allow_status = {401, 403, 429}
    s.goto("/login", check=False)
    user = s.page.locator('input[name="username"], input[type="text"]').first
    pw = s.page.locator('input[type="password"]').first

    def bad_login(p):
        user.fill("webcheck_nobody")
        pw.fill("not-the-password-" + str(time.time_ns()))
        p.locator('button[type="submit"], input[type="submit"], form button').first.click()
    s.step("login: wrong password", bad_login, expect_nav=True)
    s.note("login: still on /login after wrong password",
           None if "/login" in urlparse(s.page.url).path else f"ended on {s.page.url}")
    s.note("login: an error message is shown",
           None if re.search(r"invalid|incorrect|wrong|failed|try again", s.page.inner_text("body"), re.I)
           else "no visible error text after a failed login")
    s.rec.allow_status = set()


# -- Player card ---------------------------------------------------------------------------
# One URL per case the card must survive (real local database): a centre forward, a goalkeeper
# (no output tiles, no physical), a 2024/25 row (no physical data), a 2026/27 row, a Leyton
# Orient player (the squad section says "other"), a loanee at Orient, a player with scout
# reports, and one with a long injury record who played in two leagues.
CARD_PLAYERS = [
    ("centre forward", "/player/47357/5/318"),
    ("goalkeeper", "/player/44875/3/318"),
    ("2024/25, no physical data", "/player/39154/5/317"),
    ("2026/27", "/player/47357/5/319"),
    ("Leyton Orient player", "/player/24835/4/318"),
    ("loanee at Orient", "/player/391964/903/318"),
    ("scout reports", "/player/52132/3/318"),
    ("injury record, two leagues", "/player/3581/3/318"),
]


def card_other_players(s, w):
    """Every case above loads clean: no console error, no None/nan, nothing past its card."""
    for label, path in CARD_PLAYERS:
        s.goto(path, check=True, desc=f"card: {label} ({path})")
        s.shot("case_" + re.sub(r"\W+", "_", label), w, full=True)
        body = s.page.inner_text("main")
        s.note(f"card: {label} shows its sections",
               None if all(t in body for t in ("Season by season", "Playing style", "Packing zones",
                                               "Availability and injury record"))
               else "a section heading is missing")


def card_back_link(s, w):
    """The Players page links with ?back=<its URL>: the card's back link returns there, and only
    to a path on this site."""
    base = "/player/39154/5/318"
    s.goto(base + "?back=%2Fplayers%3Fposition%3DWinger%26season%3D318", check=True,
           desc="card: open with ?back=")
    href = s.page.locator("#back").get_attribute("href")
    s.note("card: back link keeps the Players URL",
           None if href == "/players?position=Winger&season=318" else f"href was {href!r}")
    s.note("card: back label names the position",
           None if "Wingers" in s.page.locator("#back").inner_text() else "label has no position")
    s.goto(base + "?back=https%3A%2F%2Fevil.example%2F", check=True, desc="card: off-site ?back=")
    href = s.page.locator("#back").get_attribute("href")
    s.note("card: an off-site ?back= is ignored", None if href == "/players" else f"href was {href!r}")


def card_money_switch(s, w):
    """Affordability on shows market / fair value tiles without a reload; off hides them; the
    choice is in the URL."""
    sw = s.page.locator("#money-sw")
    if not sw.count():
        return s.note("card: affordability switch", skipped="no switch")
    s.step("card: affordability on", lambda p: sw.click(timeout=3000))
    s.note("card: money tiles appear", None if "Market value" in s.page.inner_text("#c-rating")
           or "quality view" in s.page.inner_text("#c-rating") else "no money tiles or note")
    s.note("card: money is in the URL", None if "money=1" in s.page.url else s.page.url)
    s.step("card: affordability off", lambda p: sw.click(timeout=3000))
    s.note("card: money tiles gone", None if "Market value" not in s.page.inner_text("#c-rating")
           else "tiles still shown")


def card_rank_as(s, w):
    sel = s.page.locator("#h-rank")
    if not sel.count() or not sel.is_visible():
        return s.note("card: Rank as", skipped="no Rank as select for this player")
    _pick_other(s, sel, "card: Rank as another lens")
    s.note("card: rank_as is in the URL", None if "rank_as=" in s.page.url else s.page.url)
    s.note("card: lens named in the rating tile",
           None if "Composite (" in s.page.inner_text("#r-tiles") else "tile does not name the lens")


def card_zones(s, w):
    """Packing zones: every metric and every unit redraws the pitch without a request."""
    m = s.page.locator("#pz-m")
    if not m.count() or not m.is_visible():
        return s.note("card: packing zones", skipped="no zone data for this player")
    opts = m.evaluate("e => [...e.options].map(o => o.value)")
    for v in opts[1:4]:
        s.step(f"card: zone metric {v}", lambda p, v=v: m.select_option(value=v, timeout=3000))
    for mode in s.page.locator("#pz-mode button").all():
        label = mode.inner_text()
        s.step(f"card: zone values {label!r}", lambda p, b=mode: b.click(timeout=3000))
    s.note("card: pitch has 11 zones", None if s.page.locator("#pz .zone:not(.gk)").count() == 11
           else "wrong number of zones")


def card_squad_season(s, w):
    """Against our <position>s: both seasons draw, the switch keeps the page, the URL records it."""
    seg = s.page.locator("#sq-seg button")
    if seg.count() < 2:
        return s.note("card: squad season switch", skipped="fewer than two seasons")
    s.step("card: squad season 2", lambda p: seg.nth(1).click(timeout=3000))
    s.note("card: squad season in the URL", None if "sq_season=" in s.page.url else s.page.url)
    s.note("card: squad section drawn", None if "Where he would sit by rating" in s.page.inner_text("#c-squad")
           or "to compare with" in s.page.inner_text("#c-squad")
           or "enough minutes" in s.page.inner_text("#c-squad") else "section empty")
    s.step("card: squad season 1", lambda p: s.page.locator("#sq-seg button").nth(0).click(timeout=3000))


def card_watchlist(s, w):
    """Add then remove (writes the LOCAL database: only with --allow-writes)."""
    if not s.allow_writes:
        return s.note("card: watchlist add / remove", skipped="write control (use --allow-writes)")
    b = s.page.locator("#h-watch")
    s.step("card: add to watchlist", lambda p: b.click(timeout=3000))
    s.note("card: watchlist shows on", None if "On watchlist" in b.inner_text() else b.inner_text())
    s.step("card: remove from watchlist", lambda p: b.click(timeout=3000))
    s.note("card: watchlist shows off", None if "Add to watchlist" in b.inner_text() else b.inner_text())


def radar_behaviour(s, where: str, fig_sel: str):
    """TASKS 2.36 U10, any radar: legend click hides/shows its line; hovering a point shows
    'Metric · value · P72'; zoom in / drag / double-click reset; the chart fills its column."""
    fig = s.page.locator(fig_sel).first
    if not fig.count():
        return s.note(f"{where}: radar", skipped="no radar here")
    fig.scroll_into_view_if_needed(timeout=3000)
    s.page.wait_for_timeout(150)
    key = fig.locator(".rdr-key").first
    line = fig.locator('.rdr-s[data-s="0"]')
    s.step(f"{where}: legend hides the first line", lambda p: key.click(timeout=3000))
    s.note(f"{where}: line hidden after legend click",
           None if line.evaluate("g => getComputedStyle(g).display") == "none"
           and key.get_attribute("aria-pressed") == "false" else "line still drawn")
    s.step(f"{where}: legend shows it again", lambda p: key.click(timeout=3000))
    s.note(f"{where}: line back", None if line.evaluate("g => getComputedStyle(g).display") != "none"
           else "line still hidden")
    sw = fig.locator(".rdr-key svg line").evaluate_all("ls => ls.map(l => l.getAttribute('stroke-dasharray') || '')")
    s.note(f"{where}: legend swatches show solid and dashed styles",
           None if "" in sw and any(sw) else f"swatch dashes {sw}")
    hit = fig.locator(".rdr-hit").first
    hit.hover(timeout=3000, force=True)
    s.page.wait_for_timeout(80)
    tip = s.page.locator(".tip")
    txt = tip.inner_text() if tip.count() and tip.is_visible() else ""
    s.note(f"{where}: hover shows the value", None if re.search(r"· P\d+", txt) else f"tooltip {txt!r}")
    svg = fig.locator(".rdr-svg")
    s.step(f"{where}: zoom in", lambda p: fig.locator('[data-z="in"]').click(timeout=3000, force=True))
    s.page.wait_for_timeout(250)
    zoomed = lambda: svg.evaluate("e => e.getAttribute('viewBox') !== e.dataset.vb")
    s.note(f"{where}: zoomed", None if zoomed() else "viewBox unchanged")
    box = svg.bounding_box()
    if box:
        s.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        s.page.mouse.down(); s.page.mouse.move(box["x"] + box["width"] / 2 + 60, box["y"] + box["height"] / 2 + 30, steps=4)
        s.page.mouse.up()
    s.step(f"{where}: double-click resets", lambda p: fig.locator(".rdr-stage").dblclick(timeout=3000))
    s.page.wait_for_timeout(250)
    s.note(f"{where}: zoom reset", None if not zoomed() else "still zoomed")
    fw, cw = fig.evaluate("f => [f.getBoundingClientRect().width, f.querySelector('.rdr-svg').getBoundingClientRect().width]")
    s.note(f"{where}: radar fills its column", None if cw >= fw * 0.85 else f"chart {cw:.0f}px of {fw:.0f}px")


def card_radars(s, w):
    radar_behaviour(s, "card performance radar", "#pp .rdr")
    radar_behaviour(s, "card physical radar", "#prad .rdr")
    _radar_scroll(s, "card")


def card_rated_tables(s, w):
    """U13 weight groups and U15 'vs ours' in the rated tables; U1 zone hover percentile."""
    heads = s.page.locator("#pr tr.sec.wt").all_inner_texts()
    s.note("card: performance rows grouped by weight",
           None if heads and all(h.strip().upper().endswith("WEIGHT") for h in heads) else f"headings {heads}")
    th = s.page.locator('#pr th.col-vs-ours')
    s.note("card: 'vs ours' column with its median in the tooltip",
           None if th.count() and "median" in (th.get_attribute("data-tip") or "") else "no vs ours column")
    s.note("card: no browser title tooltips on headings",
           None if s.page.locator("main th[title]").count() == 0 else "a heading still uses title")
    cells = s.page.locator("#pr .vs").all_inner_texts()
    s.note("card: 'vs ours' cells are whole signed points",
           None if cells and all(re.fullmatch(r"[+−]\d+|0|—", c.strip()) for c in cells) else f"cells {cells[:5]}")
    z = s.page.locator("#pz .zone[data-tip]").first
    if z.count():
        z.scroll_into_view_if_needed(timeout=3000)
        s.page.wait_for_timeout(150)
        z.hover(timeout=3000)
        s.page.wait_for_timeout(80)
        tip = s.page.locator(".tip")
        txt = tip.inner_text() if tip.count() and tip.is_visible() else ""
        s.note("card: packing zone hover shows the percentile",
               None if "percentile" in txt else f"tooltip {txt!r}")


COMPARE_CROSS = "/compare?season=318&position=Winger&a=39154-5&b=24835-4"


def compare_radars(s, w):
    s.goto("/compare?season=318&position=Winger&a=39154-5&b=150216-5&c=47739-5", check=True,
           desc="compare: three players for the radar")
    radar_behaviour(s, "compare performance radar", "#prad .rdr")
    _radar_scroll(s, "compare, three players")
    s.goto(COMPARE_CROSS, check=True, desc="compare: players from different leagues")
    _radar_scroll(s, "compare, different leagues")
    s.shot("radar_notes", w)


def report_radar(s, w):
    s.goto(REPORT_BASE, check=True, desc="report: radar")
    radar_behaviour(s, "report physical radar", "#p-radar .rdr")
    _radar_scroll(s, "report")


def home_first_view(s, w):
    """U7: the home page has the club crest and a link to every page in use."""
    s.note("home: crest shown", None if s.page.locator(".hero-logo").is_visible() else "no crest")
    s.note("home: page links", None if s.page.locator(".tiles-home a.hl").count() >= 5 else "too few links")
    s.shot("first_view", w)


# -- Report ---------------------------------------------------------------------------------
# Real local database. A winger, a thin peer pool (8 Scottish Premiership attacking mids in
# 2026/27: no composite, "Not rated: only 8 ..."), a goalkeeper (no playing style), a Leyton
# Orient player (Orient median line), a 2026/27 centre forward.
REPORT_BASE = "/report?player=39154&competition=5&season=318"
REPORT_CASES = [
    ("winger", REPORT_BASE),
    ("thin pool", "/report?player=2000030124&competition=901&season=319"),
    ("goalkeeper", "/report?player=44875&competition=3&season=318"),
    ("Leyton Orient player", "/report?player=24835&competition=4&season=318"),
    ("2026/27 centre forward", "/report?player=47357&competition=5&season=319"),
]


def _report_ready(s):
    try:
        s.page.locator("#rp-body:not([hidden])").wait_for(timeout=6000)
        return True
    except Exception:
        return False


def report_empty_state(s, w):
    """No player chosen: one line saying what to do, nothing else drawn."""
    s.goto("/report", check=True, desc="report: no player chosen")
    s.note("report: empty state asks for a search",
           None if "Search for a player" in s.page.inner_text("#rp-status") else s.page.inner_text("#rp-status"))
    s.note("report: no report drawn", None if s.page.locator("#rp-body").is_hidden() else "body shown")


def report_cases(s, w):
    """Every case loads clean (no console error, no None/nan, nothing past its card) with its
    sections, and the thin pool shows no composite."""
    for label, path in REPORT_CASES:
        s.goto(path, check=True, desc=f"report: {label}")
        if not _report_ready(s):
            s.note(f"report: {label} draws", "report body never shown: " + s.page.inner_text("#rp-status"))
            continue
        s.shot("case_" + re.sub(r"\W+", "_", label), w, full=True)
        body = s.page.inner_text("main")
        s.note(f"report: {label} has its sections",
               None if all(t in body for t in ("Composite", "Summary", "Technical", "Physical", "Availability"))
               else "a section heading is missing")
        bars = s.page.locator("#t-bars .rp-bar")
        if bars.count():
            h = bars.first.bounding_box()["height"]
            s.note(f"report: {label} bars have vertical room", None if h >= 30 else f"bar row {h:.0f}px")
        if label == "thin pool":
            v = s.page.inner_text("#c-verdict")
            s.note("report: thin pool shows the not-rated note and no composite",
                   None if "Not rated: only" in v and not s.page.locator("#c-verdict .rp-composite").count()
                   else v[:120])
            s.note("report: thin pool headings name the pool size",
                   None if re.search(r"Percentile vs \d+ ", s.page.inner_text("#t-sub")) else s.page.inner_text("#t-sub"))
        if label == "goalkeeper":
            s.note("report: goalkeeper has no playing style", None if s.page.locator("#c-style").is_hidden() else "style shown")


def report_search_pick(s, w):
    """Search reaches any position and league; picking a result draws his report in place and
    puts him in the URL."""
    s.goto("/report", check=False)
    box = s.control("Find a player", "text")
    if box is None:
        return s.note("report: search", skipped="no search box")
    s.step("report: search", lambda p: box.fill("Markanday", timeout=3000))
    res = s.page.locator("#rp-results [data-action=pick]")
    try:
        res.first.wait_for(timeout=4000)
    except Exception:
        return s.note("report: search", "no result for 'Markanday'")
    s.step("report: pick a result", lambda p: res.first.click(timeout=3000))
    s.note("report: report drawn", None if _report_ready(s) else "report not drawn")
    s.note("report: player in the URL", None if "player=39154" in s.page.url else s.page.url)
    s.step("report: search nothing", lambda p: box.fill("zzzz-no-such-player", timeout=3000))
    try:
        s.page.locator("#rp-results .none").wait_for(timeout=3000)
        s.note("report: no-match message", None)
    except Exception:
        s.note("report: no-match message", "no message")
    clear = s.page.locator("#rp-clear")
    s.step("report: clear search", lambda p: clear.click(timeout=3000))
    s.note("report: clear empties the box", None if box.input_value() == "" else box.input_value())


def report_form_live(s, w):
    """Write your report: typing changes the stamp and the Summary; a Psychological score
    changes the band; nothing reloads."""
    s.goto(REPORT_BASE, check=False)
    _report_ready(s)
    s.step("report: open the form", lambda p: p.locator("#rp-write").click(timeout=3000))
    ta = s.page.locator('#f-text textarea[data-key="summary"]')
    if not ta.count():
        return s.note("report: form", "no Summary box")
    s.step("report: type a summary", lambda p: (ta.fill("Quick, brave, presses well.", timeout=3000),
                                                 p.wait_for_timeout(400)))
    s.note("report: stamp names the author", None if "Report by" in s.page.inner_text("#h-stamp") else s.page.inner_text("#h-stamp"))
    s.note("report: summary shows the text", None if "Quick, brave" in s.page.inner_text("#c-summary") else "summary not updated")
    sel = s.page.locator("#f-psych select").first
    if sel.count():
        s.step("report: score a Psychological criterion", lambda p: (sel.select_option(value="4", timeout=3000),
                                                                     p.wait_for_timeout(300)))
        s.note("report: band caption", None if "Band: 4.00" in s.page.inner_text("#f-psych-band") else s.page.inner_text("#f-psych-band"))
        s.note("report: Psychological tile shows the score", None if "4.00" in s.page.inner_text("#c-verdict") else "not shown")
    radio = s.page.locator("#f-med input[type=radio][value='Meets']").first
    if radio.count():
        s.step("report: answer a medical check", lambda p: (radio.check(timeout=3000), p.wait_for_timeout(300)))
        s.note("report: medical checks line", None if "Medical checks" in s.page.inner_text("#c-verdict") else "no line")
    s.shot("form_open", w, full=True)
    s.step("report: clear the summary", lambda p: (ta.fill("", timeout=3000), p.wait_for_timeout(400)))


def report_downloads(s, w):
    """Both downloads come back as the report document, named for the player and season."""
    s.goto(REPORT_BASE, check=False)
    _report_ready(s)
    href = s.page.locator("#rp-dl-data").get_attribute("href") or ""
    got = s.page.evaluate("(h) => fetch(h).then(r => r.text().then(t => [r.status, r.headers.get('content-disposition') || '', t.slice(0, 15), t.includes('Data only')]))", href)
    s.note("report: data-only download", None if got[0] == 200 and "data_only_report.html" in got[1]
           and got[2].lower().startswith("<!doctype") and got[3] else str(got)[:160])
    try:
        with s.page.expect_download(timeout=5000) as dl:
            s.step("report: Download report", lambda p: p.locator("#rp-dl").click(timeout=3000))
        name = dl.value.suggested_filename
        s.note("report: download is named for the player", None if name.endswith("_report.html") and "Markanday" in name else name)
    except Exception as e:
        s.note("report: Download report", f"no download: {str(e).splitlines()[0][:100]}")


def report_season_switch(s, w):
    """Season switch keeps the page and the player, and is in the URL."""
    s.goto(REPORT_BASE, check=False)
    _report_ready(s)
    sel = s.control("Season")
    if sel is None:
        return s.note("report: season", skipped="no Season select")
    s.step("report: season 2026/27", lambda p: sel.select_option(value="319", timeout=3000))
    s.note("report: season in the URL", None if "season=319" in s.page.url else s.page.url)
    s.note("report: same player, other season",
           None if "Markanday" in s.page.inner_text("#h-name") or "No report" in s.page.inner_text("#rp-status")
           else "neither his report nor a message")


def report_history_and_url(s, w):
    """Two players, back and forward between them; the URL reopens the same report."""
    s.goto(REPORT_BASE, check=False)
    _report_ready(s)
    box = s.control("Find a player", "text")
    s.step("report: search another player", lambda p: box.fill("Nygren", timeout=3000))
    res = s.page.locator("#rp-results [data-action=pick]")
    try:
        res.first.wait_for(timeout=4000)
    except Exception:
        return s.note("report: history", skipped="no result for 'Nygren'")
    s.step("report: open him", lambda p: res.first.click(timeout=3000))
    second = s.page.url
    name2 = s.page.inner_text("#h-name")
    s.step("report: back", lambda p: p.go_back())
    s.note("report: back shows the first player", None if "Markanday" in s.page.inner_text("#h-name") else s.page.inner_text("#h-name"))
    s.step("report: forward", lambda p: p.go_forward())
    s.note("report: forward shows the second player", None if s.page.inner_text("#h-name") == name2 else s.page.inner_text("#h-name"))
    fresh = s.page.context.new_page()
    try:
        fresh.goto(second, wait_until="load")
        fresh.locator("#rp-body:not([hidden])").wait_for(timeout=6000)
        s.note("report: shareable URL reopens the same report",
               None if fresh.inner_text("#h-name") == name2 else fresh.inner_text("#h-name"))
    except Exception as e:
        s.note("report: shareable URL reopens the same report", str(e).splitlines()[0][:100])
    finally:
        fresh.close()


def report_layout_widths(s, w):
    """With the form open, nothing overflows at any width."""
    for width in s.widths:
        s.page.set_viewport_size({"width": width, "height": 900})
        s.goto(REPORT_BASE, check=True, desc=f"report: layout @{width}")
        _report_ready(s)
        s.step(f"report: form open @{width}", lambda p: p.locator("#rp-write").click(timeout=3000))
        s.shot("form_layout", width, full=True)
    s.page.set_viewport_size({"width": w, "height": 900})



# -- Compare -------------------------------------------------------------------------------
CMP3 = "/compare?season=318&position=Winger&a=39154-5&b=150216-5&c=47739-5"


def _cmp_heads(s):
    return [t.strip() for t in s.page.locator("#cmp-sum thead a.nm").all_inner_texts()]


def compare_three_players_every_width(s, w):
    """Three wingers at 1280 / 1440 / 1920: every section draws, nothing overflows."""
    for width in s.widths:
        s.page.set_viewport_size({"width": width, "height": 900})
        s.goto(CMP3, check=True, desc=f"compare: three players @{width}")
        s.shot("three", width, full=True)
        body = s.page.inner_text("main")
        s.note(f"compare: every section @{width}", None if all(t in body for t in (
            "Composite", "Performance profile", "Physical profile", "Performance · in the rating",
            "Physical · in the rating", "Packing zones")) else "a section is missing")
    s.page.set_viewport_size({"width": w, "height": 900})
    s.note("compare: three name columns", None if len(_cmp_heads(s)) == 3 else _cmp_heads(s))


def compare_defaults_fill_the_url(s, w):
    """A bare /compare opens two players and writes them into the URL (shareable)."""
    s.goto("/compare?season=318&position=Winger", check=True, desc="compare: defaults")
    s.note("compare: two defaults", None if len(_cmp_heads(s)) == 2 else _cmp_heads(s))
    s.note("compare: defaults in the URL", None if re.search(r"[?&]a=\d+-\d+.*&b=\d+-\d+", s.page.url)
           else s.page.url)


def compare_position_season_back_forward(s, w):
    """position -> season, then back x2 / forward x2 restore the state; the URL reopens it."""
    s.goto("/compare?season=318&position=Winger", check=False)
    pos, sea = _need(s, "position"), _need(s, "season")
    if pos is None or sea is None:
        return
    states = [s.snapshot()]
    s.step("compare: position = Centre Back", lambda p: pos.select_option(value="Centre Back", timeout=3000))
    states.append(s.snapshot())
    s.note("compare: position change picks two Centre Backs",
           None if "Centre Back" in s.page.inner_text("#cmp-title") and len(_cmp_heads(s)) == 2 else s.page.inner_text("#cmp-title"))
    _pick_other(s, sea, "compare: change season")
    states.append(s.snapshot())
    for i in (1, 0):
        s.step(f"compare: back to state {i}", lambda p: p.go_back())
        s.note(f"compare: back restores state {i}", None if s.snapshot() == states[i]
               else f"expected {states[i]}, got {s.snapshot()}")
    for i in (1, 2):
        s.step(f"compare: forward to state {i}", lambda p: p.go_forward())
        s.note(f"compare: forward restores state {i}", None if s.snapshot() == states[i]
               else f"expected {states[i]}, got {s.snapshot()}")
    other = s.page.context.new_page()
    try:
        from web_check import open_fresh
        got = open_fresh(other, s.page.url)
    finally:
        other.close()
    s.note("compare: URL is shareable", None if got == states[2] else f"reopened as {got}")


def compare_pick_from_pool_list(s, w):
    """Focusing a slot lists the ranked pool; clicking one puts him in that slot."""
    s.goto("/compare?season=318&position=Winger", check=False)
    box = s.page.locator("#slot-b")
    s.step("compare: open Player B list", lambda p: box.click(timeout=3000))
    items = s.page.locator("#res-b [data-action=pick]")
    if items.count() < 4:
        return s.note("compare: pool list", skipped="fewer than 4 players listed")
    target = items.nth(3)
    name = target.inner_text().split(" — ")[0].strip()
    s.step("compare: pick the 4th player into B", lambda p: target.click(timeout=3000))
    s.note("compare: B is the picked player", None if name in _cmp_heads(s)[1] else f"{name} vs {_cmp_heads(s)}")


def compare_search_this_position_only(s, w):
    """C5 (owner 2026-11-09): search in Player C lists only Wingers; a pick keeps the position
    and the other two slots."""
    s.goto(CMP3, check=False)
    heads = _cmp_heads(s)
    box = s.page.locator("#slot-c")
    s.step("compare: type in Player C", lambda p: (box.click(timeout=3000), box.fill("son", timeout=3000)))
    res = s.page.locator("#res-c [data-action=pick]")
    try:
        s.page.wait_for_function("() => document.querySelectorAll('#res-c [data-action=pick]').length > 1", timeout=5000)
    except Exception:
        return s.note("compare: search this position", skipped="no result for 'son'")
    texts = [t for t in res.all_inner_texts() if "none" not in t]
    bad = [t for t in texts if "Winger" not in t]
    s.note("compare: search lists Wingers only", None if texts and not bad else f"other positions: {bad[:3]}")
    i = next((k for k, t in enumerate(res.all_inner_texts()) if "Winger" in t and t.split(" · ")[0] not in " ".join(heads[:2])), None)
    if i is None:
        return s.note("compare: pick from search", skipped="no other winger listed")
    s.step("compare: pick a winger into C", lambda p: res.nth(i).click(timeout=3000))
    s.note("compare: position kept", None if "Winger" in s.page.inner_text("#cmp-title") else s.page.inner_text("#cmp-title"))
    s.note("compare: A and B kept", None if _cmp_heads(s)[:2] == heads[:2] else f"{heads} -> {_cmp_heads(s)}")


def compare_none_in_c(s, w):
    s.goto(CMP3, check=False)
    box = s.page.locator("#slot-c")
    s.step("compare: open Player C list", lambda p: box.click(timeout=3000))
    none = s.page.locator("#res-c [data-action=pick]").first
    s.step("compare: Player C = none", lambda p: none.click(timeout=3000))
    s.note("compare: two players left", None if len(_cmp_heads(s)) == 2 else _cmp_heads(s))
    s.note("compare: c gone from the URL", None if "&c=" not in s.page.url and "?c=" not in s.page.url else s.page.url)


def compare_name_opens_card(s, w):
    s.goto(CMP3, check=False)
    link = s.page.locator("#cmp-sum thead a.nm").first
    _go_card(s, "compare: a name opens his card with a way back", lambda: link.click(timeout=3000))
    s.note("compare: back link returns to Compare", None if "back=%2Fcompare" in s.page.url else s.page.url)
    s.step("compare: browser back", lambda p: p.go_back(), expect_nav=True)
    s.note("compare: same players after back", None if len(_cmp_heads(s)) == 3 else _cmp_heads(s))


def compare_zones_and_money(s, w):
    s.goto(CMP3, check=False)
    m = s.page.locator("#pz-m")
    if m.count() and m.is_visible():
        for v in m.evaluate("e => [...e.options].map(o => o.value)")[1:4]:
            s.step(f"compare: zone measure {v}", lambda p, v=v: m.select_option(value=v, timeout=3000))
        s.note("compare: one pitch per player", None if s.page.locator("#pz .pitch").count() == 3
               else f"{s.page.locator('#pz .pitch').count()} pitches")
    else:
        s.note("compare: packing zones", skipped="no zone data")
    sw = s.page.get_by_label("Market value")
    s.step("compare: Market value on", lambda p: sw.check(timeout=3000))
    s.note("compare: Market row shown", None if "Market (€m)" in s.page.inner_text("#cmp-sum") else "no Market row")
    s.step("compare: Market value off", lambda p: sw.uncheck(timeout=3000))


def compare_special_cases(s, w):
    """Goalkeepers (no physical), a 2024/25 pair (no physical data), a thin-pool player
    (no composite, 'vs N' in the headings) and a league filter all draw cleanly."""
    for label, path, want in (
        ("goalkeepers", "/compare?season=318&position=Goalkeeper&a=66767-3&b=6423-4", "Performance profile"),
        ("2024/25", "/compare?season=317&position=Winger&a=142372-903&b=36385-901", "Performance profile"),
        ("thin pool", "/compare?season=319&position=Attacking%20Mid&a=2000030124-901", "Not rated: only"),
        ("league filter", "/compare?season=318&position=Centre%20Back&leagues=Championship&leagues=National%20League",
         "Performance profile")):
        s.goto(path, check=True, desc=f"compare: {label}")
        s.shot("case_" + re.sub(r"\W+", "_", label), w, full=True)
        s.note(f"compare: {label} draws", None if want in s.page.inner_text("main") else f"no {want!r}")
        if label == "goalkeepers":
            s.note("compare: goalkeepers have no Physical profile",
                   None if not s.page.locator("#c-phrad").is_visible() else "Physical profile shown")


def compare_more_filters(s, w):
    """C4: More filters narrow the list a picker shows, live in the URL, and reopen from it;
    typing a name still searches everyone."""
    s.goto("/compare?season=318&position=Winger", check=False)

    def listed():
        box = s.page.locator("#slot-b")
        box.click(timeout=3000)
        s.page.locator("#res-b [data-action=pick]").first.wait_for(timeout=4000)
        n = s.page.locator("#res-b [data-action=pick]").count()
        s.page.keyboard.press("Escape")
        return n
    before = listed()
    b = s.page.get_by_role("button", name=re.compile("More filters", re.I)).first
    s.step("compare: open More filters", lambda p: b.click(timeout=3000))
    foot = _need(s, "Preferred foot")
    if foot is None:
        return
    s.step("compare: foot = Left", lambda p: foot.select_option(value="Left", timeout=3000))
    age = s.page.locator("#f-age")
    s.step("compare: max age = 24", lambda p: age.evaluate(
        "e => { e.value = 24; e.dispatchEvent(new Event('change', {bubbles: true})); }"))
    s.note("compare: filters in the URL", None if "foot=Left" in s.page.url and "max_age=24" in s.page.url else s.page.url)
    s.note("compare: button counts them", None if "2 active" in b.inner_text() else b.inner_text())
    after = listed()
    s.note("compare: the picker list is narrowed", None if 0 < after < before else f"{before} -> {after}")
    box = s.page.locator("#slot-c")
    s.step("compare: type a name in Player C", lambda p: (box.click(timeout=3000), box.fill("son", timeout=3000)))
    try:
        s.page.wait_for_function("() => document.querySelectorAll('#res-c [data-action=pick]').length > 1", timeout=5000)
        typed = len([t for t in s.page.locator("#res-c [data-action=pick]").all_inner_texts() if "none" not in t])
        s.note("compare: typing searches past the filters", None if typed > 0 else "no results")
    except Exception:
        s.note("compare: typing searches past the filters", skipped="no result for 'son'")
    s.page.keyboard.press("Escape")
    fresh = s.page.context.new_page()
    try:
        fresh.goto(s.page.url, wait_until="load")
        fresh.locator("#cmp-body:not([hidden])").wait_for(timeout=6000)
        ok = fresh.locator("#f-foot").input_value() == "Left" and fresh.locator("#more").is_visible()
        s.note("compare: URL reopens with the filters shown", None if ok else "filters lost")
    except Exception as e:
        s.note("compare: URL reopens with the filters shown", str(e).splitlines()[0][:100])
    finally:
        fresh.close()


# -- Squads & loans ------------------------------------------------------------------------
SQ_ORIENT = "/squads?league=League+One&club=Leyton+Orient"


def _sq_rows(s):
    """Rows in the list (the table draws them in pages as it scrolls; the total is on tbody)."""
    t = s.page.locator("#sq-body").get_attribute("data-total")
    return int(t) if t and t.isdigit() else 0


def squads_scroll_draws_more(s, w):
    """The full list draws its first rows, then the next ones as the table scrolls."""
    s.goto("/squads", check=False)
    first = s.page.locator("#sq-body tr.click").count()
    s.step("squads: scroll the table to the end", lambda p: p.locator("#tw").evaluate(
        "e => { e.scrollTop = e.scrollHeight; }"))
    after = s.page.locator("#sq-body tr.click").count()
    s.note("squads: scrolling draws more rows", None if 0 < first < after <= _sq_rows(s) else f"{first} -> {after}")


def _sq_tile(s, label):
    """A tile's value as an int (the tiles say "3,783")."""
    for t in s.page.locator("#sq-tiles .tile").all():
        if t.locator(".k").inner_text().strip() == label:
            return int(t.locator(".v").inner_text().replace(",", "") or 0)
    return None


def squads_exercise_controls(s, w):
    """The generic exerciser over every filter control; the ~3,800 rows are left to the
    scenarios below (each click leaves the page for the card)."""
    g = s.exercise.__globals__
    orig = g["sample_controls"]
    g["sample_controls"] = lambda cs, **kw: orig([c for c in cs if c["kind"] != "row"], **kw)
    try:
        s.exercise("/squads?league=League+Two")
    finally:
        g["sample_controls"] = orig


def squads_first_view(s, w):
    """Opens on every squad: tiles = rows, the table is visible without scrolling."""
    s.goto("/squads", check=False)
    n = _sq_rows(s)
    s.note("squads: Players tile = rows drawn", None if n and _sq_tile(s, "Players") == n
           else f"tile {_sq_tile(s, 'Players')} vs {n} rows")
    first = s.page.locator("#sq-body tr.click").first
    box = first.bounding_box() if first.count() else None
    s.note("squads: first row inside the 1440x900 viewport",
           None if box and box["y"] + box["height"] <= 900 else f"first row box {box}")
    heads = s.page.inner_text("#sq-head")
    s.note("squads: Composite columns named", None if heads.count("Composite") >= 2 else heads)


def squads_layout_widths(s, w):
    """Nothing overflows with More filters open at every width (Orient's squad and all)."""
    for width in s.widths:
        s.page.set_viewport_size({"width": width, "height": 900})
        s.goto("/squads?max_age=30", check=True, desc=f"squads: layout, more filters @{width}")
        s.shot("filters_open", width)
        s.goto(SQ_ORIENT, check=True, desc=f"squads: Leyton Orient @{width}")
        s.shot("orient", width)
    s.page.set_viewport_size({"width": w, "height": 900})


def squads_league_club_open_back(s, w):
    """League -> Club -> open a player -> the card's back link and browser back both return
    to the same filters."""
    s.goto("/squads", check=False)
    lg, cl = _need(s, "league"), _need(s, "club")
    if lg is None or cl is None:
        return
    s.step("squads: League = League One", lambda p: lg.select_option(value="League One", timeout=3000))
    s.step("squads: Club = Leyton Orient", lambda p: cl.select_option(value="Leyton Orient", timeout=3000))
    s.note("squads: Orient's squad (33 on 7 Sep 2026)", None if _sq_tile(s, "Players") == _sq_rows(s) > 20
           else f"{_sq_tile(s, 'Players')} players")
    snap = s.snapshot()
    row = s.page.locator("#sq-body tr[data-href]").first
    if not row.count():
        return s.note("squads: open a player", skipped="no linked row")
    _go_card(s, "squads: row opens the player card with a way back", lambda: row.click(timeout=3000))
    back = s.page.locator("#back")
    s.note("squads: back link names Squads & loans",
           None if "Squads & loans" in back.inner_text() else back.inner_text())
    s.note("squads: back link keeps the filters",
           None if (back.get_attribute("href") or "").startswith("/squads?") and "Leyton" in back.get_attribute("href")
           else back.get_attribute("href"))
    s.step("squads: browser back", lambda p: p.go_back(), expect_nav=True)
    s.note("squads: back restores filters", None if s.snapshot() == snap else f"before {snap} / after {s.snapshot()}")
    s.goto(SQ_ORIENT, check=False)
    row = s.page.locator("#sq-body tr[data-href]").first
    _go_card(s, "squads: open again", lambda: row.click(timeout=3000))
    s.step("squads: click ← Back", lambda p: p.locator("#back").click(timeout=3000), expect_nav=True)
    s.page.wait_for_url(re.compile(r"/squads\?"), timeout=6000)
    s.note("squads: ← Back lands on the same squad", None if "Leyton" in s.page.url and _sq_rows(s) > 20 else s.page.url)


def squads_show(s, w):
    """Show: On loan only (every loan; tiles agree), Contract expiring, back to Everyone."""
    s.goto("/squads", check=False)
    everyone = _sq_rows(s)
    s.step("squads: Show = On loan only", lambda p: p.locator("#f-show [data-show=loan]").click(timeout=3000))
    n = _sq_rows(s)
    s.note("squads: loans view, every row on loan", None if n and _sq_tile(s, "On loan") == n == _sq_tile(s, "Players")
           else f"rows {n}, tiles {_sq_tile(s, 'Players')}/{_sq_tile(s, 'On loan')}")
    s.note("squads: show=loan in the URL", None if "show=loan" in s.page.url else s.page.url)
    s.step("squads: Show = Contract expiring", lambda p: p.locator("#f-show [data-show=expiring]").click(timeout=3000))
    n = _sq_rows(s)
    s.note("squads: expiring view, every row expiring", None if n and _sq_tile(s, "Expiring < 12 months") == n
           else f"rows {n}")
    s.step("squads: Show = Everyone", lambda p: p.locator("#f-show [data-show='']").click(timeout=3000))
    s.note("squads: Everyone restores the list", None if _sq_rows(s) == everyone else f"{everyone} -> {_sq_rows(s)}")


def squads_more_filters(s, w):
    """The sidebar filters on the page: each narrows the list, shows in the URL and in the
    More filters count; Leagues untick + one league; All leagues resets."""
    s.goto("/squads", check=False)
    _fold(s, "more filters")
    base = _sq_rows(s)
    for label, value in (("foot", "Left"), ("contract", "Out of contract summer 2027"), ("loan", "On loan now")):
        c = _need(s, label)
        if c is None:
            continue
        s.step(f"squads: {label} = {value}", lambda p, c=c, v=value: c.select_option(value=v, timeout=3000))
        s.note(f"squads: {label} narrows the list", None if 0 < _sq_rows(s) < base else f"{base} -> {_sq_rows(s)}")
        s.step(f"squads: {label} = Any", lambda p, c=c: c.select_option(value="Any", timeout=3000))
    age = s.page.locator("#f-age")
    s.step("squads: Maximum age 21", lambda p: age.evaluate(
        "e => { e.value = 21; e.dispatchEvent(new Event('change', {bubbles: true})); }"))
    s.note("squads: max_age in the URL and the More count", None if "max_age=21" in s.page.url
           and "(1)" in s.page.inner_text("#more-btn") else f"{s.page.url} / {s.page.inner_text('#more-btn')}")
    s.step("squads: open Leagues", lambda p: p.locator("#leagues-btn").click(timeout=3000))
    s.step("squads: untick all leagues", lambda p: p.locator("#leagues-none").click(timeout=3000))
    s.step("squads: tick League Two", lambda p: p.locator("#leagues-list input[value='League Two']").check(timeout=3000))
    opts = s.page.locator("#f-league option").all_inner_texts()
    s.note("squads: League list holds only what the sidebar kept", None if opts == ["All", "League Two"] else str(opts))
    s.step("squads: All leagues", lambda p: p.locator("#leagues-all").click(timeout=3000))
    s.note("squads: leagues gone from the URL", None if "leagues=" not in s.page.url else s.page.url)


def squads_row_message(s, w):
    """A squad member with no profile to open: the click says why, in place, no navigation."""
    s.goto("/squads?league=League+Two", check=False)
    row = s.page.locator("#sq-body tr[data-row]").first
    if not row.count():
        return s.note("squads: no-profile row", skipped="every row has a profile")
    s.step("squads: click a row with no profile", lambda p: row.click(timeout=3000))
    msg = s.page.inner_text("#sq-click")
    s.note("squads: the click says why", None if "no profile to open" in msg else repr(msg))


def squads_thin_and_sort(s, w):
    """A composite from a thin peer pool is withheld with the note; a header click sorts on
    the server (asc, desc, off)."""
    s.goto("/squads", check=False)
    # the note is the instant tooltip (data-tip) since 2.36; a title would be the old browser tip
    thin = s.page.locator("#sq-body span[data-tip^='Not rated: only']")
    for _ in range(20):                      # rows are drawn as the table scrolls
        if thin.count() or not s.page.locator("#sq-body tr.sentinel").count():
            break
        s.page.locator("#tw").evaluate("e => { e.scrollTop = e.scrollHeight; }")
        s.page.wait_for_timeout(150)
    s.note("squads: thin-pool composite withheld with the note",
           None if thin.count() and re.fullmatch(r"Not rated: only \d+ comparable players \(needs 10\)",
                                                 thin.first.get_attribute("data-tip")) else "no withheld composite found")
    head = s.page.locator("#sq-head [data-sort='Minutes']")
    s.step("squads: sort by Minutes (asc)", lambda p: head.click(timeout=3000))
    s.note("squads: sort in the URL", None if "sort=Minutes" in s.page.url and "dir=asc" in s.page.url else s.page.url)
    s.step("squads: sort by Minutes (desc)", lambda p: s.page.locator("#sq-head [data-sort='Minutes']").click(timeout=3000))
    first = s.page.locator("#sq-body tr").first.locator("td").nth(4).inner_text()
    s.note("squads: most minutes first", None if first.replace(",", "").isdigit() and int(first.replace(",", "")) > 500 else first)
    s.step("squads: sort off", lambda p: s.page.locator("#sq-head [data-sort='Minutes']").click(timeout=3000))
    s.note("squads: sort gone from the URL", None if "sort=" not in s.page.url else s.page.url)


def squads_search(s, w):
    """Player search narrows in place (accent / case-insensitive, on the server)."""
    s.goto("/squads", check=False)
    box = _need(s, "player", "text")
    if box is None:
        return
    s.step("squads: search 'smith'", lambda p: (box.fill("smith"), box.press("Enter")))
    names = s.page.locator("#sq-body td.pname").all_inner_texts()
    s.note("squads: every row matches", None if names and all("smith" in n.lower() for n in names) else str(names[:5]))
    s.note("squads: q in the URL", None if "q=smith" in s.page.url else s.page.url)


def squads_download(s, w):
    s.goto(SQ_ORIENT, check=False)
    link = s.page.locator("#csv")
    href = link.get_attribute("href") or ""
    s.note("squads: CSV link carries the filters", None if "club=Leyton" in href else href)
    got = s.page.evaluate("(h) => fetch(h).then(r => r.text().then(t => [r.status, t.split('\\n')[0], "
                          "r.headers.get('content-disposition')]))", href)
    s.note("squads: CSV is Streamlit's file", None if got[0] == 200 and got[1].startswith("Club,Player,Position,Age")
           and "lofc_squads_leyton_orient.csv" in (got[2] or "") else str(got))


def squads_history_and_url(s, w):
    """Two changes, back x2, forward x2 restore state; the final URL reopens identically."""
    s.goto("/squads", check=False)
    lg = _need(s, "league")
    if lg is None:
        return
    states = [s.snapshot()]
    s.step("squads: history League = League Two", lambda p: lg.select_option(value="League Two", timeout=3000))
    states.append(s.snapshot())
    s.step("squads: history Show = On loan only", lambda p: p.locator("#f-show [data-show=loan]").click(timeout=3000))
    states.append(s.snapshot())
    for i in (1, 0):
        s.step(f"squads: back to state {i}", lambda p: p.go_back())
        s.note(f"squads: back restores state {i}", None if s.snapshot() == states[i]
               else f"expected {states[i]}, got {s.snapshot()}")
    for i in (1, 2):
        s.step(f"squads: forward to state {i}", lambda p: p.go_forward())
        s.note(f"squads: forward restores state {i}", None if s.snapshot() == states[i]
               else f"expected {states[i]}, got {s.snapshot()}")
    url = s.page.url
    other = s.page.context.new_page()
    try:
        from web_check import open_fresh
        got = open_fresh(other, url)
    finally:
        other.close()
    s.note("squads: URL is shareable", None if got == states[2] else f"{url} reopened as {got}, expected {states[2]}")


# -- Scout reports --------------------------------------------------------------------------
# Real local database. Floyd Samba (Scottish Championship centre mid, 2025/26): a pool of 8, so
# his 2025/26 rating is withheld on the web page.
SR_PATH = "/scout-reports"


def _sr_rows(s):
    return s.page.locator("#sr-body tr[data-row]")


def _sr_ready(s):
    try:
        s.page.locator("#sr-main:not([hidden])").wait_for(timeout=6000)
        return True
    except Exception:
        return False


def scout_first_view(s, w):
    """Sync line, three tabs, the filters and the table; Refresh is never pressed."""
    s.goto(SR_PATH, check=True, desc="scout reports: first view")
    if not _sr_ready(s):
        return s.note("scout reports: page draws", "main never shown: " + s.page.inner_text("main")[:120])
    s.note("scout reports: sync line", None if re.search(r"synced", s.page.inner_text("#sr-sync"), re.I)
           else s.page.inner_text("#sr-sync"))
    tabs = s.page.locator("#sr-tabs button")
    s.note("scout reports: three tabs", None if tabs.count() == 3 else f"{tabs.count()} tabs")
    s.note("scout reports: rows drawn", None if _sr_rows(s).count() > 0 else "no rows")
    s.note("scout reports: caption", None if re.search(r"\d+ of [\d,]+ reports", s.page.inner_text("#sr-cap"))
           else s.page.inner_text("#sr-cap"))
    s.note("scout reports: Refresh present (never pressed: reads the club's sheet)",
           None if s.page.locator("#sr-refresh").is_visible() else "no Refresh button")


def scout_filters_url(s, w):
    """A filter narrows the list, goes in the URL, back restores it, the URL reopens it."""
    s.goto(SR_PATH, check=False)
    sel = _need(s, "Verdict")
    if sel is None:
        return
    before = _sr_rows(s).count()
    s.step("scout reports: Verdict = Sign", lambda p: sel.select_option(value="Sign", timeout=3000))
    after = _sr_rows(s).count()
    s.note("scout reports: filter narrows", None if 0 < after < before else f"{before} -> {after}")
    s.note("scout reports: filter in the URL", None if "verdict=Sign" in s.page.url else s.page.url)
    url = s.page.url
    s.step("scout reports: back", lambda p: p.go_back())
    s.note("scout reports: back restores all", None if _sr_rows(s).count() == before
           else f"{_sr_rows(s).count()} rows, expected {before}")
    s.goto(urlparse(url).path + "?" + urlparse(url).query, check=True, desc="scout reports: shared filter URL")
    s.note("scout reports: shared URL keeps the filter",
           None if s.page.locator("#f-verdict").input_value() == "Sign" and _sr_rows(s).count() == after
           else f"{s.page.locator('#f-verdict').input_value()} / {_sr_rows(s).count()}")


def scout_search_and_age(s, w):
    s.goto(SR_PATH, check=False)
    box = _need(s, "Search for a player", "text")
    if box is None:
        return
    s.step("scout reports: search", lambda p: (box.fill("Samba", timeout=3000), box.press("Enter")))
    names = s.page.locator("#sr-body .pname").all_inner_texts()
    s.note("scout reports: search matches names", None if names and all("samba" in n.lower() for n in names) else names[:5])
    s.note("scout reports: thin pool rating withheld",
           None if "Not rated: only" in s.page.inner_text("#sr-body") else "no 'Not rated: only' note")
    age = s.page.locator("#f-max_age")
    s.step("scout reports: max age 24", lambda p: (age.fill("24"), age.press("Enter"), age.blur()))
    s.note("scout reports: max age in the URL", None if "max_age=24" in s.page.url else s.page.url)


def scout_tabs(s, w):
    s.goto(SR_PATH, check=False)
    b = s.page.locator("#sr-tabs [data-tab=disagree]")
    s.step("scout reports: Data disagrees tab", lambda p: b.click(timeout=3000))
    s.note("scout reports: disagree caption", None if "Sign but rated under" in s.page.inner_text("#sr-cap")
           else s.page.inner_text("#sr-cap"))
    s.note("scout reports: filters hidden on that tab", None if s.page.locator("#sr-filters").is_hidden() else "filters shown")
    s.step("scout reports: Scout activity tab", lambda p: s.page.locator("#sr-tabs [data-tab=activity]").click(timeout=3000))
    s.note("scout reports: activity table", None if "Reports" in s.page.inner_text("#sr-thead") else s.page.inner_text("#sr-thead"))
    s.step("scout reports: back to Data disagrees", lambda p: p.go_back())
    s.note("scout reports: back restores the tab", None if "tab=disagree" in s.page.url else s.page.url)


def scout_open_report(s, w):
    """A row opens the full report below the table; it is in the URL; a fresh load reopens it;
    nothing overflows at any width."""
    s.goto(SR_PATH, check=False)
    row = _sr_rows(s).first
    s.step("scout reports: open a report", lambda p: row.locator("td").nth(0).click(timeout=3000))
    try:
        s.page.locator("#sr-detail .sr-report").wait_for(timeout=3000)
    except Exception:
        return s.note("scout reports: report card shown", "no report card")
    s.note("scout reports: open report in the URL", None if "open=" in s.page.url else s.page.url)
    body = s.page.inner_text("#sr-detail")
    s.note("scout reports: report card has a way on", None if ("Open card" in body or "Not in our data" in body
                                                                or "no card to open" in body) else body[:120])
    url = s.page.url
    for width in (1280, 1440, 1920):
        s.page.set_viewport_size({"width": width, "height": 900})
        s.goto(urlparse(url).path + "?" + urlparse(url).query, check=True, desc=f"scout reports: open report @{width}")
        try:                     # the report opens once its JSON has arrived
            s.page.locator("#sr-detail .sr-report").first.wait_for(state="attached", timeout=3000)
        except Exception:
            pass
        s.shot("report_open", width, full=True)
        s.note(f"scout reports: report reopens from the URL @{width}",
               None if s.page.locator("#sr-detail .sr-report").count() else "not reopened")
    s.page.set_viewport_size({"width": w, "height": 900})
    close = s.page.locator("[data-action=close-report]")
    if close.count():
        s.step("scout reports: close the report", lambda p: close.click(timeout=3000))
        s.note("scout reports: closed", None if not s.page.locator("#sr-detail .sr-report").count() else "still shown")


def scout_name_opens_card(s, w):
    s.goto(SR_PATH + "?verdict=Sign", check=False)
    link = s.page.locator("#sr-body a.plink").first
    if not link.count():
        return s.note("scout reports: name link", skipped="no linked player")
    _go_card(s, "scout reports: a name opens his card with a way back", lambda: link.click(timeout=3000))
    s.note("scout reports: back link returns to Scout reports",
           None if "back=%2Fscout-reports%3Fverdict%3DSign" in s.page.url else s.page.url)
    back = s.page.locator("#back")
    try:
        s.page.wait_for_function("() => document.querySelector('#back')?.getAttribute('href')?.startsWith('/scout')", timeout=4000)
        s.step("scout reports: card ← Back", lambda p: back.click(timeout=3000), expect_nav=True)
    except Exception as e:
        return s.note("scout reports: card ← Back", f"back link not set: {str(e)[:80]}")
    s.note("scout reports: ← Back keeps the filter",
           None if urlparse(s.page.url).path == SR_PATH and "verdict=Sign" in s.page.url else s.page.url)


def scout_sort(s, w):
    s.goto(SR_PATH, check=False)
    b = s.page.locator("#sr-thead [data-sort=Watched]")
    s.step("scout reports: sort by Watched", lambda p: b.click(timeout=3000))
    first = s.page.locator("#sr-body tr td").first.inner_text()
    s.step("scout reports: sort by Watched (descending)", lambda p: s.page.locator("#sr-thead [data-sort=Watched]").click(timeout=3000))
    first_d = s.page.locator("#sr-body tr td").first.inner_text()
    s.note("scout reports: sort flips", None if first <= first_d else f"{first} / {first_d}")
    s.note("scout reports: sort in the URL", None if "sort=Watched" in s.page.url and "dir=desc" in s.page.url else s.page.url)


# -- Watchlist --------------------------------------------------------------------------------
WL_PATH = "/watchlist"


def _wl_rows(s):
    return s.page.locator("#wl-body tr[data-row]")


def _wl_ready(s):
    try:
        s.page.locator("#wl-main:not([hidden]), #wl-empty:not([hidden])").first.wait_for(timeout=6000)
        return s.page.locator("#wl-main:not([hidden])").count() > 0
    except Exception:
        return False


def watchlist_first_view(s, w):
    s.goto(WL_PATH, check=True, desc="watchlist: first view")
    if not _wl_ready(s):
        return s.note("watchlist: rows", skipped="watchlist empty in this database")
    s.note("watchlist: four tiles", None if s.page.locator("#wl-tiles .tile").count() == 4 else "tiles missing")
    big = s.page.locator("#wl-tiles .tile .v").first.evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
    s.note("watchlist: tile numbers large", None if big >= 22 else f"{big}px")
    s.note("watchlist: rows drawn", None if _wl_rows(s).count() > 0 else "no rows")
    heads = s.page.inner_text("#wl-thead")
    s.note("watchlist: columns", None if all(h in heads for h in ("Composite", "Injury", "Months left", "Assessed", "Note"))
           else heads)


def watchlist_status_filter(s, w):
    s.goto(WL_PATH, check=False)
    if not _wl_ready(s):
        return s.note("watchlist: status filter", skipped="watchlist empty")
    box = s.page.locator("#wl-status input").first
    before = _wl_rows(s).count()
    s.step("watchlist: untick a status", lambda p: box.click(timeout=3000))
    s.note("watchlist: status in the URL", None if "status=" in s.page.url else s.page.url)
    after = _wl_rows(s).count()
    s.note("watchlist: filter applies", None if after <= before and (after or s.page.locator("#wl-none:not([hidden])").count())
           else f"{before} -> {after}")
    s.step("watchlist: back", lambda p: p.go_back())
    s.note("watchlist: back restores", None if _wl_rows(s).count() == before else f"{_wl_rows(s).count()} rows")


def watchlist_money(s, w):
    s.goto(WL_PATH, check=False)
    if not _wl_ready(s):
        return s.note("watchlist: market value", skipped="watchlist empty")
    sw = s.page.locator("#f-money")
    s.step("watchlist: Market value on", lambda p: sw.check(timeout=3000))
    s.note("watchlist: Market value column", None if "Market value" in s.page.inner_text("#wl-thead") else "no column")
    s.note("watchlist: money in the URL", None if "money=1" in s.page.url else s.page.url)
    s.shot("money", w, full=True)
    s.step("watchlist: Market value off", lambda p: sw.uncheck(timeout=3000))
    s.note("watchlist: column gone", None if "Market value" not in s.page.inner_text("#wl-thead") else "still shown")


def watchlist_editor(s, w):
    """A row opens the editor (note, status, Save / Remove / Close, Assess); in the URL; a fresh
    load reopens it. Save / Remove write: only with --allow-writes, and the note and status are
    put back as they were."""
    s.goto(WL_PATH, check=False)
    if not _wl_ready(s):
        return s.note("watchlist: editor", skipped="watchlist empty")
    s.step("watchlist: open a row", lambda p: _wl_rows(s).first.locator("td").nth(1).click(timeout=3000))
    ed = s.page.locator("#wl-edit")
    s.note("watchlist: editor shown", None if ed.is_visible() else "editor hidden")
    s.note("watchlist: open row in the URL", None if "open=" in s.page.url else s.page.url)
    s.note("watchlist: editor has its controls",
           None if all(s.page.locator(f"#{i}").is_visible() for i in ("e-note", "e-status", "e-save", "e-remove", "e-close", "e-assess"))
           else "a control is missing")
    url = s.page.url
    for width in (1280, 1440, 1920):
        s.page.set_viewport_size({"width": width, "height": 900})
        s.goto(urlparse(url).path + "?" + urlparse(url).query, check=True, desc=f"watchlist: editor @{width}")
        try:                     # the editor opens once the list's JSON has arrived
            ed.wait_for(state="visible", timeout=3000)
        except Exception:
            pass
        s.shot("editor", width, full=True)
        s.note(f"watchlist: editor reopens from the URL @{width}", None if ed.is_visible() else "not reopened")
    s.page.set_viewport_size({"width": w, "height": 900})
    s.step("watchlist: Close", lambda p: s.page.locator("#e-close").click(timeout=3000))
    s.note("watchlist: closed", None if ed.is_hidden() else "still open")
    if not s.allow_writes:
        return s.note("watchlist: Save / Remove", skipped="write control (use --allow-writes)")
    s.step("watchlist: reopen", lambda p: _wl_rows(s).first.locator("td").nth(1).click(timeout=3000))
    note, status = s.page.locator("#e-note").input_value(), s.page.locator("#e-status").input_value()
    s.page.locator("#e-note").fill(note + " [webcheck]")
    s.step("watchlist: Save", lambda p: s.page.locator("#e-save").click(timeout=3000))
    s.note("watchlist: saved note shown", None if "[webcheck]" in s.page.inner_text("#wl-body") else "note not shown")
    s.step("watchlist: reopen to restore", lambda p: _wl_rows(s).first.locator("td").nth(1).click(timeout=3000))
    s.page.locator("#e-note").fill(note)
    s.page.locator("#e-status").select_option(value=status)
    s.step("watchlist: Save the original back", lambda p: s.page.locator("#e-save").click(timeout=3000))


def watchlist_name_opens_card(s, w):
    s.goto(WL_PATH, check=False)
    if not _wl_ready(s):
        return s.note("watchlist: name link", skipped="watchlist empty")
    link = s.page.locator("#wl-body a.plink").first
    if not link.count():
        return s.note("watchlist: name link", skipped="no openable card")
    _go_card(s, "watchlist: a name opens his card with a way back", lambda: link.click(timeout=3000))
    try:
        s.page.wait_for_function("() => document.querySelector('#back')?.getAttribute('href')?.startsWith('/watchlist')", timeout=4000)
        s.step("watchlist: card ← Back", lambda p: s.page.locator("#back").click(timeout=3000), expect_nav=True)
    except Exception as e:
        return s.note("watchlist: card ← Back", f"back link not set: {str(e)[:80]}")
    s.note("watchlist: ← Back returns", None if urlparse(s.page.url).path == WL_PATH else s.page.url)


def watchlist_download(s, w):
    s.goto(WL_PATH + "?money=1", check=False)
    if not _wl_ready(s):
        return s.note("watchlist: CSV", skipped="watchlist empty")
    href = s.page.locator("#wl-dl").get_attribute("href") or ""
    s.note("watchlist: CSV link carries the switch", None if "money=1" in href else href)
    got = s.page.evaluate("(h) => fetch(h).then(r => r.text().then(t => [r.status, t.split('\\n')[0]]))", href)
    s.note("watchlist: CSV downloads with today's header",
           None if got[0] == 200 and got[1].startswith("Player,Club,League,Position,Age,Composite") and "Market value" in got[1]
           else str(got))


def watchlist_sort(s, w):
    s.goto(WL_PATH, check=False)
    if not _wl_ready(s):
        return s.note("watchlist: sort", skipped="watchlist empty")
    s.step("watchlist: sort by Composite", lambda p: s.page.locator("#wl-thead [data-sort=Composite]").click(timeout=3000))
    vals = [v for v in s.page.locator("#wl-body td.c:nth-of-type(6)").all_inner_texts() if v != "—"]
    s.note("watchlist: Composite ascending", None if vals == sorted(vals) else vals)
    s.note("watchlist: sort in the URL", None if "sort=Composite" in s.page.url else s.page.url)


# -- Physical ---------------------------------------------------------------------------------
PH_PATH = "/physical"


def _ph_ready(s):
    try:
        s.page.locator("#ph-main:not([hidden]), #ph-empty:not([hidden])").first.wait_for(timeout=6000)
        return s.page.locator("#ph-main:not([hidden])").count() > 0
    except Exception:
        return False


def _ph_rows(s):
    return s.page.locator("#ld-body tr:not(.sec)")


def physical_exercise_controls(s, w):
    """The generic exerciser over every control except the player links (each leaves for the
    card, which has its own entry; the hand-off is physical_name_opens_card)."""
    g = s.exercise.__globals__
    orig = g["sample_controls"]
    g["sample_controls"] = lambda cs, **kw: orig([c for c in cs if c["kind"] not in ("row", "link")], **kw)
    try:
        s.exercise(PH_PATH)
    finally:
        g["sample_controls"] = orig


def reference_rating(s, w):
    """What goes into each rating: a position button redraws in place and goes in the URL; the
    Excel download answers."""
    s.page.wait_for_selector("#rr-table tbody tr", timeout=5000)
    s.note("rating reference: metrics listed", None if s.page.locator("#rr-table tbody tr").count() > 8 else "few rows")
    s.step("rating reference: Winger", lambda p: s.page.locator("#rr-pos button[data-p='Winger']").click(timeout=3000))
    s.page.wait_for_timeout(300)
    s.note("rating reference: position in the URL", None if "position=Winger" in s.page.url else s.page.url)
    s.note("rating reference: archetype columns", None if "Direct & 1v1" in s.page.inner_text("#rr-table") else "no archetype column")
    r = s.page.request.get(s.base + "/api/rating-reference.xlsx")
    s.note("rating reference: Excel download", None if r.status == 200 and len(r.body()) > 1000 else f"HTTP {r.status}")


def reference_styles(s, w):
    """How playing styles work: steps, labels, a position switch, the worked example."""
    s.page.wait_for_selector("#ps-table tbody tr", timeout=5000)
    s.note("playing styles: three steps", None if s.page.locator(".ps-step").count() == 3 else "steps missing")
    s.note("playing styles: worked example (Winger)", None if s.page.locator("#ps-ex tbody tr").count() >= 1 else "no example")
    s.step("playing styles: Centre Back", lambda p: s.page.locator("#ps-group button[data-g='Centre Back']").click(timeout=3000))
    s.page.wait_for_timeout(300)
    s.note("playing styles: group in the URL", None if "group=Centre" in s.page.url else s.page.url)


def reference_glossary(s, w):
    """Glossary: search narrows (in the URL), a group tab switches, nothing matches -> a note."""
    s.page.wait_for_selector(".gl-row", timeout=5000)
    before = s.page.locator(".gl-row").count()
    s.step("glossary: search 'sprint'", lambda p: s.page.locator("#gl-q").fill("sprint", timeout=3000))
    s.note("glossary: search narrows", None if 0 < s.page.locator(".gl-row").count() < before else "no change")
    s.note("glossary: search in the URL", None if "q=sprint" in s.page.url else s.page.url)
    s.step("glossary: clear", lambda p: s.page.locator("#gl-q").fill("", timeout=3000))
    tab = s.page.locator("#gl-tabs [data-g='Physical']")
    s.step("glossary: Physical tab", lambda p: tab.click(timeout=3000))
    s.note("glossary: Physical entries", None if "SkillCorner" in s.page.inner_text("#gl-list") else "not switched")
    s.step("glossary: search nothing", lambda p: s.page.locator("#gl-q").fill("zzzzqq", timeout=3000))
    s.note("glossary: empty note", None if "No metric matches" in s.page.inner_text("#gl-list") else "no note")


def club_vs_league(s, w):
    """Club vs League One (owner's redesign 2026-11-10): Top 6 + our row, Big picture in two
    columns, gap map (one line per position, a click opens its detail, shortfall columns aligned),
    percentiles as plain numbers, and the remembered Leagues picker."""
    s.page.evaluate("() => { try { localStorage.removeItem('lofc.cvl.leagues'); } catch (e) {} }")
    s.page.reload()
    s.page.wait_for_selector("#cv-gap-t tr.pos", timeout=8000)
    s.shot("top", w)
    top = s.page.locator("#cv-top6-t tbody tr:not(.us)").count()
    us = s.page.locator("#cv-top6-t tbody tr.us")
    s.note("club vs league: top 6 + our row", None if us.count() == 1 and top + 1 in (6, 7) else f"{top} clubs, {us.count()} our rows")
    if us.count():
        chips = us.locator(".chip").all_inner_texts()
        s.note("club vs league: our row has 3 ratings", None if len(chips) == 3 and all(re.match(r"^\d\.\d\d$", c) for c in chips) else str(chips))
    gap = s.page.evaluate("""() => { const c = document.querySelector('#cv-top6'), t = document.querySelector('#cv-top6-t');
      return c.getBoundingClientRect().bottom - t.getBoundingClientRect().bottom; }""")
    s.note("club vs league: Top 6 card ends at its table", None if gap < 48 else f"{gap:.0f}px empty below the table")
    s.note("club vs league: how-it-works closed", None if not s.page.locator("#cv-how").evaluate("d => d.open") else "open")
    bp = s.page.locator("#cv-big-l, #cv-big-r").count()
    side = s.page.evaluate("() => { const l = document.querySelector('#cv-big-l').getBoundingClientRect(), r = document.querySelector('#cv-big-r').getBoundingClientRect(); return Math.abs(l.top - r.top) < 2 && r.left > l.right; }")
    s.note("club vs league: Big picture in two columns", None if bp == 2 and side else "not side by side")
    ranks = s.page.locator("#cv-big .cv-rk").all_inner_texts()
    s.note("club vs league: ranks are ordinals only", None if ranks and all(re.match(r"^\d+(st|nd|rd|th)$", r) for r in ranks) else str(ranks[:5]))
    s.note("club vs league: six positions", None if s.page.locator("#cv-gap-t tr.pos").count() == 6 else "not 6")
    vis = s.page.locator("#cv-gap-t tr.cv-det:not([hidden])")
    first = s.page.locator("#cv-gap-t tr.pos").first.get_attribute("data-g")
    s.note("club vs league: first gap row open by default", None if vis.count() == 1 and vis.first.get_attribute("data-d") == first else f"{vis.count()} open")
    over = s.page.evaluate("() => { const c = document.querySelector('#cv-gap'); return c.scrollWidth - c.clientWidth; }")
    s.note("club vs league: gap map has no sideways scroll", None if over <= 1 else f"{over}px wider than its card")
    gtext = s.page.inner_text("#cv-gap-t")
    s.note("club vs league: gap map percentiles are plain numbers", None if not re.search(r"\b\d+(st|nd|rd|th)\b", gtext) else "ordinal found")
    if first != "Full Back":
        s.step("club vs league: close the first gap row", lambda p: s.page.locator(f"#cv-gap-t tr.pos[data-g='{first}']").click(timeout=3000))
    fb = s.page.locator("#cv-gap-t tr.pos[data-g='Full Back']")
    if fb.count():
        if first != "Full Back":
            s.step("club vs league: open Full Back", lambda p: fb.click(timeout=3000))
        det = s.page.locator("#cv-gap-t tr.cv-det[data-d='Full Back']")
        s.note("club vs league: Full Back detail open", None if det.is_visible() else "closed")
        # owner 2026-11-10: opening a gap row also switches "Players who could close the gap"
        s.page.wait_for_timeout(1500)
        pos = s.page.eval_on_selector("#cv-group", "e => e.value")
        s.note("club vs league: a gap-row click switches the recommendations", None if pos == "Full Back" else pos)
        s.note("club vs league: detail stays open after the switch", None if det.is_visible() else "closed")
        if s.page.locator("#cv-gap-t tr.pos[data-g='Midfield']").count():
            s.step("club vs league: open Midfield", lambda p: s.page.locator("#cv-gap-t tr.pos[data-g='Midfield']").click(timeout=3000))
            s.page.wait_for_timeout(1500)
            pos = s.page.eval_on_selector("#cv-group", "e => e.value")
            s.note("club vs league: recommendations follow the opened row", None if pos == "Midfield" else pos)
        # the summary row's Ours/Top 6/Behind columns line up with "Every shortfall" below
        al = s.page.evaluate("""() => {
          const a = [...document.querySelectorAll("#cv-gap-t tr.pos[data-g='Full Back'] .cv-sfl > span")].slice(0, 4),
                b = [...document.querySelectorAll("#cv-gap-t tr.cv-det[data-d='Full Back'] .cv-sfd > span")].slice(0, 4),
                h = [...document.querySelectorAll("#cv-gap-t thead .cv-sfh > span")];
          if (a.length < 4 || b.length < 4) return 'missing';
          const bad = [1, 2, 3].filter(i => Math.abs(a[i].getBoundingClientRect().right - b[i].getBoundingClientRect().right) > 0.5
                                         || Math.abs(a[i].getBoundingClientRect().right - h[i].getBoundingClientRect().right) > 0.5);
          return bad.length ? 'columns ' + bad.join(',') + ' off' : ''; }""")
        s.note("club vs league: shortfall columns aligned", al or None)
        same = s.page.evaluate("""() => {
          const pick = sel => { const s = [...document.querySelectorAll(sel)], o = {};
            for (let i = 0; i + 3 < s.length; i += 4) o[s[i].innerText] = s[i + 3].innerText; return o; };
          const top = pick("#cv-gap-t tr.pos[data-g='Full Back'] .cv-sfl > span"),
                all = pick("#cv-gap-t tr.cv-det[data-d='Full Back'] .cv-sfd > span:not(.h)");
          return Object.keys(top).filter(k => k in all && all[k] !== top[k]).join(', '); }""")
        s.note("club vs league: one Behind figure", None if not same else f"differ: {same}")
        cut = s.page.evaluate("""() => [...document.querySelectorAll("#cv-gap-t tr.cv-det[data-d='Full Back'] td, #cv-gap-t tr.cv-det[data-d='Full Back'] span")]
          .filter(e => e.scrollWidth > e.clientWidth + 1).length""")
        s.note("club vs league: nothing cut off in the detail", None if not cut else f"{cut} clipped")
        fb.scroll_into_view_if_needed()
        s.page.evaluate("() => document.querySelector(\"#cv-gap-t tr.pos[data-g='Full Back']\").scrollIntoView({block: 'start'}); window.scrollBy(0, -130)")
        s.shot("gap_fullback", w)
    s.step("club vs league: pick Centre Back", lambda p: s.page.select_option("#cv-group", "Centre Back", timeout=3000))
    s.page.wait_for_timeout(400)
    s.note("club vs league: position in the URL", None if "group=Centre" in s.page.url else s.page.url)
    rows = s.page.locator("#cv-rec-t tbody tr")
    s.note("club vs league: at most 15 per league", None if 0 < rows.count() <= 15 else f"{rows.count()} rows")
    # Leagues picker: default three, a checklist of every league, remembered on this computer
    btn = s.page.locator("#cv-leagues")
    s.note("club vs league: default leagues", None if btn.inner_text().startswith("3 selected: League One, Championship, League Two") else btn.inner_text())
    s.note("club vs league: one tab per selected league", None if s.page.locator("#cv-tabs button[data-l]").count() == 3 else "not 3 tabs")
    cap = s.page.inner_text("#cv-count")
    s.note("club vs league: caption names the league", None if re.match(r"^League One · top \d+ of \d+ centre backs above our level$", cap) else cap)
    hh = s.page.evaluate("() => [document.querySelector('#cv-leagues'), document.querySelector('#cv-contract')].map(e => { const r = e.getBoundingClientRect(); return [r.top, r.bottom]; })")
    s.note("club vs league: Leagues lines up with the other filters", None if abs(hh[0][0] - hh[1][0]) <= 2 and abs(hh[0][1] - hh[1][1]) <= 2 else str(hh))
    s.step("club vs league: open Leagues", lambda p: btn.click(timeout=3000))
    boxes = s.page.locator("#cv-lp-menu input[type=checkbox]")
    s.note("club vs league: every league in the checklist", None if boxes.count() >= 3 else f"{boxes.count()} leagues")
    s.page.evaluate("() => window.scrollTo(0, document.querySelector('#cv-rec').getBoundingClientRect().top + scrollY - 10)")
    s.shot("leagues_open", w)
    if boxes.count() > 3:
        extra = boxes.nth(3)
        s.step("club vs league: add a fourth league", lambda p: extra.check(timeout=3000))
        s.note("club vs league: four tabs", None if s.page.locator("#cv-tabs button[data-l]").count() == 4 else "not 4")
        s.page.keyboard.press("Escape")
        s.page.reload(); s.page.wait_for_selector("#cv-rec-t tbody tr", timeout=8000)
        s.note("club vs league: selection remembered", None if s.page.locator("#cv-tabs button[data-l]").count() == 4 else "forgotten")
        s.step("club vs league: open Leagues again", lambda p: s.page.locator("#cv-leagues").click(timeout=3000))
        s.step("club vs league: remove it", lambda p: s.page.locator("#cv-lp-menu input[type=checkbox]").nth(3).uncheck(timeout=3000))
        s.page.keyboard.press("Escape")
        s.note("club vs league: back to three tabs", None if s.page.locator("#cv-tabs button[data-l]").count() == 3 else "not 3")
    tab = s.page.locator("#cv-tabs button[data-l]").nth(1)
    if tab.count():
        s.step("club vs league: second league tab", lambda p: tab.click(timeout=3000))
        s.note("club vs league: active league in the URL", None if f"league={tab.get_attribute('data-l')}" in s.page.url else s.page.url)
        s.note("club vs league: active tab bold + underlined", None if tab.evaluate("b => b.classList.contains('on') && getComputedStyle(b).fontWeight >= 600") else "not marked")
    s.step("club vs league: strong on 2+ weaknesses", lambda p: s.page.locator("#cv-strong").click(timeout=3000))
    s.page.wait_for_timeout(300)
    s.note("club vs league: strong filter in the URL", None if "strong=1" in s.page.url else s.page.url)
    s.step("club vs league: strong off", lambda p: s.page.locator("#cv-strong").click(timeout=3000))
    # owner 2026-11-09: three weakness columns (sortable), "vs our best", Top-6 level only
    heads = s.page.locator("#cv-rec-t th.cv-sort")
    s.note("club vs league: Overall, vs our best and 3 weakness columns sortable",
           None if heads.count() == 5 else f"{heads.count()} sortable headings")
    s.note("club vs league: no tag column", None if "Strong where we are weak" not in s.page.inner_text("#cv-rec-t") else "old column")
    col = s.page.locator("#cv-rec-t th[data-sort='w0']")
    if col.count():
        s.step("club vs league: sort by first weakness", lambda p: col.click(timeout=3000))
        vals = s.page.locator("#cv-rec-t tbody tr td:nth-child(10)").all_inner_texts()
        s.note("club vs league: weakness columns are plain numbers", None if all(re.match(r"^(\d+|—)$", v.strip()) for v in vals) else str(vals[:5]))
        nums = [int(re.sub(r"\D", "", v)) for v in vals if re.search(r"\d", v)]
        s.note("club vs league: weakness sort is best first", None if nums == sorted(nums, reverse=True) else str(nums))
        s.note("club vs league: sort in the URL", None if "sort=w0" in s.page.url else s.page.url)
        s.step("club vs league: back to Overall", lambda p: s.page.locator("#cv-rec-t th[data-sort='']").click(timeout=3000))
    s.step("club vs league: Top-6 level only", lambda p: s.page.locator("#cv-top6only").click(timeout=3000))
    s.page.wait_for_timeout(300)
    s.note("club vs league: top6 filter in the URL", None if "top6=1" in s.page.url else s.page.url)
    rows = s.page.locator("#cv-rec-t tbody tr")
    badges = s.page.locator("#cv-rec-t tbody tr .cv-t6")
    s.note("club vs league: Top-6 level only keeps badged players", None if rows.count() == badges.count() else f"{rows.count()} rows, {badges.count()} badges")
    s.step("club vs league: Top-6 level off", lambda p: s.page.locator("#cv-top6only").click(timeout=3000))
    s.shot("weakness_columns", w)


def users_first_view(s, w):
    """Users (admin): the accounts list, a row opens the account panel, Close shuts it; the
    create form opens and cancels. Writes are never sent without --allow-writes."""
    if s.page.locator("#us-body").count() == 0:
        return s.note("users: page", skipped="not an admin (run with --role admin)")
    s.page.wait_for_selector("#us-body tr[data-id]", timeout=5000)
    s.note("users: accounts listed", None if s.page.locator("#us-body tr[data-id]").count() >= 1 else "no rows")
    s.step("users: open an account", lambda p: s.page.locator("#us-body tr[data-id]").first.click(timeout=3000))
    s.note("users: account panel", None if s.page.locator("#us-panel").is_visible()
           and "Reset password" in s.page.inner_text("#us-panel") else "panel not shown")
    s.step("users: close the panel", lambda p: s.page.locator("[data-action=close]").click(timeout=3000))
    s.note("users: panel closed", None if not s.page.locator("#us-panel").is_visible() else "still open")
    s.step("users: open the create form", lambda p: s.page.locator("#us-new").click(timeout=3000))
    s.note("users: create form", None if s.page.locator("#us-create").is_visible() else "form hidden")
    s.step("users: cancel", lambda p: s.page.locator("#c-cancel").click(timeout=3000))


def physical_additions(s, w):
    """TASKS 2.36: Physical rating first in the metric list and ranked; age filter in the URL;
    chart medians, named top dots, instant tooltips, find-a-player; no browser title tips."""
    s.goto(PH_PATH, check=True, desc="physical: additions")
    if not _ph_ready(s):
        return s.note("physical: additions", "page did not draw")
    first = s.page.locator("#f-metric option").first
    s.note("physical: 'Physical rating' is the first metric",
           None if first.inner_text().strip() == "Physical rating" else first.inner_text())
    s.step("physical: rank by Physical rating",
           lambda p: s.page.locator("#f-metric").select_option(value="physical_rating", timeout=3000))
    rk = s.page.locator("#ld-body .ph-rk").all_inner_texts()
    s.note("physical: rating ranks 'Nth of M'",
           None if rk and all(re.fullmatch(r"\d+(st|nd|rd|th) of \d+", t.strip()) for t in rk[:5]) else f"{rk[:3]}")
    s.note("physical: two median lines", None if s.page.locator("#sc-plot line.med").count() == 2 else "no medians")
    s.note("physical: named dots", None if s.page.locator("#sc-plot text.ptl").count() >= 1 else "no names")
    dot = s.page.locator("#sc-plot circle[data-tip]").first
    tip = dot.get_attribute("data-tip") or ""
    s.note("physical: dot tooltip has club, minutes and both values",
           None if tip.count("\n") >= 3 and " min" in tip else f"tooltip {tip!r}")
    s.note("physical: no browser title tooltips", None if s.page.locator("main [title], main svg title").count() == 0
           else "title attributes left")
    s.step("physical: age Under 23", lambda p: s.page.locator("#f-age").select_option(value="u23", timeout=3000))
    s.note("physical: age in the URL", None if "age=u23" in s.page.url else s.page.url)
    name = s.page.locator("#ld-body .pname").first.inner_text() if s.page.locator("#ld-body .pname").count() else ""
    if name:
        s.step("physical: find a player on the chart", lambda p: s.page.locator("#f-find").fill(name.split()[-1], timeout=3000))
        s.note("physical: found player highlighted", None if s.page.locator("#sc-plot circle.found").count() >= 1
               else "no highlighted dot")
    box = s.page.locator("#sc-plot").bounding_box()
    card = s.page.locator("#ph-scatter").bounding_box()
    s.note("physical: chart fills its box", None if box and card and (card["y"] + card["height"]) - (box["y"] + box["height"]) < 60
           else "space below the chart")


def physical_first_view(s, w):
    """Opens on the live season and Orient's league: leaders (three large tiles + table), the
    scatter with Orient's players, and the squad table."""
    s.goto(PH_PATH, check=True, desc="physical: first view")
    if not _ph_ready(s):
        return s.note("physical: first view", "page did not draw")
    s.note("physical: opens on 2026/27", None if s.page.locator("#f-season").input_value() == "319"
           else s.page.locator("#f-season").input_value())
    s.note("physical: leaders listed", None if _ph_rows(s).count() > 0 else "no rows")
    s.note("physical: three leader tiles", None if s.page.locator("#ld-tiles .tile").count() == 3 else "tiles missing")
    big = s.page.locator("#ld-tiles .tile .v").first.evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
    s.note("physical: tile numbers large", None if big >= 22 else f"{big}px")
    s.note("physical: scatter drawn", None if s.page.locator("#sc-plot svg circle").count() >= 3 else "no points")
    s.note("physical: squad rows", None if s.page.locator("#sq-body tr").count() > 0 else "no squad rows")
    s.note("physical: percentile colours in the squad table",
           None if s.page.locator("#sq-body .ph-pp").count() > 0 else "no percentile pills")


def physical_filters_back_forward(s, w):
    """position -> league -> metric: each in the URL; back x3 / forward restore; the URL reopens it."""
    s.goto(PH_PATH, check=False)
    if not _ph_ready(s):
        return s.note("physical: filters", skipped="page did not draw")
    start = s.snapshot()
    pos = _need(s, "Position")
    if pos is None:
        return
    s.step("physical: position = Winger", lambda p: pos.select_option(value="Winger", timeout=3000))
    s.note("physical: position in the URL", None if "position=Winger" in s.page.url else s.page.url)
    s.note("physical: title follows the position", None if "Wingers" in s.page.inner_text("#ld-sub") else s.page.inner_text("#ld-sub"))
    lg = _need(s, "League")
    if lg is not None:
        _pick_other(s, lg, "physical: another league")
    met = _need(s, "Metric")
    if met is not None:
        s.step("physical: metric = Sprints", lambda p: met.select_option(value="sprint_count_p90", timeout=3000))
        s.note("physical: metric in the URL", None if "metric=sprint_count_p90" in s.page.url else s.page.url)
        s.note("physical: value column follows the metric", None if "Sprints" in s.page.inner_text("#ld-head") else s.page.inner_text("#ld-head"))
    mid = s.snapshot()
    url = s.page.url
    for i in range(3):
        s.step(f"physical: back {i + 1}", lambda p: p.go_back())
    back = s.snapshot()
    s.note("physical: back restores the first view", None if back["controls"] == start["controls"] else
           f"{start['controls']} -> {back['controls']}")
    for i in range(3):
        s.step(f"physical: forward {i + 1}", lambda p: p.go_forward())
    s.note("physical: forward restores", None if s.snapshot()["controls"] == mid["controls"] else "controls differ")
    fresh = s.page.context.new_page()
    try:
        fresh.goto(url, wait_until="load")
        fresh.wait_for_load_state("networkidle", timeout=8000)
        same = fresh.locator("#f-metric").input_value() == "sprint_count_p90" and \
            fresh.locator("#f-position").input_value() == "Winger"
    finally:
        fresh.close()
    s.note("physical: the URL reopens the same view", None if same else url)


def physical_no_data_season(s, w):
    """2024/25: one line, no tables, no league/position filters."""
    s.goto(PH_PATH, check=False)
    sea = _need(s, "Season")
    if sea is None:
        return
    s.step("physical: season 2024/25", lambda p: sea.select_option(value="317", timeout=3000))
    s.note("physical: no-data line", None if s.page.inner_text("#ph-empty").strip() == "No physical data for 2024/25." else
           s.page.inner_text("#ph-empty"))
    s.note("physical: nothing else drawn", None if s.page.locator("#ph-main").is_hidden() and
           s.page.locator("#w-league").is_hidden() else "tables or filters still shown")
    s.step("physical: season 2025/26", lambda p: sea.select_option(value="318", timeout=3000))
    s.note("physical: 2025/26 draws", None if _ph_rows(s).count() > 0 else "no rows")


def physical_thin_pool(s, w):
    """A league-position pool below 10: listed by name, no rank or percentile, the note says why."""
    s.goto(PH_PATH + "?season=319&league=903&position=Central+Mid", check=True, desc="physical: thin pool")
    if not _ph_ready(s):
        return s.note("physical: thin pool", skipped="page did not draw")
    t = s.page.locator("#ld-thin")
    s.note("physical: thin note", None if t.is_visible() and t.inner_text().startswith("Not rated: only") else "no note")
    s.note("physical: no Percentile column", None if "Percentile" not in s.page.inner_text("#ld-head") else "percentiles shown")
    s.note("physical: no tiles", None if s.page.locator("#ld-tiles").is_hidden() else "tiles shown")


def physical_show_all_and_orient(s, w):
    """Show all lists the whole pool (in the URL); Orient players are highlighted."""
    s.goto(PH_PATH + "?season=318&league=4&position=Centre+Back", check=False)
    if not _ph_ready(s):
        return s.note("physical: show all", skipped="page did not draw")
    before = _ph_rows(s).count()
    more = s.page.locator("#ld-more")
    if more.is_hidden():
        return s.note("physical: show all", skipped="pool fits in the top list")
    s.step("physical: Show all", lambda p: more.click(timeout=3000))
    after = _ph_rows(s).count()
    s.note("physical: more rows", None if after > before else f"{before} -> {after}")
    s.note("physical: show all in the URL", None if "all=1" in s.page.url else s.page.url)
    s.note("physical: Orient rows highlighted", None if s.page.locator("#ld-body tr.me").count() > 0 else "no Orient row")
    s.shot("show_all", w, full=True)


def physical_scatter_axes(s, w):
    """Changing an axis redraws the scatter (its medians and named dots come from the API) and is in the URL."""
    s.goto(PH_PATH, check=False)
    if not _ph_ready(s):
        return s.note("physical: scatter", skipped="page did not draw")
    x = _need(s, "Across")
    if x is None:
        return
    s.step("physical: scatter across = Distance", lambda p: x.select_option(value="distance_p90", timeout=3000))
    s.note("physical: axis label", None if "Distance (m)" in s.page.inner_text("#sc-plot") else "label not redrawn")
    s.note("physical: axis in the URL", None if "x=distance_p90" in s.page.url else s.page.url)
    s.note("physical: Orient points", None if s.page.locator("#sc-plot circle.orient").count() > 0 else "none highlighted")


def physical_squad_sort(s, w):
    """A squad header sorts highest first, then lowest, then back to the squad order."""
    s.goto(PH_PATH, check=False)
    if not _ph_ready(s):
        return s.note("physical: squad sort", skipped="page did not draw")
    b = s.page.locator("#sq-head [data-sort=top5_psv99_kmh]")
    s.step("physical: sort squad by Top speed", lambda p: b.click(timeout=3000))
    col = 1 + s.page.evaluate("() => [...document.querySelectorAll('#sq-head th')].findIndex("
                              "th => th.querySelector('[data-sort=top5_psv99_kmh]'))")
    vals = [v.split()[0] if v.strip() else "—" for v in s.page.locator(f"#sq-body tr td:nth-child({col}) .ph-v").all_inner_texts()]
    nums = [float(v) for v in vals if v != "—"]
    s.note("physical: Top speed highest first", None if nums == sorted(nums, reverse=True) else vals[:6])
    s.note("physical: sort in the URL", None if "sort=top5_psv99_kmh" in s.page.url else s.page.url)
    s.step("physical: sort squad lowest first", lambda p: s.page.locator("#sq-head [data-sort=top5_psv99_kmh]").click(timeout=3000))
    s.note("physical: dir in the URL", None if "dir=asc" in s.page.url else s.page.url)


def physical_name_opens_card(s, w):
    s.goto(PH_PATH, check=False)
    if not _ph_ready(s):
        return s.note("physical: name link", skipped="page did not draw")
    link = s.page.locator("#ld-body a.plink").first
    if not link.count():
        return s.note("physical: name link", skipped="no openable card")
    _go_card(s, "physical: a name opens his card with a way back", lambda: link.click(timeout=3000))
    try:
        s.page.wait_for_function("() => document.querySelector('#back')?.getAttribute('href')?.startsWith('/physical')", timeout=4000)
        s.step("physical: card ← Back", lambda p: s.page.locator("#back").click(timeout=3000), expect_nav=True)
    except Exception as e:
        return s.note("physical: card ← Back", f"back link not set: {str(e)[:80]}")
    s.note("physical: ← Back returns", None if urlparse(s.page.url).path == PH_PATH else s.page.url)


def physical_layout_widths(s, w):
    """Nothing overflows at any width, with the whole pool listed."""
    for width in s.widths:
        s.page.set_viewport_size({"width": width, "height": 900})
        s.goto(PH_PATH + "?season=318&league=4&position=Centre+Back&all=1", check=True,
               desc=f"physical: layout @{width}")
        s.shot("layout", width, full=True)
    s.page.set_viewport_size({"width": w, "height": 900})


_COMMON = {"exercise": True, "scenarios": []}

PAGES = {
    "home": {"path": "/", "exercise": False, "scenarios": [home_first_view]},
    "players": {"path": "/players", "exercise": False, "scenarios": [
        players_first_view, players_layout_widths, players_exercise_controls, players_position_season_open_back,
        players_filter_open_back, players_leagues, players_chip_remove,
        players_search_other_position, players_clear_search, players_sort, players_money,
        players_metric_filters, players_assessed, players_download, players_history_and_url]},
    "card": {"path": "/player/39154/5/318", "exercise": True, "scenarios": [
        card_back_link, card_money_switch, card_rank_as, card_zones, card_squad_season,
        card_watchlist, card_radars, card_rated_tables, card_other_players]},
    "compare": {"path": "/compare?season=318&position=Winger", "exercise": True, "scenarios": [
        compare_three_players_every_width, compare_defaults_fill_the_url,
        compare_position_season_back_forward, compare_pick_from_pool_list,
        compare_search_this_position_only, compare_none_in_c, compare_name_opens_card,
        compare_zones_and_money, compare_special_cases, compare_more_filters, compare_radars]},
    "report": {"path": REPORT_BASE, "exercise": True, "scenarios": [
        report_empty_state, report_cases, report_search_pick, report_form_live, report_downloads,
        report_season_switch, report_history_and_url, report_layout_widths, report_radar]},
    "squads": {"path": "/squads", "exercise": False, "scenarios": [
        squads_first_view, squads_layout_widths, squads_exercise_controls,
        squads_league_club_open_back, squads_show, squads_more_filters, squads_row_message,
        squads_thin_and_sort, squads_search, squads_download, squads_history_and_url,
        squads_scroll_draws_more]},
    "scout-reports": {"path": "/scout-reports", "exercise": True, "scenarios": [
        scout_first_view, scout_filters_url, scout_search_and_age, scout_tabs, scout_open_report,
        scout_name_opens_card, scout_sort]},
    "watchlist": {"path": "/watchlist", "exercise": True, "scenarios": [
        watchlist_first_view, watchlist_status_filter, watchlist_money, watchlist_editor,
        watchlist_name_opens_card, watchlist_download, watchlist_sort]},
    "assess": {"path": "/assess", "scenarios": []},
    "signoff": {"path": "/signoff", "scenarios": []},
    "physical": {"path": "/physical", "exercise": False, "scenarios": [
        physical_first_view, physical_exercise_controls, physical_layout_widths, physical_filters_back_forward,
        physical_no_data_season, physical_thin_pool, physical_show_all_and_orient,
        physical_scatter_axes, physical_squad_sort, physical_name_opens_card, physical_additions]},
    "club-vs-league": {"path": "/club-vs-league", "exercise": True, "scenarios": [club_vs_league]},
    "rating-reference": {"path": "/rating-reference", "exercise": True, "scenarios": [reference_rating]},
    "playing-styles": {"path": "/playing-styles", "exercise": True, "scenarios": [reference_styles]},
    "glossary": {"path": "/glossary", "exercise": True, "scenarios": [reference_glossary]},
    "users": {"path": "/users", "exercise": True, "scenarios": [users_first_view]},
}
