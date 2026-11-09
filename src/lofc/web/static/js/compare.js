// Compare page (mockup v5 v-compare). Draws what /api/compare sends; computes no football number
// (every value, percentile text, colour class and caption comes from the API, which calls the
// same Python as the Streamlit page). The URL query string is the whole page state.
import {api, esc, dash, chip, pcol, radar, orientSeries} from './common.js';

const $ = id => document.getElementById(id);
const PCOL = ['#15171C', '#D9822B', '#2A9D8F'];
const ORIENT = '#1F5FA8';
const SLOTS = ['a', 'b', 'c'];
const NONE = '— none —';

let opts = null;           // /api/players/options (seasons, positions, leagues, archetypes)
let st = null;             // page state, mirrors the URL
let seq = 0;               // newest /api/compare request
let last = null;           // last /api/compare answer
const pools = {};          // picker lists by filter query

// ---- state <-> URL -----------------------------------------------------------------------
const ALL_STYLES = 'All styles';
const defaults = () => ({season: opts.default_season, position: opts.default_position, leagues: [],
  rank_as: opts.default_archetype, money: false, min_minutes: opts.minutes.default,
  max_age: opts.max_age.default, foot: 'Any', contract: opts.contract[0], loan: opts.loan[0],
  style: ALL_STYLES, strong_only: false, a: null, b: null, c: null});
// "More filters" (owner C4): the Players page's, narrowing the list a picker shows
const MORE = ['min_minutes', 'max_age', 'foot', 'contract', 'loan', 'style'];

function fromUrl() {
  const q = new URLSearchParams(location.search), s = defaults();
  const season = Number(q.get('season'));
  if (opts.seasons.some(x => x.id === season)) s.season = season;
  if (opts.positions.includes(q.get('position'))) s.position = q.get('position');
  if ((opts.archetypes[s.position] || []).includes(q.get('rank_as'))) s.rank_as = q.get('rank_as');
  s.leagues = q.getAll('leagues').filter(l => opts.leagues.includes(l));
  s.money = q.get('money') === '1';
  const n = (k, lo, hi) => { const v = Number(q.get(k)); return q.get(k) !== null && q.get(k) !== '' && isFinite(v) ? Math.min(hi, Math.max(lo, v)) : null; };
  s.min_minutes = n('min_minutes', 450, opts.minutes.max) ?? s.min_minutes;
  s.max_age = n('max_age', 18, 40) ?? s.max_age;
  const pick = (k, allowed) => { const v = q.get(k); if (v != null && allowed.includes(v)) s[k] = v; };
  pick('foot', opts.foot); pick('contract', opts.contract); pick('loan', opts.loan);
  pick('style', opts.styles[s.position] || []);
  s.strong_only = q.get('strong_only') === '1' && s.style !== ALL_STYLES;
  for (const k of SLOTS) { const v = q.get(k); s[k] = /^\d+-\d+$/.test(v || '') ? v : null; }
  return s;
}

/** Filters only (the picker list's key) or the whole state. */
function toQuery(s, {slots = true} = {}) {
  const d = defaults(), q = new URLSearchParams();
  if (s.season !== d.season) q.set('season', s.season);
  if (s.position !== d.position) q.set('position', s.position);
  s.leagues.forEach(l => q.append('leagues', l));
  if (s.rank_as !== d.rank_as) q.set('rank_as', s.rank_as);
  if (s.money) q.set('money', '1');
  for (const k of MORE) if (s[k] !== d[k]) q.set(k, String(s[k]));
  if (s.strong_only) q.set('strong_only', '1');
  if (slots) for (const k of SLOTS) if (s[k]) q.set(k, s[k]);
  const t = q.toString();
  return t ? '?' + t : '';
}

function commit() {
  const qs = toQuery(st);
  if (qs !== location.search) history.pushState({}, '', location.pathname + qs);
  refresh();
}

// ---- controls ----------------------------------------------------------------------------
const fill = (el, values, labels) => {
  el.innerHTML = values.map((v, i) => `<option value="${esc(v)}">${esc(labels ? labels[i] : v)}</option>`).join('');
};
const leaguesLabel = () => {
  const n = st.leagues.length;
  return n === 0 || n === opts.leagues.length ? 'All leagues' : n === 1 ? st.leagues[0] : `${n} leagues`;
};

function setControls() {
  $('f-season').value = st.season; $('f-position').value = st.position;
  const arch = opts.archetypes[st.position] || [];
  fill($('f-rank'), arch); $('f-rank').value = st.rank_as; $('rank-wrap').hidden = arch.length < 2;
  $('f-money').checked = st.money;
  const styles = opts.styles[st.position] || [];
  fill($('f-style'), [ALL_STYLES, ...styles]); $('f-style').value = st.style;
  $('style-wrap').hidden = $('strong-wrap').hidden = styles.length === 0;
  $('f-strong').checked = st.strong_only;
  $('f-minutes').value = st.min_minutes; $('f-minutes-num').value = st.min_minutes;
  $('f-age').value = st.max_age; $('age-out').textContent = st.max_age >= 40 ? '40+' : st.max_age;
  $('f-foot').value = st.foot; $('f-contract').value = st.contract; $('f-loan').value = st.loan;
  foldText();
  const sel = st.leagues.length ? new Set(st.leagues) : new Set(opts.leagues);
  document.querySelectorAll('#leagues-list input').forEach(i => { i.checked = sel.has(i.value); });
  $('leagues-btn').textContent = leaguesLabel();
}

function showSlotLabels() {
  const labels = (last && last.slot_labels) || {};
  for (const k of SLOTS) {
    const inp = $('slot-' + k);
    if (document.activeElement === inp) continue;
    inp.value = labels[k] || '';
    inp.placeholder = k === 'c' ? NONE : 'Search a player…';
  }
}

/** "More filters · 2 active ▾": the count says the picker list is narrowed while it is shut. */
function foldText() {
  const d = defaults(), n = MORE.filter(k => st[k] !== d[k]).length;
  $('more-btn').textContent = 'More filters' + (n ? ` · ${n} active` : '') + ($('more').classList.contains('open') ? ' ▴' : ' ▾');
}

/** Another position: its styles differ, so the style filter goes back to all. */
function setPosition(pos) {
  st.position = pos; st.rank_as = opts.default_archetype; st.style = ALL_STYLES; st.strong_only = false;
}

// ---- refresh -----------------------------------------------------------------------------
async function refresh() {
  const mine = ++seq;
  setControls();
  let d;
  try { d = await api('/api/compare' + toQuery(st)); }
  catch (e) {
    if (mine !== seq) return;
    $('cmp-msg').innerHTML = '<div class="warn">The comparison could not be loaded. Reload the page to try again.</div>';
    return;
  }
  if (mine !== seq) return;
  last = d;
  // the server fills A/B defaults and drops slots of another position: keep the URL exact
  // (shareable) without adding a history entry
  for (const k of SLOTS) st[k] = d.slots[k];
  const qs = toQuery(st);
  if (qs !== location.search) history.replaceState({}, '', location.pathname + qs);
  render(d);
}

// ---- rendering ---------------------------------------------------------------------------
const dot = i => `<i class="dot" style="background:${PCOL[i]}"></i>`;
const backQ = () => '?back=' + encodeURIComponent('/compare' + location.search);

function render(d) {
  document.title = `Compare · ${d.title} · LOFC Recruitment`;
  $('cmp-title').textContent = d.title;
  $('cmp-meta').textContent = 'Up to three players of one position' + (d.lens ? ` · ranked as ${d.lens}` : '');
  $('cmp-notice').innerHTML = d.notice
    ? (d.notice.level === 'info' ? `<div class="info">${esc(d.notice.text)}</div>` : `<div class="note" style="margin-top:8px">${esc(d.notice.text)}</div>`) : '';
  showSlotLabels();
  if (d.message) {
    const cls = d.message.level === 'error' ? 'notice' : d.message.level === 'warn' ? 'warn' : 'info';
    $('cmp-msg').innerHTML = `<div class="${cls}">${esc(d.message.text)}</div>`;
    $('cmp-body').hidden = true;
    return;
  }
  $('cmp-msg').innerHTML = '';
  $('cmp-body').hidden = false;
  renderSummary(d);
  renderRadars(d);
  renderTables(d);
  const ph = $('c-ph').hidden, pr = $('c-phrad').hidden;
  $('r-phys').hidden = ph && pr;
  $('r-phys').classList.toggle('one', ph !== pr);
  renderZones(d);
}

const stylePills = t => {
  if (!t || t === '—') return '<span class="note">—</span>';
  return t.split(' · ').map(s => s.endsWith('(leans)') ? `<span class="pill lean">${esc(s.replace(' (leans)', ''))}</span>`
    : s === 'No standout style' ? `<span class="note">${esc(s)}</span>` : `<span class="pill strong">${esc(s)}</span>`).join('');
};
const verdictPills = t => {
  if (!t || t === '—') return '<span class="note">—</span>';
  return t.split(' · ').map(s => `<span class="pill ${/Don't|Not /.test(s) ? 'verdict-neg' : /Sign|High/.test(s) ? 'verdict-pos' : 'verdict-mid'}">${esc(s)}</span>`).join('');
};
const trend = t => esc(dash(t)).split(' · ').map(x => `<span class="tr">${x}</span>`).join('');
const ARROW = {up: '▲ ', down: '▼ ', neutral: ''};

function renderSummary(d) {
  const P = d.players;
  let h = '<thead><tr><th class="k"></th>' + P.map((p, i) =>
    `<th><a class="nm" href="${esc(p.href + backQ())}">${dot(i)}${esc(p.header_name)}</a>`
    + `<span class="sm">${esc(p.sub)}</span>`
    + (p.not_rated ? `<span class="nr">${esc(p.not_rated)}</span>` : '') + '</th>').join('') + '</tr></thead><tbody>';
  for (const r of d.summary.rows) {
    h += `<tr><th class="k" scope="row">${esc(r.attribute)}</th>` + r.cells.map(c => {
      if (r.kind === 'text') {
        if (r.attribute === 'Playing style') return `<td>${stylePills(c.text)}</td>`;
        if (r.attribute === 'Scout verdicts') return `<td>${verdictPills(c.text)}</td>`;
        return `<td class="trend">${trend(c.text)}</td>`;
      }
      const big = r.rating ? chip(c.now) : `<b class="big">${esc(dash(c.now))}</b>`;
      const small = c.sub ? `<span class="ch ${esc(c.tone || 'neutral')}">${ARROW[c.tone] || ''}${esc(c.sub)}</span>` : '';
      return `<td>${big}${small}</td>`;
    }).join('') + '</tr>';
  }
  $('cmp-sum').innerHTML = h + '</tbody>';
  $('cmp-sumcap').textContent = [d.summary.caption, d.summary.note].filter(Boolean).join(' ');
}

/** raw[i] = player k's shown value for that axis, from the metric table with the same label. */
function rawFor(labels, rows, k) {
  if (!rows) return null;
  const by = new Map(rows.map(r => [String(r.label), r.cells[k] && r.cells[k].text]));
  return labels.map(l => { const v = by.get(String(l)); return v == null || v === '' ? null : dash(v); });
}

function radarBlock(R, players, rows) {
  if (!R.traces.length) return '';
  const series = R.traces.map((t, i) => ({values: t.values, name: t.name, colour: PCOL[i], raw: rawFor(R.labels, rows, i)}));
  // An Orient line with a gap would be drawn at the centre (a wrong claim): drawn only whole.
  const o = R.orient, whole = o && o.values.every(v => v != null);
  if (whole) series.push(orientSeries(o.values, o.label));
  return radar(R.labels, series);
}
const notes = arr => arr.filter(Boolean).map(t => `<p class="note">${esc(t)}</p>`).join('');

function renderRadars(d) {
  const P = d.perf_radar, F = d.phys_radar;
  $('prad-h').textContent = P.heading;
  $('prad-sub').textContent = P.sub;
  // No physical chart at all (goalkeepers, or nobody has tracking): no empty card; its
  // caption goes under the Performance radar.
  const physChart = F && F.traces.length;
  $('prad').innerHTML = radarBlock(P, d.players, d.perf_table && d.perf_table.rows) + notes([P.no_data, P.leagues_note, !physChart && F ? F.no_data : null]);
  $('c-phrad').hidden = !physChart;
  if (physChart) {
    $('phrad-sub').textContent = F.sub;
    $('phrad').innerHTML = radarBlock(F, d.players, d.phys_table && d.phys_table.rows) + notes([F.no_data]);
  }
}

function metricTable(rows, players) {
  const head = '<thead><tr><th>Metric</th>' + players.map((p, i) => `<th>${dot(i)}${esc(p.header_name)}</th>`).join('') + '</tr></thead>';
  const line = r => `<tr><td class="ml">${esc(r.label)}</td>`
    + r.cells.map(c => `<td class="${c.cls || ''}"><b>${esc(dash(c.text))}</b>${c.pct_text ? ` <span class="pc" style="color:${pcol(c.pct)}">${esc(c.pct_text)}</span>` : ''}</td>`).join('')
    + '</tr>';
  // Rated metrics carry their weight tier: grouped under thin High / Mid / Low headings.
  if (!rows.some(r => r.tier)) return head + '<tbody>' + rows.map(line).join('') + '</tbody>';
  const order = ['High', 'Mid', 'Low'];
  const groups = [...order, ...new Set(rows.map(r => r.tier).filter(t => t && !order.includes(t)))];
  return head + '<tbody>' + groups.map(g => {
    const rs = rows.filter(r => r.tier === g);
    return rs.length ? `<tr class="sec wt"><td colspan="${players.length + 1}">${esc(g)} weight</td></tr>` + rs.map(line).join('') : '';
  }).join('') + rows.filter(r => !r.tier).map(line).join('') + '</tbody>';
}

function renderTables(d) {
  const P = d.players;
  $('pt-h').textContent = d.perf_table.heading;
  $('pt-sub').textContent = d.perf_table.sub;
  $('cmp-pt').innerHTML = metricTable(d.perf_table.rows, P);
  $('po-d').hidden = !d.perf_other.rows.length;
  $('cmp-po').innerHTML = metricTable(d.perf_other.rows, P);
  const ph = d.phys_table;
  $('c-ph').hidden = !ph;
  if (ph) {
    $('ph-sub').textContent = ph.sub;
    $('cmp-ph').innerHTML = metricTable(ph.rows, P);
    const o = d.phys_other;
    $('pho-d').hidden = !(o && o.rows.length);
    $('cmp-pho').innerHTML = o ? metricTable(o.rows, P) : '';
  }
}

// ---- packing zones -----------------------------------------------------------------------
const ZLAYOUT = {IBWL: [1, '1'], IB: [2, '1'], IBWR: [3, '1'], WL: [1, '2 / span 2'], AM: [2, '2'], WR: [3, '2 / span 2'],
  CM: [2, '3'], FBL: [1, '4 / span 2'], DM: [2, '4'], FBR: [3, '4 / span 2'], CB: [2, '5']};

function renderZones(d) {
  const Z = d.zones;
  $('c-pz').hidden = !Z;
  if (!Z) return;
  $('pz-sub').textContent = Z.caption;
  const sel = $('pz-m'), keep = sel.value;
  fill(sel, Z.options.map(o => o.key), Z.options.map(o => o.label));
  if (keep && Z.measures[keep]) sel.value = keep;
  const names = Object.fromEntries(Z.zones.map(z => [z.code, z.name]));
  const per = Z.measures[sel.value];
  $('pz').style.gridTemplateColumns = `repeat(${d.players.length}, minmax(0, 1fr))`;
  $('pz').innerHTML = d.players.map((p, i) => {
    const cells = per[i];
    const head = `<div class="pz-name">${dot(i)}${esc(p.header_name)}</div>`;
    if (!cells) return `<div>${head}<p class="note">No zone data for this measure.</p></div>`;
    return `<div>${head}<div class="pitch">` + Object.entries(ZLAYOUT).map(([code, [col, row]]) => {
      const c = cells[code] || {}, pc = c.pct;
      const bg = pc == null ? 'rgba(255,255,255,.15)' : pc >= 70 ? '#2E7D4F' : pc >= 30 ? '#E6E8EC' : '#C0392B';
      const ink = pc == null ? '#D7E6DC' : (pc >= 70 || pc < 30) ? '#fff' : '#15171C';
      const tip = `${p.header_name}\n${names[code]}\n${dash(c.text)} · ${c.pct_text || 'no percentile'}`;
      return `<div class="zone" style="grid-column:${col};grid-row:${row};background:${bg};color:${ink}" data-tip="${esc(tip)}">`
        + `<span>${esc(names[code])}</span><b>${esc(dash(c.text))}</b><span>${pc == null ? '' : 'P' + pc}</span></div>`;
    }).join('') + '<div class="zone gk" style="grid-row:6">Goalkeeper zone · no data</div></div></div>';
  }).join('');
  $('pz-legend').innerHTML = '<span><i style="background:var(--hi)"></i>70th percentile and above</span><span><i style="background:#E6E8EC"></i>30th to 70th</span><span><i style="background:var(--lo)"></i>Below 30th</span>'
    + (Z.any_missing[sel.value] ? '<span><i style="background:rgba(255,255,255,.15);border:1px dashed #8D939C"></i>No percentile (under 450 min)</span>' : '')
    + '<span>↑ Attacking</span>';
}

// ---- slot pickers ------------------------------------------------------------------------
let searchSeq = 0;
const timers = {};

async function poolList() {
  const k = toQuery(st, {slots: false});
  if (!pools[k]) pools[k] = api('/api/compare/pool' + k).catch(e => { delete pools[k]; throw e; });
  return pools[k];
}

function showResults(slot, items) {
  const out = $('res-' + slot);
  out._items = items;
  out.innerHTML = items.length
    ? items.map((x, i) => `<button type="button" data-action="pick" data-i="${i}">${esc(x.label)}${x.composite ? ` <span class="rc">${esc(x.composite)}</span>` : ''}</button>`).join('')
    : '<div class="none">No player found.</div>';
  out.hidden = false;
}

async function openList(slot) {
  const inp = $('slot-' + slot), q = inp.value.trim();
  const current = last && last.slot_labels ? last.slot_labels[slot] : null;
  const mine = ++searchSeq;
  let items;
  try {
    if (!q || q === current) {
      const p = await poolList();
      items = p.players.map(x => ({label: x.label, key: x.key, composite: x.composite, position: st.position}));
    } else {
      // owner C5: the selected Position only (any league, outside the filters)
      const r = await api('/api/compare/search?' + new URLSearchParams({season: st.season, position: st.position, q}));
      items = r.results.map(x => ({label: x.label, key: `${x.player_id}-${x.competition_id}`, position: x.position, league: x.league}));
    }
  } catch (e) { return; }
  if (mine !== searchSeq) return;
  if (slot === 'c') items = [{label: NONE, key: null}, ...items];
  showResults(slot, items);
}

function closeAll() {
  for (const k of SLOTS) $('res-' + k).hidden = true;
  showSlotLabels();
}

/** A pick fills only its own slot (owner C5: never switches the position or clears the others;
 *  the lists hold only this position). */
function pick(slot, item) {
  closeAll();
  st[slot] = item.key;
  document.activeElement && document.activeElement.blur();
  commit();
}

function bindSlots() {
  for (const slot of SLOTS) {
    const inp = $('slot-' + slot), out = $('res-' + slot);
    inp.addEventListener('focus', () => { inp.select(); openList(slot); });
    inp.addEventListener('input', () => { clearTimeout(timers[slot]); timers[slot] = setTimeout(() => openList(slot), 200); });
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const items = out._items || [];
        if (!out.hidden && items.length) pick(slot, items[0]);
      } else if (e.key === 'Escape') { inp.blur(); closeAll(); }
    });
    out.addEventListener('mousedown', e => e.preventDefault());     // keep focus until the click
    out.addEventListener('click', e => {
      const b = e.target.closest('[data-action="pick"]'); if (!b) return;
      pick(slot, out._items[Number(b.dataset.i)]);
    });
    inp.addEventListener('blur', () => setTimeout(() => { if (document.activeElement !== inp) { out.hidden = true; showSlotLabels(); } }, 150));
  }
}

// ---- "More filters" (the Players page's controls and behaviour) ---------------------------
const timers2 = {};
const debounced = (name, fn, ms = 250) => { clearTimeout(timers2[name]); timers2[name] = setTimeout(fn, ms); };
const flush = (name, fn) => { clearTimeout(timers2[name]); fn(); };

function buildMore() {
  fill($('f-foot'), opts.foot); fill($('f-contract'), opts.contract); fill($('f-loan'), opts.loan);
  for (const id of ['f-minutes', 'f-minutes-num']) Object.assign($(id), {min: opts.minutes.min, max: opts.minutes.max, step: opts.minutes.step});
  $('minutes-max').textContent = opts.minutes.max.toLocaleString('en-GB');
  Object.assign($('f-age'), {min: opts.max_age.min, max: opts.max_age.max, step: 1});
  const h = opts.help, tip = (id, t) => { if (t) $(id).title = t; };
  tip('f-minutes', h.minutes); tip('f-age', h.max_age); tip('f-foot', h.foot); tip('f-contract', h.contract);
  tip('f-loan', h.loan); tip('f-style', h.style); tip('sw-strong', h.strong_only);
}

function bindMore() {
  for (const [id, key] of [['f-foot', 'foot'], ['f-contract', 'contract'], ['f-loan', 'loan']])
    $(id).addEventListener('change', e => { st[key] = e.target.value; commit(); });
  $('f-style').addEventListener('change', e => { st.style = e.target.value; if (st.style === ALL_STYLES) st.strong_only = false; commit(); });
  $('f-strong').addEventListener('change', e => { st.strong_only = e.target.checked && st.style !== ALL_STYLES; commit(); });
  const setMin = v => {
    let x = Number(v); if (!isFinite(x)) return false;
    x = Math.round(Math.min(opts.minutes.max, Math.max(450, x)) / 10) * 10;
    st.min_minutes = x; $('f-minutes').value = x; $('f-minutes-num').value = x; return true;
  };
  $('f-minutes').addEventListener('input', e => { if (setMin(e.target.value)) debounced('min', commit); });
  $('f-minutes').addEventListener('change', e => { if (setMin(e.target.value)) flush('min', commit); });
  $('f-minutes-num').addEventListener('change', e => { if (setMin(e.target.value)) flush('min', commit); });
  const age = e => { st.max_age = Number(e.target.value); $('age-out').textContent = st.max_age >= 40 ? '40+' : st.max_age; };
  $('f-age').addEventListener('input', e => { age(e); debounced('age', commit); });
  $('f-age').addEventListener('change', e => { age(e); flush('age', commit); });
  $('more-btn').addEventListener('click', () => {
    const open = !$('more').classList.contains('open');
    $('more').classList.toggle('open', open);
    $('more-btn').setAttribute('aria-expanded', String(open));
    foldText();
  });
}

// ---- events ------------------------------------------------------------------------------
function bind() {
  $('f-season').addEventListener('change', e => { st.season = Number(e.target.value); commit(); });
  $('f-position').addEventListener('change', e => {
    setPosition(e.target.value); st.a = st.b = st.c = null; commit();
  });
  $('f-rank').addEventListener('change', e => { st.rank_as = e.target.value; commit(); });
  $('f-money').addEventListener('change', e => { st.money = e.target.checked; commit(); });

  const pop = $('leagues-pop'), btn = $('leagues-btn');
  const togglePop = open => {
    const wasOpen = !pop.hidden;
    pop.hidden = !open; btn.setAttribute('aria-expanded', String(open));
    if (wasOpen && !open) setControls();
  };
  btn.addEventListener('click', () => togglePop(pop.hidden));
  $('leagues-all').addEventListener('click', () => { st.leagues = []; commit(); });
  $('leagues-none').addEventListener('click', () =>
    document.querySelectorAll('#leagues-list input').forEach(i => { i.checked = false; }));
  $('leagues-list').addEventListener('change', () => {
    const on = [...document.querySelectorAll('#leagues-list input:checked')].map(i => i.value);
    st.leagues = on.length === opts.leagues.length ? [] : on; commit();
  });
  $('pz-m').addEventListener('change', () => { if (last) renderZones(last); });
  bindMore();

  bindSlots();
  document.addEventListener('click', e => { if (!e.target.closest('.popwrap')) togglePop(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') togglePop(false); });
  window.addEventListener('popstate', () => { st = fromUrl(); refresh(); });
}

(async function init() {
  const first = location.search;
  const optsP = api('/api/players/options');
  const pre = api('/api/compare' + first); pre.catch(() => {});
  opts = await optsP;
  fill($('f-season'), opts.seasons.map(s => s.id), opts.seasons.map(s => s.name));
  fill($('f-position'), opts.positions);
  $('leagues-list').innerHTML = opts.leagues.map((l, i) =>
    `<label><input type="checkbox" name="league_${i}" value="${esc(l)}" aria-label="${esc(l)}">${esc(l)}</label>`).join('');
  $('f-season').title = opts.help.season;
  $('f-rank').title = opts.help.rank_as;
  buildMore();
  st = fromUrl();
  // open when the URL carries one of its filters, so the narrowed list is explained
  const d0 = defaults();
  if (MORE.some(k => st[k] !== d0[k])) { $('more').classList.add('open'); $('more-btn').setAttribute('aria-expanded', 'true'); }
  bind();
  // the first answer was requested beside the options; used when the URL was already normal
  if (toQuery(st) === first) {
    const mine = ++seq; setControls();
    try {
      const d = await pre;
      if (mine === seq) {
        last = d; for (const k of SLOTS) st[k] = d.slots[k];
        const qs = toQuery(st);
        if (qs !== location.search) history.replaceState({}, '', location.pathname + qs);
        render(d);
      }
      return;
    } catch (e) { /* fall through to a normal load */ }
  }
  refresh();
})();
