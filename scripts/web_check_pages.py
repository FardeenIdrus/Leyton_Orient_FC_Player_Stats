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
from urllib.parse import urlencode, urlparse


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


def card_strengths_no_overlap(s, w):
    """Owner 2026-11-13: a metric is never in both Strengths and Watch-outs (seen on goalkeeper
    Nathan Baxter, "Goals saved above average (52)" in both); the Physical page's Performance view
    uses the same rule."""
    s.goto("/player/9300/4/319", check=True, desc="card: Baxter strengths / watch-outs")
    sw = s.page.locator("#r-sw")
    try:
        sw.locator("div").first.wait_for(timeout=8000)
    except Exception:
        return s.note("card: strengths / watch-outs", skipped="no strengths on this card")
    lists = s.page.evaluate("""() => [...document.querySelectorAll('#r-sw > div')].map(d =>
        d.textContent.replace(/^\\s*(Strengths|Watch-outs)\\s*/, '').split(' · ').map(x => x.replace(/ \\(\\d+\\)$/, '').trim()))""")
    both = set(lists[0]) & set(lists[1]) if len(lists) == 2 else {"lists missing"}
    s.note("card: no metric in both Strengths and Watch-outs", None if not both else str(both))
    sw.scroll_into_view_if_needed()
    path = s.out / "card_baxter_strengths.png"
    sw.screenshot(path=str(path))
    s.shots.append(str(path))


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
    s.goto(base + "?back=%2Fclub-vs-league%3Fcontract%3DOut%26strong%3D1%23cv-rec", check=True,
           desc="card: open from Club vs League One")
    s.note("card: back to Club vs League One keeps its filters",
           None if s.page.locator("#back").get_attribute("href") == "/club-vs-league?contract=Out&strong=1#cv-rec"
           and s.page.locator("#back").inner_text().strip() == "← Back to Club vs League One"
           else f"{s.page.locator('#back').get_attribute('href')!r} {s.page.locator('#back').inner_text()!r}")


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


_PHYS_COLS = ["metric", "all-phases", "in-possession", "out-of-possession", "percentile", "vs-ours"]
_VS_TEXT = re.compile(r"^([+−]\d+|0|—)$")


def card_extra_tables(s, w):
    """'vs ours' in All tracked metrics (#at) and Other physical metrics (#po); the two physical
    tables share one column grid; the Out of possession figure keeps clear of the percentile bar;
    nothing overflows. Element screenshots at 1280 and 1440."""
    for width in (1280, 1440):
        s.page.set_viewport_size({"width": width, "height": 900})
        s.page.wait_for_timeout(250)
        s.page.evaluate("() => ['po-d', 'at-d'].forEach(i => { const d = document.getElementById(i); if (d) d.open = true; })")
        s.page.wait_for_timeout(150)
        for sel, name in (("#at", "All tracked metrics"), ("#po", "Other physical metrics")):
            th = s.page.locator(f"{sel} th.col-vs-ours")
            cells = s.page.evaluate(f"""() => {{
                const t = document.querySelector('{sel} table'); if (!t) return null;
                const i = [...t.tHead.rows[0].cells].findIndex(c => c.classList.contains('col-vs-ours'));
                if (i < 0) return null;
                const pi = [...t.tHead.rows[0].cells].findIndex(c => c.classList.contains('col-percentile'));
                return {{after: i === pi + 1, v: [...t.tBodies[0].rows].map(r => r.cells[i].textContent.trim())}};
            }}""")
            ok = (th.count() and "median" in (th.get_attribute("data-tip") or "") and cells
                  and cells["after"] and cells["v"] and all(_VS_TEXT.match(x) for x in cells["v"])
                  and any(x != "—" for x in cells["v"]))
            s.note(f"card: {name} has 'vs ours' after Percentile, whole signed points @{width}",
                   None if ok else f"column {th.count()} cells {cells and cells['v'][:6]}")
        geo = s.page.evaluate("""cols => {
            const left = sel => { const t = document.querySelector(sel + ' table'); if (!t) return null;
              const h = t.tHead.rows[0].cells, o = {};
              cols.forEach(c => { const x = [...h].find(e => e.classList.contains('col-' + c)); o[c] = x ? x.getBoundingClientRect().left : null; });
              return o; };
            const gaps = sel => [...document.querySelectorAll(sel + ' tbody tr')].map(r => {
              const h = [...r.closest('table').tHead.rows[0].cells];
              const oi = h.findIndex(e => e.classList.contains('col-out-of-possession'));
              const pi = h.findIndex(e => e.classList.contains('col-percentile'));
              if (oi < 0 || pi < 0 || !r.cells[oi]) return null;
              const rg = document.createRange(); rg.selectNodeContents(r.cells[oi]);
              const txt = rg.getBoundingClientRect();
              const pb = r.cells[pi].querySelector('.pb .t');
              const tgt = pb && pb.getBoundingClientRect().width > 0 ? pb : r.cells[pi].querySelector('.pctn, .pb b, .note') || r.cells[pi];
              return Math.round(tgt.getBoundingClientRect().left - txt.right);
            }).filter(v => v != null);
            const over = sel => { const e = document.querySelector(sel); if (!e) return null;
              const card = e.closest('.card').getBoundingClientRect(), t = e.querySelector('table');
              return {scroll: e.scrollWidth - e.clientWidth, past: t ? Math.round(t.getBoundingClientRect().right - card.right) : 0,
                      clipped: [...e.querySelectorAll('td, th')].filter(c => c.scrollWidth > c.clientWidth + 1).map(c => `${c.textContent.trim()} ${c.scrollWidth}>${c.clientWidth}`)}; };
            // owner 2026-11-10: no bars in the physical tables (coloured numbers); in the half-width card the
            // two longest names need 3 lines (7 columns leave ~120px for Metric at 1440)
            const lines = sel => [...document.querySelectorAll(sel + ' tbody td:first-child')].map(td => {
              const rg = document.createRange(); rg.selectNodeContents(td);
              const tops = new Set([...rg.getClientRects()].map(r => Math.round(r.top)));
              return [td.textContent.trim(), tops.size]; }).filter(x => x[1] > 3);
            const pcts = sel => [...document.querySelectorAll(sel + ' tbody td.c-percentile, ' + sel + ' tbody td')].length
              ? {bars: document.querySelectorAll(sel + ' .pb').length, nums: document.querySelectorAll(sel + ' .pctn').length} : null;
            return {ph: left('#ph'), po: left('#po'), gph: gaps('#ph'), gpo: gaps('#po'),
                    lines: [...lines('#ph'), ...lines('#po')], pct: {ph: pcts('#ph'), po: pcts('#po')},
                    o: {ph: over('#ph'), po: over('#po'), at: over('#at')}};
        }""", _PHYS_COLS)
        bad = [c for c in _PHYS_COLS if geo["ph"] is None or geo["po"] is None or geo["ph"][c] is None
               or geo["po"][c] is None or abs(geo["ph"][c] - geo["po"][c]) > 1]
        s.note(f"card: physical tables' columns line up @{width}",
               None if not bad else f"misaligned {bad}: rated {geo['ph']} other {geo['po']}")
        g = (geo["gph"] or []) + (geo["gpo"] or [])
        s.note(f"card: Out of possession keeps >= 16px from the percentile @{width}",
               None if g and min(g) >= 16 else f"gaps {sorted(g)[:5]}")
        s.note(f"card: physical percentiles are coloured numbers, no bars @{width}",
               None if all(v and v["bars"] == 0 and v["nums"] > 0 for v in geo["pct"].values()) else f"{geo['pct']}")
        s.note(f"card: physical metric names take at most 3 lines @{width}",
               None if not geo["lines"] else f"{geo['lines'][:4]}")
        bad = {k: v for k, v in geo["o"].items() if v is None or v["scroll"] > 1 or v["past"] > 1 or v["clipped"]}
        s.note(f"card: physical and all-tracked tables fit their card @{width}",
               None if not bad else f"overflow {bad}")
        s.out.mkdir(parents=True, exist_ok=True)
        for el, name in (("#c-phys", "physical"), ("#c-perf", "all_tracked")):
            if name == "all_tracked" and width != 1440:
                continue
            p = s.out / f"card_{name}_open_{width}.png"
            try:                         # the fixed bar at the foot would cover part of the card
                s.page.evaluate("() => { const b = document.getElementById('infobar'); if (b) b.style.visibility = 'hidden'; }")
                s.page.locator(el).screenshot(path=str(p))
                s.page.evaluate("() => { const b = document.getElementById('infobar'); if (b) b.style.visibility = ''; }")
                s.shots.append(str(p))
            except Exception as e:
                s.note(f"screenshot {p.name}", f"screenshot failed: {e}")
    s.page.set_viewport_size({"width": w, "height": 900})


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
        body = s.page.inner_text("main").lower()      # section headings are small capitals
        s.note(f"report: {label} has its sections",
               None if all(t in body for t in ("composite", "summary", "technical", "physical", "availability"))
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


REPORT_SCOUTED = "/report?player=52132&competition=3&season=318"     # 3 scouts, 4 reports


def report_scout_verdicts(s, w):
    """Owner 2026-11-13: under Playing style, one line per scout (his latest report: name,
    verdict pill, date); in the authored download, never in the data-only one; absent for a
    player nobody has reported on."""
    s.goto(REPORT_SCOUTED, check=True, desc="report: player with scout reports")
    if not _report_ready(s):
        return s.note("report: scouted player draws", "report body never shown")
    card = s.page.locator("#c-scouts")
    lines = s.page.locator("#c-scouts .rp-scout")
    s.note("report: Scout verdicts block shown", None if card.is_visible() else "block hidden")
    texts = lines.all_inner_texts()
    scouts = [t.split("\n")[0].strip() for t in texts]
    s.note("report: one line per scout", None if texts and len(scouts) == len(set(scouts)) else texts)
    s.note("report: each line has a verdict pill and a date",
           None if texts and lines.count() == s.page.locator("#c-scouts .rp-scout .pill").count()
           and all(re.search(r"\d{1,2} [A-Z][a-z]{2} \d{4}", t) for t in texts) else texts)
    if card.is_visible() and s.page.locator("#c-style").is_visible():
        a, b = s.page.locator("#c-style").bounding_box(), card.bounding_box()
        s.note("report: block sits under Playing style",
               None if b["y"] >= a["y"] + a["height"] - 1 and abs(b["x"] - a["x"]) < 2 else f"{a} / {b}")
    card.scroll_into_view_if_needed()
    s.shot("scout_verdicts", w, full=True)
    name, text = _report_file(s, "#rp-dl", "report: Download report (scouted player)")
    s.note("report: authored file has the scout verdicts",
           None if name and 'id="c-scouts"' in text and all(x in text for x in scouts) else f"{name}: missing")
    name, text = _report_file(s, "#rp-dl-data", "report: Download data-only report (scouted player)")
    s.note("report: data-only file has no scout verdicts",
           None if name and 'id="c-scouts"' not in text and "Scout verdicts" not in text
           else f"{name}: verdicts present")
    s.goto("/report?player=47357&competition=5&season=319", check=False)    # nobody has reported on him
    _report_ready(s)
    s.note("report: no scout reports, no block", None if s.page.locator("#c-scouts").is_hidden() else "block shown")


def report_empty_search_lists(s, w):
    """Owner 2026-11-13: no Position control; the empty box lists EVERY player of the season A-Z
    (name · position · club · league), drawn as it scrolls; typing filters the same list;
    picking one opens his report; position= in a URL is dropped."""
    s.goto(REPORT_BASE, check=False)
    _report_ready(s)
    s.note("report: no Position control", None if not s.page.locator("#rp-position").count()
           and s.control("Position") is None else "Position control still on the page")
    box = s.page.locator("#rp-search")
    t0 = time.perf_counter()
    s.step("report: focus the empty search box", lambda p: box.click(timeout=3000))
    res = s.page.locator("#rp-results [data-action=pick]")
    try:
        res.first.wait_for(timeout=6000)
    except Exception:
        return s.note("report: empty box lists players", "no list")
    secs = time.perf_counter() - t0
    s.note("report: the list opens fast", None if secs < 3.0 else f"{secs:.2f}s")
    names = [t.split(" · ")[0] for t in res.all_inner_texts()]
    s.note("report: empty box lists players (a page at a time)", None if 100 <= len(names) <= 300 else f"{len(names)} rows")
    import unicodedata
    plain = lambda n: "".join(c for c in unicodedata.normalize("NFKD", n) if c.isalnum()).casefold()  # noqa: E731
    s.note("report: list is A-Z", None if [plain(n) for n in names] == sorted(plain(n) for n in names) else names[:6])
    parts = res.first.inner_text().split(" · ")
    s.note("report: row reads name · position · club · league", None if len(parts) == 4 else res.first.inner_text())
    total = s.page.evaluate("async () => (await (await fetch('/api/report/players?season=318')).json()).rows.length")
    s.note("report: the season's whole list is there", None if total >= 1000 else f"{total} players")
    before = res.count()
    s.step("report: scroll the list", lambda p: (p.evaluate("() => { const o = document.querySelector('#rp-results'); o.scrollTop = o.scrollHeight; }"),
                                                 p.wait_for_timeout(300)))
    s.note("report: scrolling draws more", None if res.count() > before else f"{before} -> {res.count()}")
    s.shot("empty_search_list", w)
    s.step("report: type a winger's name", lambda p: box.fill("Markanday", timeout=3000))
    try:
        s.page.wait_for_function("() => { const b = [...document.querySelectorAll('#rp-results [data-action=pick]')];"
                                 " return b.length && b.every(x => x.textContent.includes('Markanday')); }", timeout=3000)
        s.note("report: typing filters the list", None)
    except Exception:
        s.note("report: typing filters the list", s.page.inner_text("#rp-results")[:120])
    s.step("report: type a club", lambda p: box.fill("Leyton Orient", timeout=3000))
    s.note("report: typing matches club too", None if res.count() >= 5 else f"{res.count()} rows")
    s.step("report: type a name again", lambda p: box.fill("Markanday", timeout=3000))
    pick = s.page.locator("#rp-results [data-action=pick]", has_text="Markanday").first
    s.step("report: pick him", lambda p: pick.click(timeout=3000))
    _report_ready(s)
    s.page.wait_for_timeout(500)
    s.note("report: picking opens his report", None if "Markanday" in s.page.inner_text("#h-name")
           and "player=" in s.page.url else s.page.inner_text("#h-name"))
    s.goto("/report?position=Goalkeeper", check=False)
    s.page.wait_for_timeout(500)
    s.note("report: position= in a URL is dropped", None if "position=" not in s.page.url else s.page.url)


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
    _clear_drafts(s)


def _clear_drafts(s):
    """Report drafts live in this browser (owner 2026-11-13); a scenario's own draft must not
    reopen in the next one."""
    try:
        s.page.wait_for_timeout(500)          # a save still queued (300 ms) lands first
        s.page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('lofc.report.draft.'))"
                        ".forEach(k => localStorage.removeItem(k))")
    except Exception:
        pass


def _png(w=40, h=50):
    """A plain red PNG: the photo the harness chooses (any image the browser can decode)."""
    import struct
    import zlib
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    raw = b"".join(b"\x00" + b"\xc8\x10\x2e" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


_PHOTO_PNG = _png()
_REPORT_FILE_IDS = ('id="h-name"', 'id="c-verdict"', 'id="c-summary"', 'id="c-tech"', 'id="c-phys"',
                    'id="p-avail"')


def _report_file(s, button, desc):
    """Click a download button; (filename, text) of the file, or (None, error)."""
    try:
        with s.page.expect_download(timeout=8000) as dl:
            s.step(desc, lambda p: p.locator(button).click(timeout=3000))
        d = dl.value
        return d.suggested_filename, open(d.path(), encoding="utf-8").read()
    except Exception as e:
        return None, str(e).splitlines()[0][:100]


def _report_file_problems(name, text, suffix):
    """The file is the on-screen layout, self-contained: no old-template marker, nothing
    fetched from the site, no form, no scripts."""
    if name is None:
        return f"no download: {text}"
    bad = [] if name.endswith(suffix) and "Markanday" in name else [f"name {name}"]
    bad += [f"missing {i}" for i in _REPORT_FILE_IDS if i not in text]
    bad += [f"has {m}" for m in ("Recruitment Report", "/static/", "<script", "<link", 'id="rp-form"', 'class="card',
                                 "rp-photo-file", "Add photo", "Download") if m in text]
    if not text.lower().startswith("<!doctype html"):
        bad.append("not a document")
    return "; ".join(bad) or None


def report_downloads(s, w):
    """Both downloads are the preview's own layout in one self-contained file; the photo is in
    both, the writer's availability rows only in the authored one."""
    s.goto(REPORT_BASE, check=False)
    _report_ready(s)
    s.note("report: photo box on screen", None if s.page.locator("#rp-photo").is_visible()
           and "Add photo" in s.page.inner_text("#rp-photo") else "no photo box")
    name, text = _report_file(s, "#rp-dl-data", "report: Download data-only report (no photo)")
    s.note("report: data-only file is the preview layout", _report_file_problems(name, text, "_data_only_report.html"))
    if name:
        s.note("report: data-only file says Data only, no empty photo box",
               None if "Data only" in text and 'id="rp-photo"' not in text else "stamp or empty photo box")
    s.step("report: choose a photo", lambda p: (p.set_input_files(
        "#rp-photo-file", files=[{"name": "p.png", "mimeType": "image/png", "buffer": _PHOTO_PNG}]),
        p.wait_for_timeout(500)))
    src = s.page.locator("#rp-photo-img").get_attribute("src") or ""
    s.note("report: photo shown, downscaled in the browser",
           None if src.startswith("data:image/jpeg") and s.page.locator("#rp-photo-img").is_visible() else src[:40])
    pw = (s.page.locator("#rp-photo-img").bounding_box() or {}).get("width", 0)
    s.note("report: photo at least 150px wide", None if pw >= 150 else f"{pw:.0f}px")
    s.step("report: open the form", lambda p: p.locator("#rp-write").click(timeout=3000))
    s.step("report: add an availability row", lambda p: p.locator("#f-avail-add").click(timeout=3000))
    row = s.page.locator("#f-avail .rp-avrow").last
    if not row.count():
        return s.note("report: availability row", "no row added")
    s.step("report: fill the row", lambda p: (
        row.locator("[data-av=dates]").fill("Oct–Dec 2025", timeout=3000),
        row.locator("[data-av=injury]").fill("Hamstring tear", timeout=3000),
        row.locator("[data-av=missed]").fill("6", timeout=3000), p.wait_for_timeout(300)))
    av = s.page.inner_text("#p-avail")
    s.note("report: row in the availability section", None if "Hamstring tear" in av and "Oct–Dec 2025" in av else av[:120])
    s.page.evaluate("window.scrollTo(0, 0)")
    s.shot("photo_and_availability", w, full=True)
    name, text = _report_file(s, "#rp-dl", "report: Download report")
    s.note("report: authored file is the preview layout", _report_file_problems(name, text, "_report.html"))
    if name:
        s.note("report: authored file has the photo and the row",
               None if "data:image/jpeg" in text and "Hamstring tear" in text else "photo or row missing")
        out = s.out / f"{s.cur_page}_downloaded_report.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        fresh = s.page.context.new_page()
        asked = []
        fresh.on("request", lambda r: asked.append(r.url) if not r.url.startswith(("data:", "about:")) else None)
        try:
            fresh.set_viewport_size({"width": w, "height": 900})
            fresh.set_content(text, wait_until="load")      # as opened from disk: no site
            p = s.out / f"{s.cur_page}_downloaded_file_{w}.png"
            fresh.screenshot(path=str(p), full_page=True)
            s.shots.append(str(p))
            s.note("report: file opens without the site", None if not asked else ", ".join(asked)[:120])
            fresh.emulate_media(media="print")
            pdf = fresh.pdf(format="A4", print_background=True, prefer_css_page_size=True)
            pages = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
            box = re.search(rb"/MediaBox\s*\[\s*0 0 ([\d.]+) ([\d.]+)", pdf)
            land = bool(box) and float(box.group(1)) > float(box.group(2))
            s.note("report: file prints on one landscape A4 page",
                   None if pages == 1 and land else f"{pages} pages, landscape={land}")
            # owner 2026-11-13: the sheet fills the printable width (A4 landscape inside 8 mm
            # margins = 1062 CSS px), not ~2/3 of it
            m = re.search(r"@media print\{.*?main\{width:(\d+)px[^}]*zoom:([\d.]+)", text, re.S)
            frac = int(m.group(1)) * float(m.group(2)) / 1062 if m else 0
            got = fresh.evaluate("() => document.querySelector('main').getBoundingClientRect().width") / 1062
            s.note("report: printed sheet fills the page width (>= 95%)",
                   None if frac >= 0.95 and got >= 0.95 else f"{frac:.0%} by its CSS, {got:.0%} measured")
        except Exception as e:
            s.note("report: open the downloaded file", str(e).splitlines()[0][:100])
        finally:
            fresh.close()
    name, text = _report_file(s, "#rp-dl-data", "report: Download data-only report (photo)")
    if name:
        s.note("report: data-only file has the photo, not the writer's rows",
               None if "data:image/jpeg" in text and "Hamstring tear" not in text else "photo missing or rows present")
    s.step("report: remove the photo", lambda p: p.locator("#rp-photo-del").click(timeout=3000))
    s.note("report: photo removed", None if s.page.locator("#rp-photo-img").is_hidden() else "still shown")
    _clear_drafts(s)


_SHEET_JS = """() => {
  const sh = [...document.querySelectorAll('#v-report .rp-sheet')];
  if (sh.length !== 1) return {sheets: sh.length};
  const S = sh[0], b = S.getBoundingClientRect(), page = getComputedStyle(document.body).backgroundColor;
  const vis = e => !e.closest('[hidden]') && e.getBoundingClientRect().width > 0;
  const inner = [...S.querySelectorAll('*')].filter(vis);
  const rows = [...S.querySelectorAll('.rp-top, .rp-bottom')].map(r => [...r.children].filter(vis)
    .map(c => { const q = c.getBoundingClientRect(); return [Math.round(q.top), Math.round(q.bottom)]; }));
  const sc = S.querySelector('.rp-score');
  const cb = S.querySelector('.rp-cblock'), br = [...S.querySelectorAll('.rp-brow')];
  const comp = cb && br.length ? [Math.round(cb.getBoundingClientRect().top - br[0].getBoundingClientRect().top),
    Math.round(cb.getBoundingClientRect().bottom - br[br.length - 1].getBoundingClientRect().bottom)] : null;
  return {sheets: 1, comp, bordered: getComputedStyle(S).borderLeftStyle !== 'none',
    grey: inner.filter(e => getComputedStyle(e).backgroundColor === page).map(e => e.id || e.className).slice(0, 4),
    cards: S.querySelectorAll('.card').length,
    rows, score: sc ? parseFloat(getComputedStyle(sc).fontSize) : null,
    over: inner.filter(e => { const q = e.getBoundingClientRect(); return q.right > b.right + 1 || q.left < b.left - 1; })
      .map(e => e.id || e.className).slice(0, 4),
    hscroll: document.documentElement.scrollWidth > innerWidth + 1};
}"""


# owner 2026-11-13: Scout verdicts' heading level with Availability's; both blocks end level;
# Playing style stays at the top
_VERDICTS_JS = """() => { const r = s => document.querySelector(s) && document.querySelector(s).getBoundingClientRect();
  const sc = document.querySelector('#c-scouts:not([hidden]) h2');
  if (!sc || !r('#c-avail h2')) return null;
  return {head: sc.getBoundingClientRect().top - r('#c-avail h2').top, end: r('#c-scouts').bottom - r('#c-avail').bottom,
          style: r('#c-style').top - r('#c-phys').top}; }"""


def _verdicts_level(s, page, where):
    m = page.evaluate(_VERDICTS_JS)
    if m is None:
        return s.note(f"report: scout verdicts line up ({where})", skipped="no scout verdicts shown")
    s.note(f"report: scout verdicts line up with Availability ({where})",
           None if abs(m["head"]) <= 2 and abs(m["end"]) <= 2 and abs(m["style"]) <= 2 else m)


def report_one_sheet(s, w):
    """Owner 2026-11-13: the report is ONE white bordered sheet (the wide layout): no cards and
    no page grey inside it; the two columns of each row share top and bottom edges; the
    composite is a large number; nothing overflows, at every width."""
    for width in s.widths:
        s.page.set_viewport_size({"width": width, "height": 900})
        for label, path in (("winger", REPORT_BASE), ("scouted", REPORT_SCOUTED)):
            s.goto(path, check=True, desc=f"report: sheet {label} @{width}")
            if not _report_ready(s):
                s.note(f"report: sheet {label} @{width}", "report body never shown")
                continue
            s.page.wait_for_timeout(300)
            m = s.page.evaluate(_SHEET_JS)
            if m.get("sheets") != 1:
                s.note(f"report: one sheet @{width}", f"{m.get('sheets')} sheets")
                continue
            s.note(f"report: one bordered sheet, no cards or grey inside ({label} @{width})",
                   None if m["bordered"] and not m["cards"] and not m["grey"] else m)
            bad = [r for r in m["rows"] if len(r) == 2 and (abs(r[0][0] - r[1][0]) > 2 or abs(r[0][1] - r[1][1]) > 2)]
            s.note(f"report: row columns align ({label} @{width})", None if not bad else bad)
            s.note(f"report: composite is a large number ({label} @{width})",
                   None if (m["score"] or 0) >= 44 else m["score"])
            s.note(f"report: composite block level with the four rows ({label} @{width})",
                   None if m["comp"] and all(abs(d) <= 2 for d in m["comp"]) else m["comp"])
            s.note(f"report: nothing overflows the sheet ({label} @{width})",
                   None if not m["over"] and not m["hscroll"] else m)
            if label == "scouted":
                _verdicts_level(s, s.page, f"@{width}")
                if width == 1440:          # the downloaded file, on screen and printed
                    name, text = _report_file(s, "#rp-dl", "report: download (scouted)")
                    if not name:
                        s.note("report: download (scouted)", text)
                    else:
                        fresh = s.page.context.new_page()
                        try:
                            fresh.set_viewport_size({"width": 1440, "height": 900})
                            fresh.set_content(text, wait_until="load")
                            _verdicts_level(s, fresh, "downloaded file")
                            fresh.emulate_media(media="print")
                            _verdicts_level(s, fresh, "downloaded file, printed")
                        finally:
                            fresh.close()
        if width == 1440:
            s.shot("one_sheet", width, full=True)
    s.page.set_viewport_size({"width": w, "height": 900})


_DRAFT_RULES_JS = """async (url) => {
  const m = await import(url);
  const mem = {}, big = {getItem: k => mem[k] ?? null, removeItem: k => { delete mem[k]; },
    setItem: (k, v) => { if (v.includes('data:image')) throw new DOMException('full', 'QuotaExceededError'); mem[k] = v; }};
  const ids = {player: 1, competition: 2, season: 3};
  const out = {key: m.draftKey(ids)};
  out.dropped = m.writeDraft(big, ids, {text: {summary: 'x'}, photo: 'data:image/jpeg;base64,AA'});
  out.kept = JSON.parse(mem[out.key] || 'null');
  out.empty = m.writeDraft(big, ids, {text: {summary: '  '}, avail: [], photo: null});
  out.gone = !(out.key in mem);
  out.nostore = m.writeDraft(null, ids, {text: {summary: 'x'}});
  out.read = m.readDraft(null, ids);
  return out;
}"""


def report_draft(s, w):
    """Owner 2026-11-13: the writer's draft (text, availability rows, photo) is kept in this
    browser per player-season and comes back after leaving the page; Clear draft empties it."""
    s.goto(REPORT_BASE, check=False)
    if not _report_ready(s):
        return s.note("report: draft", "report body never shown")
    _clear_drafts(s)
    s.goto(REPORT_BASE, check=False)
    _report_ready(s)
    src = s.page.evaluate("[...document.scripts].map(x => x.src).find(x => /report\\.js/.test(x)) || ''")
    if src:
        r = s.page.evaluate(_DRAFT_RULES_JS, src.replace("report.js", "report_draft.js"))
        s.note("report: draft key", None if r["key"] == "lofc.report.draft.1-2-3" else r["key"])
        s.note("report: photo too large: saved without it, with a note",
               None if r["dropped"] == "Photo not kept — too large to save" and r["kept"]
               and r["kept"]["photo"] is None and r["kept"]["text"]["summary"] == "x" else r)
        s.note("report: an empty draft is removed", None if r["empty"] == "" and r["gone"] else r)
        s.note("report: no storage: page still works", None if r["nostore"] == "unsaved" and r["read"] is None else r)
    if s.page.locator("#rp-form").is_hidden():
        s.step("report: open the form", lambda p: p.locator("#rp-write").click(timeout=3000))
    ta = s.page.locator('#f-text textarea[data-key="summary"]')
    s.step("report: draft: type a summary", lambda p: ta.fill("Draft kept: sharp in the box.", timeout=3000))
    s.step("report: draft: add a row", lambda p: p.locator("#f-avail-add").click(timeout=3000))
    row = s.page.locator("#f-avail .rp-avrow").last
    s.step("report: draft: fill the row", lambda p: (
        row.locator("[data-av=dates]").fill("Jan–Feb 2026", timeout=3000),
        row.locator("[data-av=injury]").fill("Ankle sprain", timeout=3000)))
    s.step("report: draft: choose a photo", lambda p: (p.set_input_files(
        "#rp-photo-file", files=[{"name": "p.png", "mimeType": "image/png", "buffer": _PHOTO_PNG}]),
        p.wait_for_timeout(900)))
    s.goto("/players", check=False)
    s.goto(REPORT_BASE, check=False)
    _report_ready(s)
    s.page.wait_for_timeout(900)
    got = {"summary": ta.input_value() if ta.count() else None,
           "row": s.page.locator("#f-avail [data-av=injury]").first.input_value()
           if s.page.locator("#f-avail [data-av=injury]").count() else None,
           "photo": (s.page.locator("#rp-photo-img").get_attribute("src") or "")[:15]}
    s.note("report: draft restored after leaving the page",
           None if got["summary"] == "Draft kept: sharp in the box." and got["row"] == "Ankle sprain"
           and got["photo"].startswith("data:image/jpeg") else got)
    s.note("report: restored draft is in the preview",
           None if "sharp in the box" in s.page.inner_text("#c-summary") and "Ankle sprain" in s.page.inner_text("#p-avail")
           else "preview not redrawn")
    s.shot("draft_restored", w, full=True)
    # owner 2026-11-13: Clear draft asks first, inline: "Clear your draft? Yes · No"
    s.step("report: Clear draft (asks)", lambda p: p.locator("#rp-draft-clear").click(timeout=3000))
    s.note("report: Clear draft asks inline", None if s.page.locator("#rp-draft-confirm").is_visible()
           and "Clear your draft?" in s.page.inner_text("#rp-draft-confirm")
           and s.page.locator("#rp-draft-clear").is_hidden() else "no inline question")
    s.step("report: No keeps the draft", lambda p: p.locator("#rp-draft-no").click(timeout=3000))
    s.note("report: No keeps the draft", None if ta.input_value() == "Draft kept: sharp in the box."
           and s.page.locator("#rp-draft-clear").is_visible() and s.page.locator("#rp-draft-confirm").is_hidden()
           else ta.input_value())
    s.step("report: Clear draft (asks again)", lambda p: p.locator("#rp-draft-clear").click(timeout=3000))
    s.step("report: Yes clears", lambda p: (p.locator("#rp-draft-yes").click(timeout=3000), p.wait_for_timeout(600)))
    left = s.page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('lofc.report.draft.'))")
    s.note("report: Clear draft empties the form, rows, photo and storage",
           None if ta.input_value() == "" and not s.page.locator("#f-avail .rp-avrow").count()
           and s.page.locator("#rp-photo-img").is_hidden() and not left else left)
    s.goto(REPORT_BASE, check=False)
    _report_ready(s)
    s.page.wait_for_timeout(500)
    s.note("report: nothing comes back after Clear draft",
           None if s.page.locator("#rp-form").is_hidden() and s.page.locator("#rp-photo-img").is_hidden()
           else "draft came back")
    _clear_drafts(s)


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


def compare_remembers_players(s, w):
    """R4a: two players chosen, away to Players, back by the nav link: the same two players."""
    s.goto("/compare?season=318&position=Winger&a=39154-5&b=150216-5", check=False)
    heads = _cmp_heads(s)
    s.step("compare: to Players by the nav", lambda p: p.locator("nav a[href='/players']").click(timeout=3000),
           expect_nav=True)
    s.step("compare: back by the nav", lambda p: p.locator("nav a[href='/compare']").click(timeout=3000),
           expect_nav=True)
    try:
        s.page.wait_for_function("() => document.querySelectorAll('#cmp-sum thead a.nm').length >= 2", timeout=8000)
    except Exception:
        pass
    s.note("compare: same players after the nav", None if heads and _cmp_heads(s) == heads
           else f"{heads} -> {_cmp_heads(s)}")
    s.note("compare: URL restored", None if "a=39154-5" in s.page.url and "b=150216-5" in s.page.url else s.page.url)
    s.goto("/compare?season=318&position=Winger&a=47739-5&b=39154-5", check=False)
    s.note("compare: explicit URL wins", None if "a=47739-5" in s.page.url else s.page.url)


def compare_download(s, w):
    """R4b: one self-contained file of the screen; two players: no Player C, no controls."""
    s.goto("/compare?season=318&position=Winger&a=39154-5&b=150216-5", check=False)
    heads = _cmp_heads(s)
    try:
        with s.page.expect_download(timeout=8000) as dl:
            s.step("compare: Download", lambda p: p.locator("#cmp-dl").click(timeout=3000))
        d = dl.value
        name, text = d.suggested_filename, open(d.path(), encoding="utf-8").read()
        import shutil
        s.out.mkdir(parents=True, exist_ok=True)
        shutil.copy(d.path(), s.out / name)
    except Exception as e:
        return s.note("compare: download", f"no download: {str(e).splitlines()[0][:100]}")
    bad = [] if re.fullmatch(r"Compare_[A-Za-z0-9_]+_v_[A-Za-z0-9_]+_2025_26\.html", name) else [f"name {name}"]
    bad += [f"has {m!r}" for m in ("Player C", "/static/", "<script", "<link", "<select", "<input",
                                   "<button", 'id="filters"', "href=") if m in text]
    bad += [f"missing {m!r}" for m in ('id="cmp-sum"', "<svg", "Performance profile", "Packing zones")
            if m not in text]
    bad += [f"missing {h!r}" for h in heads if h not in text]
    if not text.lower().startswith("<!doctype html"):
        bad.append("not a document")
    s.note("compare: download is the screen, two players, no controls", "; ".join(bad) or None)
    if text and name:
        page = s.page.context.new_page()
        try:
            page.set_viewport_size({"width": w, "height": 900})
            page.set_content(text)
            page.screenshot(path=str(s.out / "compare_download.png"), full_page=True)
            cols = page.evaluate("() => document.querySelectorAll('#cmp-sum thead th').length")
            s.note("compare: file has two player columns", None if cols == 3 else f"{cols - 1} columns")
        finally:
            page.close()


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


def scout_squad_role(s, w):
    """Squad role (owner 2026-11-13): the sheet's values, narrows the list with the caption's
    count, goes in the URL, All restores, combines with another filter."""
    s.goto(SR_PATH, check=False)
    sel = _need(s, "Squad role")
    if sel is None:
        return
    opts = sel.locator("option").all_inner_texts()
    want = ["All", "Core (>70% of Minutes)", "Support (21-69% of Minutes)", "Fringe (<20% of Minutes)",
            "Emerging Talent (Ready in Next 12-18 Months)", "Below the Required Standard for LOFC"]
    s.note("scout reports: Squad role options", None if opts == want else opts)
    before = _sr_rows(s).count()
    cap = lambda: s.page.inner_text("#sr-cap")
    s.step("scout reports: Squad role = Core", lambda p: (sel.select_option(value="Core (>70% of Minutes)", timeout=3000),
                                                           p.wait_for_timeout(600)))
    after = _sr_rows(s).count()
    s.note("scout reports: squad role narrows", None if 0 < after < before else f"{before} -> {after}")
    s.note("scout reports: caption counts the filtered rows",
           None if cap().startswith(f"{after:,} of ") else cap())
    s.note("scout reports: squad role in the URL", None if "role=Core" in s.page.url else s.page.url)
    s.shot("squad_role_core", w)
    v = _need(s, "Verdict")
    if v is not None:
        s.step("scout reports: plus Verdict = Sign", lambda p: (v.select_option(value="Sign", timeout=3000),
                                                                 p.wait_for_timeout(600)))
        both = _sr_rows(s).count()
        s.note("scout reports: squad role combines with Verdict", None if both <= after and "role=Core" in s.page.url
               and "verdict=Sign" in s.page.url else f"{both} rows / {s.page.url}")
        s.step("scout reports: Verdict = All", lambda p: (v.select_option(value="All", timeout=3000),
                                                           p.wait_for_timeout(600)))
    s.step("scout reports: Squad role = All", lambda p: (sel.select_option(value="All", timeout=3000),
                                                          p.wait_for_timeout(600)))
    s.note("scout reports: All restores every row", None if _sr_rows(s).count() == before and "role=" not in s.page.url
           else f"{_sr_rows(s).count()} rows / {s.page.url}")
    s.goto(SR_PATH + "?role=Fringe%20(%3C20%25%20of%20Minutes)", check=True, desc="scout reports: squad role URL")
    s.note("scout reports: URL opens the squad role", None if sel.input_value() == "Fringe (<20% of Minutes)"
           and 0 < _sr_rows(s).count() < before else sel.input_value())


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
    cnt = re.match(r"^(\d+) ", s.page.inner_text("#cv-count"))
    s.note("club vs league: every player listed (no cap)", None if cnt and rows.count() == int(cnt.group(1)) > 0 else f"{rows.count()} rows / {s.page.inner_text('#cv-count')}")
    # Leagues picker: default three, a checklist of every league, remembered on this computer
    btn = s.page.locator("#cv-leagues")
    s.note("club vs league: default leagues", None if btn.inner_text().startswith("3 selected: League One, Championship, League Two") else btn.inner_text())
    s.note("club vs league: one tab per selected league", None if s.page.locator("#cv-tabs button[data-l]").count() == 3 else "not 3 tabs")
    cap = s.page.inner_text("#cv-count")
    s.note("club vs league: caption names the league", None if re.match(r"^\d+ centre backs above .+ · ranked within League One$", cap) else cap)
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
    nw = s.page.locator("#cv-rec-t th[data-sort^='w']").count()
    s.note("club vs league: every heading sortable (owner 2026-11-13)",
           None if heads.count() == 9 + nw else f"{heads.count()} sortable headings, {nw} metric columns")
    s.note("club vs league: no tag column", None if "Strong where we are weak" not in s.page.inner_text("#cv-rec-t") else "old column")
    col = s.page.locator("#cv-rec-t th[data-sort='w0']")
    if col.count():
        s.step("club vs league: sort by first weakness", lambda p: col.click(timeout=3000))
        vals = s.page.locator("#cv-rec-t tbody tr td:nth-child(11)").all_inner_texts()
        s.note("club vs league: weakness columns are plain numbers", None if all(re.match(r"^(\d+|—)$", v.strip()) for v in vals) else str(vals[:5]))
        nums = [int(re.sub(r"\D", "", v)) for v in vals if re.search(r"\d", v)]
        s.note("club vs league: weakness sort is best first", None if nums == sorted(nums, reverse=True) else str(nums))
        s.note("club vs league: sort in the URL", None if "sort=w0" in s.page.url else s.page.url)
        s.step("club vs league: back to Overall", lambda p: s.page.locator("#cv-rec-t th[data-sort='ov']").click(timeout=3000))
    s.step("club vs league: Top-6 level only", lambda p: s.page.locator("#cv-top6only").click(timeout=3000))
    s.page.wait_for_timeout(300)
    s.note("club vs league: top6 filter in the URL", None if "top6=1" in s.page.url else s.page.url)
    rows = s.page.locator("#cv-rec-t tbody tr")
    badges = s.page.locator("#cv-rec-t tbody tr .cv-t6")
    s.note("club vs league: Top-6 level only keeps badged players", None if rows.count() == badges.count() else f"{rows.count()} rows, {badges.count()} badges")
    s.step("club vs league: Top-6 level off", lambda p: s.page.locator("#cv-top6only").click(timeout=3000))
    s.shot("weakness_columns", w)
    # owner 2026-11-10: a player opened from "Players who could close the gap" comes back to
    # this section with every filter still set (contract, "Strong on 2+", league, ...)
    s.step("club vs league: set a contract filter", lambda p: s.page.select_option("#cv-contract", index=1))
    s.page.wait_for_timeout(1200)
    s.step("club vs league: Strong on 2+ on", lambda p: s.page.locator("#cv-strong").click(timeout=3000))
    s.page.wait_for_timeout(1200)
    before = s.page.url
    names = s.page.locator("#cv-rec-t a.pname")
    if names.count() == 0:
        return s.note("club vs league: back from a player", skipped="no players under these filters")
    _go_card(s, "club vs league: open a player by name", lambda: names.first.click(timeout=3000))
    s.page.wait_for_selector("#back", timeout=8000)
    s.note("club vs league: player page names the way back",
           None if s.page.inner_text("#back").strip() == "← Back to Club vs League One" else s.page.inner_text("#back"))
    s.goto(s.page.locator("#back").get_attribute("href"), check=True, desc="club vs league: back from the player")
    s.page.wait_for_selector("#cv-rec-t tbody tr", timeout=8000)
    s.page.wait_for_timeout(800)
    s.note("club vs league: filters kept after coming back",
           None if ("contract=" in s.page.url and "strong=1" in s.page.url) else f"{before} -> {s.page.url}")
    s.note("club vs league: lands on the players section", None if s.page.evaluate(
        "() => { const r = document.getElementById('cv-rec').getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; }") else "not scrolled to it")


def _cv_gc(s):
    """The Gap closed cells of the shown list: ints, or None for "—"."""
    vals = [v.strip().rstrip("%") for v in s.page.locator("#cv-rec-t tbody td.cv-gc").all_inner_texts()]
    return vals, [None if v == "—" else int(v) for v in vals if re.fullmatch(r"\d+|—", v)]


def _cv_cols(s):
    return [t.replace("▼", "").replace("▲", "").strip()
            for t in s.page.locator("#cv-rec-t th[data-sort^='w']").all_inner_texts()]


def club_vs_league_gap_closed(s, w):
    """Owner 2026-11-13: the Gap closed column (0-100 or —), Rank by Gap closed, the Metric
    columns picker (add / remove / reset, kept in the URL) and the way back from a player."""
    s.page.evaluate("() => { try { localStorage.removeItem('lofc.cvl.leagues'); } catch (e) {} }")
    s.goto("/club-vs-league?group=Full%20Back", check=True, desc="club vs league: Full Back")
    s.page.wait_for_selector("#cv-rec-t tbody tr", timeout=15000)
    th = s.page.locator("#cv-rec-t th[data-sort='gc']")
    s.note("club vs league: Gap closed % column", None if th.count() == 1 and th.inner_text().replace("▼", "").replace("▲", "").strip() == "Gap closed %" else th.inner_text() if th.count() else "missing")
    order = s.page.evaluate("() => [...document.querySelectorAll('#cv-rec-t thead th')].map(t => t.dataset.sort ?? t.textContent.trim())")
    s.note("club vs league: Gap closed after vs our best", None if "gc" in order and order.index("gc") == order.index("vb") + 1 else str(order))
    tip = th.get_attribute("data-tip") or ""
    s.note("club vs league: Gap closed help", None if "How much of our player's shortfall vs the top 6 he would make up. 100% = all of it." in tip else tip)
    cells = [v.strip() for v in s.page.locator("#cv-rec-t tbody td.cv-gc").all_inner_texts()]
    s.note("club vs league: Gap closed cells show %", None if cells and all(re.fullmatch(r"\d+%|—", v) for v in cells) else str(cells[:6]))
    raw, gc = _cv_gc(s)
    s.note("club vs league: Gap closed is 0-100 or —", None if raw and len(gc) == len(raw)
           and all(v is None or 0 <= v <= 100 for v in gc) else str(raw[:6]))
    s.step("club vs league: rank by Gap closed", lambda p: s.page.locator("#cv-rank button[data-r='gap']").click(timeout=3000))
    s.page.wait_for_timeout(800)
    s.note("club vs league: rank in the URL", None if "rank=gap" in s.page.url else s.page.url)
    raw, gc = _cv_gc(s)
    nums = [v for v in gc if v is not None]
    tail_ok = all(v is None for v in gc[len(nums):])
    s.note("club vs league: ranked by Gap closed, highest first", None if nums == sorted(nums, reverse=True) and tail_ok else str(raw))
    s.note("club vs league: Rank by switch shows Gap closed", None if s.page.locator("#cv-rank button.on").inner_text() == "Gap closed" else "not marked")
    s.page.evaluate("() => window.scrollTo(0, document.querySelector('#cv-rec').getBoundingClientRect().top + scrollY - 10)")
    s.shot("gap_closed_ranked", w)
    # the metric columns picker
    before = _cv_cols(s)
    chips = s.page.locator("#cv-cols .fchip")
    s.note("club vs league: one chip per metric column", None if chips.count() == len(before) else f"{chips.count()} chips, {len(before)} columns")
    s.note("club vs league: reset hidden by default", None if s.page.locator("#cv-reset").is_hidden() else "shown")
    if s.page.locator("#cv-add option").count() < 2:
        return s.note("club vs league: metric picker", skipped="no metric to add")
    added = s.page.locator("#cv-add option").nth(1).inner_text().strip()
    s.step("club vs league: add a metric column", lambda p: s.page.select_option("#cv-add", index=1, timeout=3000))
    s.page.wait_for_timeout(800)
    after = _cv_cols(s)
    s.note("club vs league: added column shown", None if after == before + [added] else f"{before} -> {after}")
    s.note("club vs league: columns in the URL", None if "cols=" in s.page.url else s.page.url)
    s.note("club vs league: reset shown after a change", None if s.page.locator("#cv-reset").is_visible() else "hidden")
    raw, gc = _cv_gc(s)
    note = s.page.locator("#cv-cols-note")
    s.note("club vs league: Gap closed with chosen columns is 0-100 or —", None if raw and len(gc) == len(raw)
           and all(v is None or 0 <= v <= 100 for v in gc) and (any(v is not None for v in gc) or note.is_visible()) else str(raw[:6]))
    if before:
        s.step("club vs league: remove the first column", lambda p: s.page.locator("#cv-cols .fchip button").first.click(timeout=3000))
        s.page.wait_for_timeout(800)
        now = _cv_cols(s)
        s.note("club vs league: removed column gone", None if now == after[1:] else f"{after} -> {now}")
        s.note("club vs league: URL follows the columns", None if "cols=" in s.page.url else s.page.url)
    s.page.evaluate("() => window.scrollTo(0, document.querySelector('#cv-rec').getBoundingClientRect().top + scrollY - 10)")
    s.shot("metric_picker_changed", w)
    url = s.page.url
    names = s.page.locator("#cv-rec-t a.pname")
    if names.count():
        _go_card(s, "club vs league: open a player (chosen columns)", lambda: names.first.click(timeout=3000))
        s.page.wait_for_selector("#back", timeout=8000)
        s.goto(s.page.locator("#back").get_attribute("href"), check=True, desc="club vs league: back with chosen columns")
        s.page.wait_for_selector("#cv-rec-t tbody tr", timeout=15000)
        s.page.wait_for_timeout(500)
        s.note("club vs league: columns and rank kept after coming back",
               None if ("cols=" in s.page.url and "rank=gap" in s.page.url and _cv_cols(s) == (after[1:] if before else after))
               else f"{url} -> {s.page.url}")
    s.step("club vs league: reset the columns", lambda p: s.page.locator("#cv-reset").click(timeout=3000))
    s.page.wait_for_timeout(800)
    s.note("club vs league: reset restores our biggest shortfalls", None if _cv_cols(s) == before and "cols=" not in s.page.url
           else f"{_cv_cols(s)} / {s.page.url}")
    s.step("club vs league: rank by Overall", lambda p: s.page.locator("#cv-rank button[data-r='']").click(timeout=3000))
    s.page.wait_for_timeout(800)
    s.note("club vs league: rank cleared", None if "rank=" not in s.page.url else s.page.url)


def _cv_over(s):
    """Elements in the gap map / players card wider than their box, and either card's sideways scroll."""
    return s.page.evaluate("""() => {
      const cards = ['#cv-gap', '#cv-rec'].map(q => document.querySelector(q));
      const wide = cards.filter(c => c.scrollWidth - c.clientWidth > 1).map(c => c.id);
      const cut = [...document.querySelectorAll('#cv-gap-t td, #cv-gap-t .cv-pick, #cv-gap-t .cv-back, #cv-level div, #cv-rec-t th')]
        .filter(e => e.offsetParent && e.scrollWidth > e.clientWidth + 1).map(e => e.innerText.trim().slice(0, 30));
      return wide.concat(cut).join(' | '); }""")


def club_vs_league_pick_player(s, w):
    """Owner 2026-11-13 (mock-up tab 4): in the open Full Back detail, pick our second rated full
    back -- vs in the URL, the gap, the level strip, the list caption and the "vs" heading all
    follow him; "Back to our best" restores; nothing overflows at 1280 / 1440."""
    s.page.evaluate("() => { try { localStorage.removeItem('lofc.cvl.leagues'); } catch (e) {} }")
    s.goto("/club-vs-league?group=Full%20Back", check=True, desc="club vs league: Full Back (pick a player)")
    s.page.wait_for_selector("#cv-rec-t tbody tr", timeout=15000)
    fb = s.page.locator("#cv-gap-t tr.pos[data-g='Full Back']")
    det = s.page.locator("#cv-gap-t tr.cv-det[data-d='Full Back']")
    if not fb.count():
        return s.note("club vs league: pick a player", skipped="no Full Back row")
    if not det.is_visible():
        s.step("club vs league: open Full Back detail", lambda p: fb.click(timeout=3000))
    picks = det.locator("button.cv-pick")
    if picks.count() < 2:
        return s.note("club vs league: pick a player", skipped=f"{picks.count()} rated full backs")
    s.note("club vs league: our best marked and highlighted",
           None if picks.first.evaluate("b => b.classList.contains('on')") and "our best" in det.inner_text() else "not marked")
    gap0 = fb.locator(".cv-gapv").inner_text().strip()
    vs0 = s.page.locator("#cv-rec-t th[data-sort='vb']").inner_text()
    second = picks.nth(1)
    name, pid = second.inner_text().strip(), second.get_attribute("data-vs")
    s.step("club vs league: pick the second full back", lambda p: second.click(timeout=3000))
    s.page.wait_for_function(f"() => location.search.includes('vs={pid}') && document.querySelector('#cv-level').innerText.includes('Comparing')", timeout=15000)
    s.page.wait_for_timeout(400)
    s.note("club vs league: vs in the URL", None if f"vs={pid}" in s.page.url else s.page.url)
    fb = s.page.locator("#cv-gap-t tr.pos[data-g='Full Back']")
    det = s.page.locator("#cv-gap-t tr.cv-det[data-d='Full Back']")
    gap1 = fb.locator(".cv-gapv").inner_text().strip()
    s.note("club vs league: gap follows him", None if gap1 != gap0 else f"still {gap0}")
    s.note("club vs league: summary row names him", None if name in fb.locator(".cv-who").inner_text() else fb.inner_text())
    strip = s.page.inner_text("#cv-level")
    s.note("club vs league: strip says Comparing <him>", None if "Comparing" in strip and name in strip and gap1.replace("−", "") in strip else strip)
    s.note("club vs league: detail still open, him highlighted",
           None if det.is_visible() and det.locator("button.cv-pick.on").inner_text().strip() == name else "not")
    cap, sub = s.page.inner_text("#cv-count"), s.page.inner_text("#cv-rec-sub")
    s.note("club vs league: list caption names him", None if f"above {name} · ranked within " in cap and name in sub else f"{cap} / {sub}")
    vs1 = s.page.locator("#cv-rec-t th[data-sort='vb']")
    s.note("club vs league: vs heading changes", None if vs1.inner_text().startswith("vs him") and vs0.startswith("vs our best")
           and name in (vs1.get_attribute("data-tip") or "") else f"{vs0} -> {vs1.inner_text()}")
    ov = [float(v) for v in s.page.locator("#cv-rec-t tbody td:nth-child(6)").all_inner_texts() if re.fullmatch(r"\d\.\d\d", v.strip())]
    his = float(re.search(r"\d\.\d\d", strip).group(0))
    s.note("club vs league: every listed player above him", None if ov and all(v > his for v in ov) else f"{his}: {ov[:5]}")
    for width in (1280, 1440):
        s.page.set_viewport_size({"width": width, "height": 900})
        s.page.wait_for_timeout(300)
        bad = _cv_over(s)
        s.note(f"club vs league: nothing overflowing with him picked @{width}", bad or None)
        s.page.evaluate("() => { document.querySelector(\"#cv-gap-t tr.pos[data-g='Full Back']\").scrollIntoView({block: 'start'}); window.scrollBy(0, -130); }")
        s.shot("pick_gap", width)
        s.page.evaluate("() => window.scrollTo(0, document.querySelector('#cv-rec').getBoundingClientRect().top + scrollY - 10)")
        s.shot("pick_list", width)
    s.page.set_viewport_size({"width": w, "height": 900})
    s.step("club vs league: Back to our best", lambda p: s.page.locator("#cv-gap-t button.cv-back").click(timeout=3000))
    s.page.wait_for_function("() => !location.search.includes('vs=') && !document.querySelector('#cv-level').innerText.includes('Comparing')", timeout=15000)
    s.page.wait_for_timeout(300)
    fb = s.page.locator("#cv-gap-t tr.pos[data-g='Full Back']")
    s.note("club vs league: back to our best restores", None if fb.locator(".cv-gapv").inner_text().strip() == gap0
           and s.page.locator("#cv-rec-t th[data-sort='vb']").inner_text().startswith("vs our best")
           and s.page.locator("#cv-gap-t button.cv-back").count() == 0 else s.page.url)
    # changing position drops vs
    s.goto(f"/club-vs-league?group=Full%20Back&vs={pid}", check=True, desc="club vs league: Full Back vs him")
    s.page.wait_for_selector("#cv-rec-t tbody tr", timeout=15000)
    s.step("club vs league: change position", lambda p: s.page.select_option("#cv-group", "Centre Back", timeout=3000))
    s.page.wait_for_timeout(800)
    s.note("club vs league: a new position drops vs", None if "vs=" not in s.page.url else s.page.url)


def club_vs_league_phase_and_example(s, w):
    """Owner 2026-11-13: Big picture's Physical section switches All phases / In possession / Out
    of possession (phase in the URL; top speed "—" in a split; ratings unchanged), and "How this
    is worked out" shows Gap closed as a live mini table for the selected position."""
    s.page.evaluate("() => { try { localStorage.removeItem('lofc.cvl.leagues'); } catch (e) {} }")
    s.goto("/club-vs-league?group=Full%20Back", check=True, desc="club vs league: Full Back (phase, example)")
    s.page.wait_for_selector("#cv-rec-t tbody tr", timeout=15000)
    seg = s.page.locator("#cv-phase button")
    s.note("club vs league: phase switch on Physical", None if seg.all_inner_texts() == ["All phases", "In possession", "Out of possession"] else str(seg.all_inner_texts()))
    if seg.count() != 3:
        return
    s.note("club vs league: All phases by default", None if s.page.locator("#cv-phase button.on").inner_text() == "All phases" else "not")
    # [section, row text] for every Big picture row (section headings are upper-cased by CSS)
    grab = r"""() => { let sec = ''; return [...document.querySelectorAll('#cv-big-l tbody tr, #cv-big-r tbody tr')].flatMap(r => {
      if (r.classList.contains('sec')) { sec = r.firstElementChild.firstChild.textContent.trim(); return []; }
      return [[sec, r.innerText.replace(/\s+/g, ' ').trim()]]; }); }"""
    before = s.page.evaluate(grab)
    s.step("club vs league: In possession", lambda p: seg.nth(1).click(timeout=3000))
    s.page.wait_for_timeout(300)
    after = s.page.evaluate(grab)
    s.note("club vs league: phase in the URL", None if "phase=tip" in s.page.url else s.page.url)
    phys = lambda rows: [t for sec, t in rows if sec == "Physical"]
    rest = lambda rows: [(sec, t) for sec, t in rows if sec != "Physical"]
    s.note("club vs league: physical ranks change", None if phys(before) and phys(after) != phys(before) else str(phys(after)[:3]))
    s.note("club vs league: only the Physical section changes", None if rest(after) == rest(before) else "changed")
    after = phys(after)
    speed = [r for r in after if r.startswith(("Top speed", "Average match top speed"))]
    s.note("club vs league: top speed has no split", None if speed and all(r.endswith("— —") for r in speed) else str(speed))
    s.page.evaluate("() => document.querySelector('#cv-big').scrollIntoView({block: 'start'})")
    s.shot("big_in_possession", w)
    s.page.reload(); s.page.wait_for_selector("#cv-phase", timeout=15000)
    s.note("club vs league: phase kept on reload", None if s.page.locator("#cv-phase button.on").inner_text() == "In possession" else "lost")
    s.step("club vs league: Out of possession", lambda p: s.page.locator("#cv-phase button").nth(2).click(timeout=3000))
    s.page.wait_for_timeout(300)
    s.note("club vs league: out of possession", None if "phase=otip" in s.page.url and phys(s.page.evaluate(grab)) not in (after, phys(before)) else s.page.url)
    s.step("club vs league: All phases", lambda p: s.page.locator("#cv-phase button").nth(0).click(timeout=3000))
    s.page.wait_for_timeout(300)
    s.note("club vs league: back to all phases", None if "phase=" not in s.page.url and s.page.evaluate(grab) == before else s.page.url)
    # the live Gap closed mini table
    s.step("club vs league: open How this is worked out", lambda p: s.page.locator("#cv-how summary").click(timeout=3000))
    gc = s.page.locator("#cv-how-gc")
    fb = gc.inner_text()
    who = s.page.locator("#cv-gap-t tr.pos[data-g='Full Back'] .cv-who").inner_text().split("\n")[0].strip()
    heads = gc.locator("table.cv-gx th").all_inner_texts()
    want = ["Measure", f"Ours ({who.split()[-1]})", "Top 6", "Gap (Top 6 − Ours)", "Target − Ours", "Counted"]
    s.note("club vs league: Full Back mini table", None if fb.startswith("Gap closed: how much of our player's shortfall a target would make up.")
           and len(heads) == 7 and [h for i, h in enumerate(heads) if i != 4] == want and heads[4].startswith("Target (")
           and 1 <= gc.locator("table.cv-gx tbody tr:not(.cv-gx-more)").count() <= 3
           and all(r.is_visible() for r in gc.locator("table.cv-gx tbody tr").all())
           and "Measures that count more in the Full Back rating count more." in fb
           and "Why: it ranks players by how much they fix our weaknesses" in fb else fb[:300])
    # the % is the list's figure for the active tab's first player by Gap closed
    pct = re.search(r"= (\d+)%", fb)
    best = max([v for v in _cv_gc(s)[1] if v is not None], default=None)
    s.note("club vs league: example's % is the list's top Gap closed", None if pct and best is not None and int(pct.group(1)) == best else f"{pct and pct.group(1)} vs {best}")
    s.page.evaluate("() => document.querySelector('#cv-how').scrollIntoView({block: 'start'})")
    s.shot("how_full_back", w)
    s.step("club vs league: change position", lambda p: s.page.select_option("#cv-group", "Centre Back", timeout=3000))
    s.page.wait_for_function("() => document.querySelector('#cv-how-gc').innerText.includes('Centre Back rating') || !document.querySelector('#cv-how-gc table')", timeout=15000)
    cb = gc.inner_text()
    s.note("club vs league: mini table follows the position", None if cb != fb and "Centre Back rating" in cb else cb[:200])
    s.page.evaluate("() => document.querySelector('#cv-how').scrollIntoView({block: 'start'})")
    s.shot("how_centre_back", w)
    # no top-15 cap: the biggest list of any position and league still draws fast
    big = s.page.evaluate("""async () => { let best = null;
      for (const g of ['Goalkeeper', 'Centre Back', 'Full Back', 'Midfield', 'Winger', 'Centre Forward']) {
        const d = await (await fetch('/api/club-vs-league?group=' + encodeURIComponent(g))).json();
        for (const l of d.recommendations.leagues) if (!best || l.count > best.n) best = {g, id: l.competition_id, n: l.count, league: l.league};
      } return best; }""")
    if not big:
        return s.note("club vs league: biggest list", skipped="no lists")
    from urllib.parse import quote
    s.goto(f"/club-vs-league?group={quote(big['g'])}&league={big['id']}", check=True,
           desc=f"club vs league: biggest list ({big['league']}, {big['g']}, {big['n']})")
    s.page.wait_for_selector("#cv-rec-t tbody tr", timeout=15000)
    rows = s.page.locator("#cv-rec-t tbody tr").count()
    s.note(f"club vs league: all {big['n']} rows listed", None if rows == big["n"] else f"{rows} rows")
    ms = s.page.evaluate("""() => { const th = document.querySelector("#cv-rec-t th[data-sort='gc']"), t0 = performance.now();
      th.click(); return performance.now() - t0; }""")
    s.note(f"club vs league: sorting {big['n']} rows under 150 ms", None if ms < 150 else f"{ms:.0f} ms")
    s.page.evaluate("() => window.scrollTo(0, document.querySelector('#cv-rec').getBoundingClientRect().top + scrollY - 10)")
    s.shot("biggest_list", w)


def _cv_col(s, nth):
    """The shown list's numbers in column `nth` (1-based); None for "—"."""
    out = []
    for v in s.page.locator(f"#cv-rec-t tbody tr td:nth-child({nth})").all_inner_texts():
        v = v.strip().replace(",", "").replace("−", "-").replace("+", "")
        out.append(None if v in ("—", "") else float(v))
    return out


def club_vs_league_sort_every_column(s, w):
    """Owner 2026-11-13: every numeric heading of "Players who could close the gap" sorts (first
    click highest first, again lowest first; arrow on it; sort= in the URL); Player and Club A-Z."""
    s.goto("/club-vs-league?group=Full%20Back", check=True, desc="club vs league: Full Back (sort every column)")
    s.page.wait_for_selector("#cv-rec-t tbody tr", timeout=15000)
    heads = s.page.locator("#cv-rec-t th.cv-sort").all_inner_texts()
    need = ["Player", "Club", "Age", "Minutes", "Overall", "Gap closed", "Performance", "Physical"]
    s.note("club vs league: every heading sortable", None if all(any(h.startswith(n) for h in heads) for n in need)
           and any(h.startswith("vs ") for h in heads) else str(heads))
    for key, nth, name in (("age", 4, "Age"), ("min", 5, "Minutes"), ("perf", 9, "Performance")):
        th = s.page.locator(f"#cv-rec-t th[data-sort='{key}']")
        if not th.count():
            s.note(f"club vs league: sort by {name}", "no heading"); continue
        s.step(f"club vs league: sort by {name}", lambda p: th.click(timeout=3000))
        s.page.wait_for_timeout(300)
        v = [x for x in _cv_col(s, nth) if x is not None]
        tail = _cv_col(s, nth)[len(v):]
        s.note(f"club vs league: {name} highest first", None if v and v == sorted(v, reverse=True) and all(x is None for x in tail)
               and f"sort={key}" in s.page.url and "▼" in th.inner_text() else f"{v[:6]} {s.page.url}")
        s.step(f"club vs league: {name} again", lambda p: th.click(timeout=3000))
        s.page.wait_for_timeout(300)
        v = [x for x in _cv_col(s, nth) if x is not None]
        s.note(f"club vs league: {name} lowest first", None if v and v == sorted(v) and f"sort=-{key}" in s.page.url
               and "▲" in th.inner_text() else f"{v[:6]} {s.page.url}")
    th = s.page.locator("#cv-rec-t th[data-sort='name']")
    if th.count():
        s.step("club vs league: sort by Player", lambda p: th.click(timeout=3000))
        s.page.wait_for_timeout(300)
        names = [n.strip() for n in s.page.locator("#cv-rec-t tbody a.pname").all_inner_texts()]
        s.note("club vs league: Player A-Z", None if names == sorted(names, key=str.casefold) else str(names[:5]))
    s.page.evaluate("() => window.scrollTo(0, document.querySelector('#cv-rec').getBoundingClientRect().top + scrollY - 10)")
    s.shot("sorted_by_name", w)


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
    box = s.page.locator("#ph-scatter .sc-chart").bounding_box()
    grid = s.page.locator("#ph-scatter .sc-grid").bounding_box()
    side = s.page.locator("#sc-side").bounding_box()
    # the chart column fills the grid: down to its bottom beside the list, or down to the list below it
    gap = ((side["y"] - (box["y"] + box["height"])) if box and side and side["y"] > box["y"] + 10
           else (grid["y"] + grid["height"]) - (box["y"] + box["height"])) if box and grid else 999
    s.note("physical: chart fills its box", None if gap < 60 else f"space below the chart ({gap:.0f}px)")


def physical_two_metrics(s, w):
    """Owner 2026-11-13 (mock-up tab 2): dashed red medians on both axes, the shaded "High on
    both" quadrant with its corner labels, grid + tick values, Orient dots blue and named, the
    top five red and numbered 1-5 = rows 1-5 of the "High on both" list (8 rows at most), list
    links carry back=, find-a-player rings and names him; nothing cut off at 1280 / 1440."""
    s.goto(PH_PATH + "?season=319&league=4&position=Centre+Back", check=True, desc="physical: two metrics")
    if not _ph_ready(s):
        return s.note("physical: two metrics", "page did not draw")
    plot = s.page.locator("#sc-plot")
    s.note("physical: two dashed red median lines",
           None if plot.locator("line.med").count() == 2 and plot.locator("line.med").first.evaluate(
               "e => getComputedStyle(e).stroke === 'rgb(192, 57, 43)' && getComputedStyle(e).strokeDasharray !== 'none'")
           else "medians missing or not dashed red")
    s.note("physical: shaded quadrant + corner labels",
           None if plot.locator("rect.quad").count() == 1
           and plot.locator("text.ql").all_text_contents() == ["Better on both", "Worse on both"] else "quadrant missing")
    ticks = plot.locator("text.ax").all_text_contents()
    s.note("physical: grid lines with tick values", None if plot.locator("line.grid").count() >= 6
           and len(ticks) >= 6 and all(re.fullmatch(r"-?\d+(\.\d+)?", t) for t in ticks) else str(ticks[:6]))
    s.note("physical: axis titles", None if plot.locator("text.axl").count() == 2 else "no axis titles")
    rows = s.page.locator("#sc-top-body tr")
    names = [n.strip() for n in s.page.locator("#sc-top-body .pname").all_inner_texts()]
    s.note("physical: Better on both list, at most 8", None if 1 <= rows.count() <= 8 else f"{rows.count()} rows")
    marks = s.page.evaluate("""() => [...document.querySelectorAll('#sc-plot g.t5')].map(g =>
        [+g.dataset.rank, g.closest('a') ? g.closest('a').getAttribute('aria-label') : g.dataset.tip.split('\\n')[0],
         getComputedStyle(g.querySelector('circle.pt')).fill, g.querySelector('text').textContent])""")
    want = min(5, len(names))
    s.note("physical: top 5 red, numbered 1-5",
           None if len(marks) == want and sorted(m[0] for m in marks) == list(range(1, want + 1))
           and all(m[2] == "rgb(200, 16, 46)" and m[3] == str(m[0]) for m in marks) else str(marks))
    by_rank = {m[0]: m[1] for m in marks}
    s.note("physical: numbered dots = list rows 1-5",
           None if [by_rank.get(k) for k in range(1, want + 1)] == names[:want] else f"{by_rank} vs {names[:want]}")
    badges = s.page.locator("#sc-top-body .t5b").all_inner_texts()
    s.note("physical: list rows 1-5 carry the red badge", None if badges == [str(k) for k in range(1, want + 1)] else str(badges))
    links = s.page.locator("#sc-top-body a.plink")
    href = links.first.get_attribute("href") if links.count() else ""
    s.note("physical: list links carry back= with the page state",
           None if href and "back=%2Fphysical%3F" in href and "position%3DCentre" in href else href)
    orient = plot.locator("circle.pt.orient")
    if orient.count():
        fill = orient.first.evaluate("e => getComputedStyle(e).fill")
        s.note("physical: Orient dots blue", None if fill == "rgb(31, 95, 168)" else fill)
        s.note("physical: Orient surnames on the chart", None if plot.locator("text.ptl.orient").count() >= 1 else "no names")
    other = plot.locator("circle.pt:not(.orient):not(.t5)").first.evaluate("e => getComputedStyle(e).fill")
    s.note("physical: other players light grey", None if other == "rgb(185, 191, 199)" else other)
    s.note("physical: no browser title tooltips", None if s.page.locator("main svg title, #ph-scatter [title]").count() == 0 else "title present")
    # find a player: someone outside the five
    target = s.page.evaluate("""() => { const a = [...document.querySelectorAll('#sc-plot a')].filter(a => !a.querySelector('g.t5'));
        return a.length ? a[Math.floor(a.length / 2)].getAttribute('aria-label') : ''; }""")
    if target:
        s.step("physical: find a player", lambda p: s.page.locator("#f-find").fill(target, timeout=3000))
        s.note("physical: found player ringed and named",
               None if plot.locator("circle.ring").count() >= 1 and target in plot.locator("text.ptl.found").all_text_contents()
               else f"no ring/name for {target!r}")
        s.step("physical: clear find", lambda p: s.page.locator("#f-find").fill("", timeout=3000))
        s.note("physical: ring gone after clearing", None if plot.locator("circle.ring").count() == 0 else "ring left")
        # the focused empty box lists the players over the chart (owner 2026-11-13): Escape shuts it
        s.step("physical: close the find list", lambda p: s.page.locator("#f-find").press("Escape", timeout=3000))
    # hover a numbered dot: the page's own tooltip with name, club and both values
    if marks:
        s.page.locator("#sc-plot g.t5[data-rank='1']").hover()
        s.page.wait_for_timeout(250)
        tip = s.page.evaluate("() => { const t = [...document.querySelectorAll('.tip')].find(e => !e.hidden); return t ? t.innerText : ''; }")
        s.note("physical: hover shows name, club and both values",
               None if names[0] in tip and tip.count("\n") >= 3 else repr(tip[:80]))
    for width in (1280, 1440):
        s.page.set_viewport_size({"width": width, "height": 900})
        s.page.wait_for_timeout(400)
        ov = s.page.evaluate("""() => { const c = document.getElementById('ph-scatter'), out = [];
          const cr = c.getBoundingClientRect();
          if (document.documentElement.scrollWidth > document.documentElement.clientWidth + 1) out.push('page scrolls sideways');
          for (const e of c.querySelectorAll('svg, #sc-top, .sc-side, .ph-key')) { const r = e.getBoundingClientRect();
            if (r.right > cr.right + 1 || r.left < cr.left - 1) out.push(e.id || e.className.baseVal || e.className); }
          const tw = c.querySelector('.sc-side .tw'); if (tw && tw.scrollWidth > tw.clientWidth + 1) out.push('list scrolls');
          const svg = c.querySelector('#sc-plot svg'); if (svg) { const sr = svg.getBoundingClientRect();
            for (const t of svg.querySelectorAll('text')) { const r = t.getBoundingClientRect();
              if (r.width && (r.left < sr.left - 1 || r.right > sr.right + 1 || r.top < sr.top - 1 || r.bottom > sr.bottom + 1)) out.push('cut: ' + t.textContent); } }
          return out; }""")
        s.note(f"physical: Two metrics fits, nothing cut off @{width}", None if not ov else str(ov[:4]))
        s.page.evaluate("() => scrollTo(0, document.getElementById('ph-scatter').getBoundingClientRect().top + scrollY - 140)")
        path = s.out / f"physical_two_metrics_{width}.png"
        s.page.locator("#ph-scatter").screenshot(path=str(path))
        s.shots.append(str(path))
    s.page.set_viewport_size({"width": w, "height": 900})


def _ph_api(s):
    """The page's own /api/physical answer for the current URL."""
    return s.page.evaluate("() => fetch('/api/physical' + location.search).then(r => r.json())")


def physical_reversed_axis(s, w):
    """Owner 2026-11-13: a lower-is-better axis (Time to sprint) runs high -> low, its title says
    "(lower is better)", and the "Better on both" list = quicker AND faster than both medians."""
    s.goto(PH_PATH + "?season=319&league=4&position=Centre+Back&x=time_to_sprint&y=top5_psv99_kmh",
           check=True, desc="physical: reversed axis")
    if not _ph_ready(s):
        return s.note("physical: reversed axis", "page did not draw")
    plot = s.page.locator("#sc-plot")
    titles = plot.locator("text.axl").all_text_contents()
    s.note("physical: reversed axis title says lower is better",
           None if len(titles) == 2 and titles[0].endswith("(lower is better)") and "lower" not in titles[1] else str(titles))
    xt = s.page.evaluate("""() => [...document.querySelectorAll('#sc-plot text.ax[text-anchor=middle]')]
        .map(t => [+t.getAttribute('x'), +t.textContent]).sort((a, b) => a[0] - b[0]).map(p => p[1])""")
    s.note("physical: reversed axis ticks run high to low",
           None if len(xt) >= 3 and all(a > b for a, b in zip(xt, xt[1:])) else str(xt))
    d = _ph_api(s)
    sc, pl = d["scatter"], d["pool"]["players"]
    s.note("physical: API marks the axis reversed", None if sc["rev"] == {"x": True, "y": False} else str(sc["rev"]))
    bad = [pl[i]["name"] for i in sc["top"] if not (pl[i]["v"]["time_to_sprint"] < sc["median"]["x"]
                                                     and pl[i]["v"]["top5_psv99_kmh"] > sc["median"]["y"])]
    s.note("physical: Better on both = quicker and faster than the medians", None if not bad else str(bad))
    names = [n.strip() for n in s.page.locator("#sc-top-body .pname").all_inner_texts()]
    s.note("physical: list is the API's order", None if names == [pl[i]["name"] for i in sc["top"]] else str(names[:3]))
    vals = s.page.locator("#sc-top-body tr td:nth-child(3)").all_inner_texts()
    # owner 2026-11-13: timing measures (lower is better) show two decimals on this chart and list
    s.note("physical: list shows real times to two decimals", None if vals and all(
        v.strip() == f'{pl[i]["v"]["time_to_sprint"]:.2f}' for v, i in zip(vals, sc["top"])) else str(vals[:3]))
    if sc["top"]:
        pos = s.page.evaluate("""() => { const g = document.querySelector('#sc-plot g.t5[data-rank="1"]');
            const m = [...document.querySelectorAll('#sc-plot line.med')];
            const c = g.querySelector('circle.t5s') || g.querySelector('circle.pt');
            return [+c.getAttribute('cx'), +c.getAttribute('cy'), +m[0].getAttribute('x1'), +m[1].getAttribute('y1')]; }""")
        s.note("physical: number 1 sits top right", None if pos[0] > pos[2] and pos[1] < pos[3] else str(pos))
    s.page.evaluate("() => scrollTo(0, document.getElementById('ph-scatter').getBoundingClientRect().top + scrollY - 140)")
    path = s.out / "physical_reversed_axis.png"
    s.page.locator("#ph-scatter").screenshot(path=str(path))
    s.shots.append(str(path))


def physical_min_minutes(s, w):
    """Owner 2026-11-13: "Min minutes" is a slider on Two metrics (450 up to the plotted pool's
    most minutes rounded up to 90, step 90, "900+ min" label): set on release, in the URL, the
    chart and list follow it, back restores; under 10 players: no ranking, the note says why."""
    s.goto(PH_PATH + "?season=319&league=4&position=Centre+Back", check=True, desc="physical: min minutes")
    if not _ph_ready(s):
        return s.note("physical: min minutes", "page did not draw")
    sel = s.page.locator("#f-min")
    rng = sel.evaluate("e => [e.type, +e.min, +e.max, +e.step, e.value]")
    d0 = _ph_api(s)
    most = max((d0["pool"]["players"][i]["mins"] for i in d0["scatter"]["idx"]), default=0)
    s.note("physical: Min minutes slider 450 to the pool's most minutes (x90), step 90",
           None if rng[0] == "range" and rng[1] == 450 and rng[3] == 90 and rng[4] == "450"
           and rng[2] % 90 == 0 and rng[2] - 90 < most <= rng[2] else f"{rng} most={most}")
    s.note("physical: slider label", None if s.page.inner_text("#min-out").strip() == "450+ min" else s.page.inner_text("#min-out"))
    before = s.page.locator("#sc-plot circle[data-tip], #sc-plot g.t5").count()
    url0 = s.page.url
    # dragging (input events) only moves the label; releasing (change) redraws
    sel.evaluate("e => { e.value = 900; e.dispatchEvent(new Event('input', {bubbles: true})); }")
    s.page.wait_for_timeout(300)
    s.note("physical: dragging moves the label only", None if s.page.inner_text("#min-out").strip() == "900+ min"
           and s.page.url == url0 else f"{s.page.inner_text('#min-out')} {s.page.url}")
    s.step("physical: Min minutes 900", lambda p: sel.evaluate("e => e.dispatchEvent(new Event('change', {bubbles: true}))"))
    s.page.wait_for_function("() => document.getElementById('sc-sub').textContent.endsWith('900+ minutes')", timeout=8000)
    s.note("physical: min in the URL", None if "min=900" in s.page.url else s.page.url)
    tips = s.page.evaluate("() => [...document.querySelectorAll('#sc-plot [data-tip]')].map(e => e.dataset.tip.split('\\n')[1])")
    mins = [int(re.search(r"([\d,]+) min", t).group(1).replace(",", "")) for t in tips if re.search(r"([\d,]+) min", t)]
    s.note("physical: every plotted player has 900+ minutes", None if mins and min(mins) >= 900 else str(mins[:5]))
    after = s.page.locator("#sc-plot circle[data-tip], #sc-plot g.t5").count()
    s.note("physical: fewer or as many dots", None if after <= before else f"{before} -> {after}")
    d = _ph_api(s)
    s.note("physical: list follows the minimum", None if all(d["pool"]["players"][i]["mins"] >= 900 for i in d["scatter"]["top"]) else "list not filtered")
    s.page.evaluate("() => scrollTo(0, document.getElementById('ph-scatter').getBoundingClientRect().top + scrollY - 140)")
    path = s.out / "physical_min_minutes_900.png"
    s.page.locator("#ph-scatter").screenshot(path=str(path))
    s.shots.append(str(path))
    s.step("physical: back", lambda p: p.go_back())
    s.page.wait_for_function("() => document.getElementById('sc-sub').textContent.endsWith('450+ minutes')", timeout=8000)
    s.note("physical: back restores 450", None if "min=" not in s.page.url and sel.input_value() == "450"
           and s.page.inner_text("#min-out").strip() == "450+ min" else s.page.url)
    # a small pool at 1,800: under 10 plotted players = no ranking, the thin note
    s.goto(PH_PATH + "?season=319&league=4&position=Centre+Back&age=u21&min=1800", check=True, desc="physical: min minutes thin")
    if _ph_ready(s):
        d = _ph_api(s)
        n = len(d["scatter"]["idx"])
        note = s.page.locator("#sc-top-note")
        if n < 10:
            s.note("physical: under 10 players, no ranking and the note",
                   None if s.page.locator("#sc-top-body tr").count() == 0 and (n == 0 or (note.is_visible()
                   and note.inner_text().strip() == f"Not rated: only {n} comparable players (needs 10)")) else note.inner_text())
        else:
            s.note("physical: thin pool at 1,800", skipped=f"{n} players")


def physical_goalkeeper_row(s, w):
    """Owner 2026-11-13: no metric in both Strongest 3 and Weakest 3 (seen on Nathan Baxter);
    the line under the table names the season shown."""
    s.goto(PH_PATH + "?season=319&view=perf", check=False)
    if not _ph_ready(s):
        return s.note("physical: goalkeeper row", "page did not draw")
    both = s.page.evaluate("""() => [...document.querySelectorAll('#sp-body tr:not(.sp-sec)')].map(tr => {
        const l = [...tr.querySelectorAll('td.sp-list')].map(td => [...td.querySelectorAll('.sp-ml span:first-child')].map(e => e.textContent));
        return [tr.querySelector('.pname').textContent, (l[0] || []).filter(m => (l[1] || []).includes(m))]; }).filter(x => x[1].length)""")
    s.note("physical: no metric in both Strongest 3 and Weakest 3", None if not both else str(both[:3]))
    line = s.page.locator("#sp-unrated")
    if line.is_visible():
        s.note("physical: unrated line names the season",
               None if re.fullmatch(r"\d+ squad players? not rated in 2026/27 \(under 450 minutes or too few peers\)",
                                    line.inner_text().strip()) else line.inner_text())
    gk = s.page.locator("#sp-body tr:not(.sp-sec)").filter(has_text="Baxter")
    if gk.count():
        gk.first.scroll_into_view_if_needed()
        path = s.out / "physical_goalkeeper_row.png"
        gk.first.screenshot(path=str(path))
        s.shots.append(str(path))


def physical_squad_download(s, w):
    """R5: the squad card's Excel button returns our squad as an .xlsx for the page's season."""
    s.goto(PH_PATH, check=False)
    if not _ph_ready(s):
        return s.note("physical: squad download", "page did not draw")
    href = s.page.locator("#sq-xlsx").get_attribute("href") or ""
    s.note("physical: Excel link carries the season", None if "season=319" in href else href)
    got = s.page.evaluate("(h) => fetch(h).then(r => r.arrayBuffer().then(b => [r.status, "
                          "r.headers.get('content-type'), r.headers.get('content-disposition'), "
                          "String.fromCharCode(...new Uint8Array(b).slice(0, 2))]))", href)
    s.note("physical: squad .xlsx", None if got[0] == 200 and "spreadsheetml" in (got[1] or "")
           and ".xlsx" in (got[2] or "") and got[3] == "PK" else str(got))


def physical_performance_view(s, w):
    """Owner 2026-11-13: the squad card's "Physical | Performance" switch. Performance = rated
    squad players grouped by position (section rows), strongest / weakest 3 as plain coloured
    percentiles, links carry back=, the view is in the URL; Physical stays as it was; nothing
    wider than its card at 1280 / 1440."""
    s.goto(PH_PATH, check=False)
    if not _ph_ready(s):
        return s.note("physical: performance view", "page did not draw")
    phys_rows = s.page.locator("#sq-body tr").count()
    s.note("physical: Physical is the default view",
           None if s.page.locator("#sq-view button.on").inner_text() == "Physical"
           and s.page.locator("#sq-tw:not([hidden])").count() == 1 else "Physical not on")
    s.step("physical: switch to Performance",
           lambda p: s.page.locator("#sq-view button[data-view=perf]").click(timeout=3000))
    s.note("physical: view in the URL", None if "view=perf" in s.page.url else s.page.url)
    s.note("physical: Physical table hidden", None if s.page.locator("#sq-tw[hidden]").count() == 1 else "still shown")
    secs = s.page.locator("#sp-body tr.sp-sec").all_inner_texts()
    order = ["GOALKEEPER", "CENTRE BACK", "FULL BACK", "MIDFIELD", "WINGER", "CENTRE FORWARD"]
    up = [t.strip().upper() for t in secs]
    s.note("physical: rows grouped by position, in order",
           None if up and up == [g for g in order if g in up] else str(secs))
    sec_style = s.page.locator("#sp-body tr.sp-sec td").first.evaluate(
        "e => [getComputedStyle(e).textTransform, getComputedStyle(e).fontWeight, parseFloat(getComputedStyle(e).paddingTop)]")
    s.note("physical: section rows bold uppercase with space above",
           None if sec_style[0] == "uppercase" and int(sec_style[1]) >= 600 and sec_style[2] >= 12 else str(sec_style))
    rows = s.page.locator("#sp-body tr:not(.sp-sec)")
    s.note("physical: rated players listed", None if rows.count() >= 3 else f"{rows.count()} rows")
    s.note("physical: seven columns", None if s.page.locator("#sp-table thead th").all_inner_texts() == [
        "Player", "Minutes", "Overall", "Performance", "Physical", "Strongest 3", "Weakest 3"]
        else str(s.page.locator("#sp-table thead th").all_inner_texts()))
    first = rows.first
    s.note("physical: strongest and weakest 3 listed",
           None if first.locator("td.sp-list").nth(0).locator(".sp-ml").count() >= 2
           and first.locator("td.sp-list").nth(1).locator(".sp-ml").count() >= 2 else "lists missing")
    s.note("physical: percentiles are plain coloured numbers (no bars or pills)",
           None if s.page.locator("#sp-body .pctn").count() > 0
           and s.page.locator("#sp-body .pb, #sp-body .ph-pp").count() == 0 else "not plain numbers")
    hues = s.page.locator("#sp-body .pctn").evaluate_all(
        "es => es.map(e => [parseInt(e.textContent), e.classList.contains('hi'), e.classList.contains('lo')])")
    bad = [h for h in hues if (h[0] >= 70) != h[1] or (h[0] < 30) != h[2]]
    s.note("physical: green 70+, red under 30", None if not bad else str(bad[:3]))
    href = first.locator("a.plink").get_attribute("href") or ""
    s.note("physical: player link carries back= with the view",
           None if "back=" in href and "view%3Dperf" in href else href)
    s.note("physical: Excel button in both views",
           None if s.page.locator("#sq-xlsx").is_visible() else "button hidden")
    s.note("physical: no browser title tooltips", None if s.page.locator("#ph-squad [title]").count() == 0
           else "title attribute present")
    for width in (1280, 1440):
        s.page.set_viewport_size({"width": width, "height": 900})
        s.page.wait_for_timeout(300)
        ov = s.page.evaluate("""() => { const tw = document.getElementById('sp-tw'), c = document.getElementById('ph-squad');
          const out = [];
          if (tw.scrollWidth > tw.clientWidth + 1) out.push('table ' + tw.scrollWidth + ' > ' + tw.clientWidth);
          for (const e of c.querySelectorAll('#sp-body td, .sp-ml span')) if (e.scrollWidth > e.clientWidth + 1) out.push((e.textContent || '').slice(0, 40));
          return out; }""")
        s.note(f"physical: Performance view fits @{width}", None if not ov else str(ov[:4]))
        s.page.locator("#ph-squad").scroll_into_view_if_needed()
        s.page.locator("#ph-squad").screenshot(path=str(s.out / f"physical_perf_view_{width}.png"))
        s.shots.append(str(s.out / f"physical_perf_view_{width}.png"))
    s.page.set_viewport_size({"width": w, "height": 900})
    s.page.go_back()
    s.page.wait_for_timeout(500)
    s.note("physical: back restores the Physical view",
           None if s.page.locator("#sq-tw:not([hidden])").count() == 1 and "view=" not in s.page.url
           and s.page.locator("#sq-body tr").count() == phys_rows else s.page.url)
    s.goto(PH_PATH + "?view=perf", check=True, desc="physical: performance view from the URL")
    _ph_ready(s)
    s.note("physical: ?view=perf opens on Performance",
           None if s.page.locator("#sq-perf:not([hidden])").count() == 1 else "not Performance")


def info_bar_dates(s, w):
    """R6: the info bar ends with the last Impect and SkillCorner pull dates."""
    text = s.page.inner_text("#infobar")
    s.note("info bar: pull dates", None if re.search(
        r"Impect (\d{1,2} [A-Z][a-z]{2}|—) · SkillCorner (\d{1,2} [A-Z][a-z]{2}|—)$", text.strip())
        else repr(text))
    s.shot("infobar", w)


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


# -- Remembered settings (owner 2026-11-13) ----------------------------------------------------
# Every list page reopens its last settings when reached by the nav (a bare URL); a URL that says
# anything wins and becomes the remembered one. s.goto() forgets them first (web_check.Session),
# so only these scenarios see a remembered page.

def _nav_round_trip(s, label, path, away="/glossary"):
    s.step(f"{label}: away by the nav", lambda p: p.locator(f"nav a[href='{away}']").click(timeout=3000), expect_nav=True)
    s.step(f"{label}: back by the nav", lambda p: p.locator(f"nav a[href='{path}']").click(timeout=3000), expect_nav=True)


def _wait_js(s, js, arg=None, timeout=8000):
    try:
        s.page.wait_for_function(js, arg=arg, timeout=timeout)
        return True
    except Exception:
        return False


_VALUE_IS = "([sel, want]) => document.querySelector(sel) && document.querySelector(sel).value === want"


def _other_option(s, sel):
    """First option of a select that is neither the current one nor 'All'."""
    return s.page.evaluate("""sel => { const e = document.querySelector(sel);
        return [...e.options].map(o => o.value).find(v => v !== e.value && v !== 'All' && v !== '') || null; }""", sel)


def _remembers_select(s, label, path, sel, want, explicit_want, *, ready, gone=(), param="position"):
    """Set `sel` to `want` on `path`, away and back by the nav: restored (the URL too, without
    any `gone` param). Then `?<param>=<explicit_want>` wins and becomes the remembered one."""
    ok = _wait_js(s, _VALUE_IS, [sel, want])
    s.note(f"{label}: choice restored after the nav", None if ok else
           f"{sel} = {s.page.locator(sel).input_value()!r}, want {want!r}")
    left = [g for g in gone if g in s.page.url]
    s.note(f"{label}: one-off params not restored", None if not left else s.page.url)
    s.goto(path + "?" + urlencode({param: explicit_want}), check=False)
    ready()
    ok = _wait_js(s, _VALUE_IS, [sel, explicit_want])
    s.note(f"{label}: explicit URL wins", None if ok else f"{sel} = {s.page.locator(sel).input_value()!r}")
    _nav_round_trip(s, label, path)
    ok = _wait_js(s, _VALUE_IS, [sel, explicit_want])
    s.note(f"{label}: explicit URL becomes the remembered one", None if ok else
           f"{sel} = {s.page.locator(sel).input_value()!r}")


def players_remembers(s, w):
    s.goto("/players", check=False)
    if not _wait_js(s, "() => document.querySelectorAll('#f-position option').length > 1"):
        return s.note("players: remembered", skipped="no positions")
    s.step("players: position = Winger", lambda p: p.locator("#f-position").select_option(value="Winger", timeout=3000))
    _nav_round_trip(s, "players", "/players")
    s.note("players: URL restored", None if "position=Winger" in s.page.url else s.page.url)
    _remembers_select(s, "players", "/players", "#f-position", "Winger", "Full Back",
                      ready=lambda: _wait_js(s, "() => document.querySelectorAll('#f-position option').length > 1"))


def physical_remembers(s, w):
    s.goto(PH_PATH, check=False)
    if not _ph_ready(s):
        return s.note("physical: remembered", skipped="page did not draw")
    s.step("physical: position = Winger", lambda p: p.locator("#f-position").select_option(value="Winger", timeout=3000))
    s.step("physical: Performance view", lambda p: p.locator("#sq-view button[data-view=perf]").click(timeout=3000))
    _nav_round_trip(s, "physical", PH_PATH)
    _ph_ready(s)
    s.note("physical: URL restored", None if "position=Winger" in s.page.url and "view=perf" in s.page.url else s.page.url)
    s.note("physical: view restored", None if _wait_js(s, "() => !document.querySelector('#sq-perf').hidden") else "Physical view shown")
    _remembers_select(s, "physical", PH_PATH, "#f-position", "Winger", "Centre Back", ready=lambda: _ph_ready(s))
    s.note("physical: explicit URL drops the old view", None if "view=perf" not in s.page.url else s.page.url)


def squads_remembers(s, w):
    s.goto("/squads", check=False)
    if not _wait_js(s, "() => document.querySelectorAll('#f-position option').length > 2"):
        return s.note("squads: remembered", skipped="no positions")
    want = _other_option(s, "#f-position")
    s.step(f"squads: position = {want}", lambda p: p.locator("#f-position").select_option(value=want, timeout=3000))
    _wait_js(s, "w => new URLSearchParams(location.search).get('position') === w", want)
    _nav_round_trip(s, "squads", "/squads")
    other = s.page.evaluate("""w => [...document.querySelectorAll('#f-position option')].map(o => o.value)
        .find(v => v !== w && v !== 'All') || null""", want)
    _remembers_select(s, "squads", "/squads", "#f-position", want, other,
                      ready=lambda: _wait_js(s, "() => document.querySelectorAll('#f-position option').length > 2"))


def scout_remembers(s, w):
    s.goto(SR_PATH, check=False)
    if not _sr_ready(s):
        return s.note("scout reports: remembered", skipped="page did not draw")
    s.step("scout reports: Verdict = Sign", lambda p: p.locator("#f-verdict").select_option(value="Sign", timeout=3000))
    row = _sr_rows(s).first
    if row.count():
        s.step("scout reports: open a report", lambda p: row.locator("td").nth(0).click(timeout=3000))
    _nav_round_trip(s, "scout reports", SR_PATH)
    _sr_ready(s)
    s.note("scout reports: URL restored", None if "verdict=Sign" in s.page.url else s.page.url)
    other = _wait_js(s, "() => document.querySelectorAll('#f-verdict option').length > 2") and \
        s.page.evaluate("() => [...document.querySelectorAll('#f-verdict option')].map(o => o.value).find(v => v !== 'Sign' && v !== 'All')")
    _remembers_select(s, "scout reports", SR_PATH, "#f-verdict", "Sign", other or "Sign", ready=lambda: _sr_ready(s),
                      gone=("open=",), param="verdict")


def watchlist_remembers(s, w):
    s.goto(WL_PATH, check=False)
    if not _wl_ready(s):
        return s.note("watchlist: remembered", skipped="watchlist empty")
    first = "() => { const b = document.querySelector('#wl-status input'); return b && !b.checked; }"
    s.step("watchlist: untick a status", lambda p: p.locator("#wl-status input").first.click(timeout=3000))
    row = _wl_rows(s).first
    if row.count():
        s.step("watchlist: open a row", lambda p: row.locator("td").nth(0).click(timeout=3000))
    url = s.page.url
    _nav_round_trip(s, "watchlist", WL_PATH)
    s.note("watchlist: status restored", None if _wait_js(s, first) and "status=" in s.page.url else f"{url} -> {s.page.url}")
    s.note("watchlist: open row not restored", None if "open=" not in s.page.url else s.page.url)
    s.goto(WL_PATH + "?money=1", check=False)
    _wl_ready(s)
    s.note("watchlist: explicit URL wins", None if "status=" not in s.page.url and
           _wait_js(s, "() => document.querySelector('#wl-status input')?.checked") else s.page.url)
    _nav_round_trip(s, "watchlist", WL_PATH)
    s.note("watchlist: explicit URL becomes the remembered one",
           None if "money=1" in s.page.url and "status=" not in s.page.url else s.page.url)


def report_remembers(s, w):
    """The season is remembered (not the player)."""
    s.goto(REPORT_BASE, check=False)
    _report_ready(s)
    s.step("report: season = 2026/27", lambda p: p.locator("#rp-season").select_option(value="319", timeout=3000))
    _nav_round_trip(s, "report", "/report")
    s.note("report: season restored, not the player",
           None if "season=319" in s.page.url and "player=" not in s.page.url else s.page.url)
    _remembers_select(s, "report", "/report", "#rp-season", "319", "318",
                      ready=lambda: _wait_js(s, "() => document.querySelectorAll('#rp-season option').length > 1"),
                      gone=("player=", "position="), param="season")


def club_vs_league_remembers(s, w):
    s.goto("/club-vs-league", check=False)
    ready = lambda: _wait_js(s, "() => document.querySelectorAll('#cv-group option').length > 1")
    if not ready():
        return s.note("club vs league: remembered", skipped="no positions")
    want = _other_option(s, "#cv-group")
    s.step(f"club vs league: position = {want}", lambda p: p.locator("#cv-group").select_option(value=want, timeout=3000))
    _nav_round_trip(s, "club vs league", "/club-vs-league")
    s.note("club vs league: URL restored", None if "group=" in s.page.url else s.page.url)
    other = s.page.evaluate("""w => [...document.querySelectorAll('#cv-group option')].map(o => o.value)
        .find(v => v !== w && v !== '') || null""", want)
    _remembers_select(s, "club vs league", "/club-vs-league", "#cv-group", want, other, ready=ready,
                      gone=("back=",), param="group")


def club_vs_league_gc_one_decimal(s, w):
    """Owner 2026-11-13: the Gap closed mini table shows one decimal and every row adds up on the
    numbers shown (Gap = Top 6 - Ours, Target - Ours, Counted); the total keeps the whole %."""
    s.goto("/club-vs-league?group=Full+Back", check=False)
    if not _wait_js(s, "() => document.querySelector('#cv-how-gc table.cv-gx')", timeout=15000):
        return s.note("club vs league: one-decimal mini table", skipped="no example for Full Back")
    s.step("club vs league: open How this is worked out", lambda p: p.locator("#cv-how summary").click(timeout=3000))
    rows = s.page.evaluate("""() => [...document.querySelectorAll('#cv-how-gc table.cv-gx tbody tr:not(.cv-gx-more)')]
        .map(tr => [...tr.querySelectorAll('td.n')].map(td => td.innerText.trim()))""")
    bad = []
    num = lambda t: float(t.split()[0].replace("−", "-"))      # noqa: E731
    for r in rows:
        if len(r) != 6 or not all(re.fullmatch(r"−?\d+\.\d", c.split()[0]) for c in r):
            bad.append(r)
            continue
        o, t6, g, tg, d, c = map(num, r)
        if abs(g - (t6 - o)) > 0.1 or abs(d - (tg - o)) > 0.1 or abs(c - min(max(d, 0), g)) > 0.1:
            bad.append(r)
    s.note("club vs league: mini table one decimal, rows add up", None if rows and not bad else str(bad or rows)[:200])
    total = s.page.locator("#cv-how-gc").inner_text()
    s.note("club vs league: total keeps the whole %", None if re.search(r"= \d+%", total) else total[-200:])


# -- Physical: Find a player lists the plotted players (owner 2026-11-13) ----------------------

def physical_find_lists_players(s, w):
    """Clicking the empty box lists the plotted players (name · club, A-Z); typing narrows it;
    picking one rings and names him on the chart."""
    s.goto(PH_PATH + "?season=319&league=4&position=Centre+Back", check=False)
    if not _ph_ready(s):
        return s.note("physical: find list", skipped="page did not draw")
    items = s.page.locator("#find-results button")
    s.step("physical: click the empty find box", lambda p: p.locator("#f-find").click(timeout=3000))
    s.note("physical: empty box lists players", None if s.page.locator("#find-results:not([hidden])").count()
           and items.count() >= 5 else f"{items.count()} listed")
    names = [t.split(" · ")[0].strip() for t in items.all_inner_texts()]
    s.note("physical: list sorted by name", None if names == sorted(names, key=str.lower) else str(names[:5]))
    plotted = s.page.locator("#sc-plot .pt:not(.t5s)").count()
    s.note("physical: one row per plotted player", None if items.count() == plotted else f"{items.count()} vs {plotted} dots")
    s.note("physical: list scrolls", None if s.page.locator("#find-results").evaluate(
        "e => getComputedStyle(e).overflowY") in ("auto", "scroll") else "no scroll")
    if items.count() < 3:
        return
    target = names[2]
    probe = target[:3]
    s.step("physical: type to narrow", lambda p: p.locator("#f-find").fill(probe, timeout=3000))
    left = [t.split(" · ")[0] for t in items.all_inner_texts()]
    s.note("physical: typing filters the list", None if left and all(probe.lower() in n.lower() for n in left)
           and len(left) <= len(names) else str(left[:5]))
    s.step("physical: clear", lambda p: p.locator("#f-find").fill("", timeout=3000))
    s.step("physical: click the box again", lambda p: p.locator("#f-find").click(timeout=3000))
    s.step("physical: pick a player", lambda p: items.nth(2).click(timeout=3000))
    s.note("physical: box holds his name", None if s.page.locator("#f-find").input_value() == target
           else s.page.locator("#f-find").input_value())
    s.note("physical: list closes", None if s.page.locator("#find-results[hidden]").count() else "still open")
    found = s.page.locator("#sc-plot text.ptl.found").all_text_contents()
    s.note("physical: picked player ringed and named", None if s.page.locator("#sc-plot circle.ring").count() >= 1
           and target in found else f"found labels {found}")


_COMMON = {"exercise": True, "scenarios": []}

PAGES = {
    "home": {"path": "/", "exercise": False, "scenarios": [home_first_view]},
    "players": {"path": "/players", "exercise": False, "scenarios": [
        players_first_view, players_layout_widths, players_exercise_controls, players_position_season_open_back,
        players_filter_open_back, players_leagues, players_chip_remove,
        players_search_other_position, players_clear_search, players_sort, players_money,
        players_metric_filters, players_assessed, players_download, players_history_and_url, players_remembers]},
    "card": {"path": "/player/39154/5/318", "exercise": True, "scenarios": [
        card_back_link, card_money_switch, card_rank_as, card_zones, card_squad_season,
        card_watchlist, card_radars, card_rated_tables, card_extra_tables, card_strengths_no_overlap,
        card_other_players]},
    "compare": {"path": "/compare?season=318&position=Winger", "exercise": True, "scenarios": [
        compare_three_players_every_width, compare_defaults_fill_the_url,
        compare_position_season_back_forward, compare_pick_from_pool_list,
        compare_search_this_position_only, compare_none_in_c, compare_name_opens_card,
        compare_zones_and_money, compare_special_cases, compare_more_filters, compare_radars,
        compare_remembers_players, compare_download]},
    "report": {"path": REPORT_BASE, "exercise": True, "scenarios": [
        report_empty_state, report_cases, report_search_pick, report_scout_verdicts,
        report_empty_search_lists, report_form_live, report_downloads,
        report_season_switch, report_history_and_url, report_layout_widths, report_radar,
        report_one_sheet, report_draft, report_remembers]},
    "squads": {"path": "/squads", "exercise": False, "scenarios": [
        squads_first_view, squads_layout_widths, squads_exercise_controls,
        squads_league_club_open_back, squads_show, squads_more_filters, squads_row_message,
        squads_thin_and_sort, squads_search, squads_download, squads_history_and_url,
        squads_scroll_draws_more, squads_remembers]},
    "scout-reports": {"path": "/scout-reports", "exercise": True, "scenarios": [
        scout_first_view, scout_filters_url, scout_squad_role, scout_search_and_age, scout_tabs, scout_open_report,
        scout_name_opens_card, scout_sort, scout_remembers]},
    "watchlist": {"path": "/watchlist", "exercise": True, "scenarios": [
        watchlist_first_view, watchlist_status_filter, watchlist_money, watchlist_editor,
        watchlist_name_opens_card, watchlist_download, watchlist_sort, watchlist_remembers]},
    "assess": {"path": "/assess", "scenarios": []},
    "signoff": {"path": "/signoff", "scenarios": []},
    "physical": {"path": "/physical", "exercise": False, "scenarios": [
        physical_first_view, physical_exercise_controls, physical_layout_widths, physical_filters_back_forward,
        physical_no_data_season, physical_thin_pool, physical_show_all_and_orient,
        physical_scatter_axes, physical_squad_sort, physical_name_opens_card, physical_additions,
        physical_squad_download, physical_performance_view, physical_two_metrics,
        physical_reversed_axis, physical_min_minutes, physical_goalkeeper_row, physical_remembers,
        physical_find_lists_players, info_bar_dates]},
    "club-vs-league": {"path": "/club-vs-league", "exercise": True, "scenarios": [club_vs_league, club_vs_league_gap_closed, club_vs_league_pick_player, club_vs_league_phase_and_example, club_vs_league_sort_every_column, club_vs_league_remembers,
        club_vs_league_gc_one_decimal]},
    "rating-reference": {"path": "/rating-reference", "exercise": True, "scenarios": [reference_rating]},
    "playing-styles": {"path": "/playing-styles", "exercise": True, "scenarios": [reference_styles]},
    "glossary": {"path": "/glossary", "exercise": True, "scenarios": [reference_glossary]},
    "users": {"path": "/users", "exercise": True, "scenarios": [users_first_view]},
}
