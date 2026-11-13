// Players page. Fetches JSON from /api/players* and renders it; computes no football number
// (every figure, caption and ordering comes from the API, which calls the same Python as
// Streamlit). The URL query string is the whole page state: shareable, back/forward restore.
import {api, esc, dash, fmtInt, rememberState, restoreState} from './common.js';

const $ = id => document.getElementById(id);
const md = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');

let opts = null;          // /api/players/options
let st = null;            // current page state (mirrors the URL)
let spec = null, specKey = '';
let seq = 0;              // newest list request; older responses are ignored
let lastPayload = null;
let physTab = 0;

// ---- state <-> URL -----------------------------------------------------------------------
const defaults = () => ({
  season: opts.default_season, position: opts.default_position, leagues: [],
  rank_as: opts.default_archetype, min_minutes: opts.minutes.default, max_age: opts.max_age.default,
  foot: 'Any', contract: opts.contract[0], loan: opts.loan[0], style: 'All styles',
  strong_only: false, money: false, budget: null, wage: null, assessed: false,
  signed_only: false, signable: null, sort: '', dir: 'desc', pct: {}, raw: {}});

function fromUrl() {
  const q = new URLSearchParams(location.search), d = defaults(), s = d;
  const pick = (k, allowed) => { const v = q.get(k); if (v != null && allowed.includes(v)) s[k] = v; };
  const season = Number(q.get('season'));
  if (opts.seasons.some(x => x.id === season)) s.season = season;
  pick('position', opts.positions);
  pick('rank_as', opts.archetypes[s.position]);
  s.leagues = q.getAll('leagues').filter(l => opts.leagues.includes(l));
  const n = (k, lo, hi) => { const v = Number(q.get(k)); return q.get(k) !== null && q.get(k) !== '' && isFinite(v) ? Math.min(hi, Math.max(lo, v)) : null; };
  s.min_minutes = n('min_minutes', 450, opts.minutes.max) ?? s.min_minutes;
  s.max_age = n('max_age', 18, 40) ?? s.max_age;
  pick('foot', opts.foot); pick('contract', opts.contract); pick('loan', opts.loan);
  pick('style', opts.styles[s.position]);
  s.strong_only = q.get('strong_only') === '1' && s.style !== 'All styles';
  s.money = q.get('money') === '1';
  s.budget = n('budget', 0, 150); s.wage = n('wage', 0, 200000);
  s.assessed = q.get('assessed') === '1';
  s.signed_only = s.assessed && q.get('signed_only') === '1';
  s.signable = q.get('signable') === '1' ? 1 : q.get('signable') === '0' ? 0 : null;
  s.sort = q.get('sort') || ''; s.dir = q.get('dir') === 'asc' ? 'asc' : 'desc';
  for (const [k, v] of q) {
    if (k.startsWith('pct_') && isFinite(Number(v))) s.pct[k.slice(4)] = Number(v);
    if (k.startsWith('raw_') && isFinite(Number(v))) s.raw[k.slice(4)] = Number(v);
  }
  return s;
}

/** Query string for the page URL and the API: only values that differ from the defaults. */
function toQuery(s) {
  const d = defaults(), q = new URLSearchParams();
  const put = (k, v, dv) => { if (v != null && v !== '' && v !== dv) q.set(k, String(v)); };
  put('season', s.season, d.season); put('position', s.position, d.position);
  s.leagues.forEach(l => q.append('leagues', l));
  put('rank_as', s.rank_as, d.rank_as); put('min_minutes', s.min_minutes, d.min_minutes);
  put('max_age', s.max_age, d.max_age); put('foot', s.foot, d.foot);
  put('contract', s.contract, d.contract); put('loan', s.loan, d.loan);
  put('style', s.style, d.style); if (s.strong_only) q.set('strong_only', '1');
  if (s.money) { q.set('money', '1'); put('budget', s.budget, null); put('wage', s.wage, null); }
  if (s.assessed) { q.set('assessed', '1'); if (s.signed_only) q.set('signed_only', '1'); }
  if (s.money && s.signable !== null) q.set('signable', String(s.signable));
  if (s.sort) { q.set('sort', s.sort); q.set('dir', s.dir); }
  for (const [m, v] of Object.entries(s.pct)) if (v > 0) q.set('pct_' + m, v);
  for (const [m, v] of Object.entries(s.raw)) q.set('raw_' + m, v);
  const t = q.toString();
  return t ? '?' + t : '';
}

function commit({replace = false} = {}) {
  const qs = toQuery(st);
  if (qs !== location.search)
    history[replace ? 'replaceState' : 'pushState']({}, '', location.pathname + qs);
  rememberState('players');
  refresh();
}

// ---- controls <-> state ------------------------------------------------------------------
function fillSelect(el, values, labels) {
  el.innerHTML = values.map((v, i) => `<option value="${esc(v)}">${esc(labels ? labels[i] : v)}</option>`).join('');
}

function buildStaticControls() {
  fillSelect($('f-season'), opts.seasons.map(s => s.id), opts.seasons.map(s => s.name));
  fillSelect($('f-position'), opts.positions);
  fillSelect($('f-foot'), opts.foot);
  fillSelect($('f-contract'), opts.contract);
  fillSelect($('f-loan'), opts.loan);
  $('leagues-list').innerHTML = opts.leagues.map((l, i) =>
    `<label><input type="checkbox" name="league_${i}" value="${esc(l)}" aria-label="${esc(l)}">${esc(l)}</label>`).join('');
  for (const id of ['f-minutes', 'f-minutes-num']) {
    $(id).min = opts.minutes.min; $(id).max = opts.minutes.max; $(id).step = opts.minutes.step;
  }
  $('minutes-max').textContent = opts.minutes.max.toLocaleString('en-GB');
  Object.assign($('f-age'), {min: opts.max_age.min, max: opts.max_age.max, step: 1});
  for (const id of ['f-budget', 'f-budget-num']) { $(id).min = opts.budget.min; $(id).max = opts.budget.max; $(id).step = opts.budget.step; }
  Object.assign($('f-wagex'), {min: opts.wage_x.min, max: opts.wage_x.max, step: opts.wage_x.step});
  Object.assign($('f-wage'), {min: opts.wage_pounds.min, max: opts.wage_pounds.max, step: opts.wage_pounds.step});
  // Help texts are Streamlit's, shown as tooltips.
  const h = opts.help, tip = (id, t) => { const e = $(id); if (e) e.title = t; };
  tip('f-search', h.search); tip('f-season', h.season); tip('f-style', h.style);
  tip('sw-strong', h.strong_only); tip('f-rank', h.rank_as); tip('f-minutes', h.minutes);
  tip('f-age', h.max_age); tip('f-contract', h.contract); tip('f-loan', h.loan);
  tip('f-foot', h.foot); tip('sw-money', h.money); tip('f-wagex', h.wage_x);
  tip('f-wage', h.wage_pounds); tip('sw-assessed', h.assessed); tip('sw-signed', h.signed_only);
}

function leaguesLabel() {
  const n = st.leagues.length;
  return n === 0 || n === opts.leagues.length ? 'All leagues' : n === 1 ? st.leagues[0] : `${n} leagues`;
}

/** Write the state into every control (no events fire). */
function setControls() {
  $('f-season').value = st.season; $('f-position').value = st.position;
  const arch = opts.archetypes[st.position];
  fillSelect($('f-rank'), arch);
  $('f-rank').value = st.rank_as; $('rank-wrap').hidden = arch.length < 2;
  const styles = opts.styles[st.position];
  fillSelect($('f-style'), ['All styles', ...styles]);
  $('f-style').value = st.style;
  $('style-wrap').hidden = styles.length === 0; $('strong-wrap').hidden = styles.length === 0;
  $('f-strong').checked = st.strong_only;
  $('f-minutes').value = st.min_minutes; $('f-minutes-num').value = st.min_minutes;
  $('f-age').value = st.max_age; $('age-out').textContent = st.max_age >= 40 ? '40+' : st.max_age;
  $('f-foot').value = st.foot; $('f-contract').value = st.contract; $('f-loan').value = st.loan;
  $('f-money').checked = st.money;
  document.querySelectorAll('.money').forEach(e => { if (e.id !== 'sw-signable') e.hidden = !st.money; });
  if (st.budget != null) { $('f-budget').value = st.budget; $('f-budget-num').value = st.budget; }
  if (st.wage != null) $('f-wage').value = st.wage;
  $('f-assessed').checked = st.assessed; $('sw-signed').hidden = !st.assessed;
  $('f-signed').checked = st.signed_only;
  const sel = st.leagues.length ? new Set(st.leagues) : new Set(opts.leagues);
  document.querySelectorAll('#leagues-list input').forEach(i => { i.checked = sel.has(i.value); });
  $('leagues-btn').textContent = leaguesLabel();
  syncSliders();
}

function syncSliders() {
  if (!spec) return;
  for (const g of spec.physical) for (const s of g.sliders) {
    const v = st.raw[s.metric] ?? s.rest, el = $('raw_' + s.metric);
    if (el) { el.value = v; el.nextElementSibling.querySelector('.val').textContent = Number(v).toFixed(s.decimals); }
  }
  for (const m of spec.performance) {
    const v = st.pct[m.metric] ?? 0, el = $('pct_' + m.metric);
    if (el) { el.value = v; el.nextElementSibling.querySelector('.val').textContent = v; }
  }
}

// ---- metric filter sliders ---------------------------------------------------------------
let prefetch = null;      // first-load requests started before the options arrive: {qs, spec, list}

async function loadSpec() {
  const key = [st.season, st.position, st.rank_as].join('|');
  if (key === specKey) return;
  const q = new URLSearchParams({season: st.season, position: st.position, rank_as: st.rank_as});
  const pre = prefetch && prefetch.qs === toQuery(st) ? prefetch.spec : null;
  spec = await (pre || api('/api/players/metrics?' + q));
  specKey = key; physTab = 0;
  buildSliders();
}

function buildSliders() {
  $('mf-phys').hidden = spec.physical.length === 0;
  $('ph-tabs').innerHTML = spec.physical.map((g, i) =>
    `<button type="button" data-tab="${i}" class="${i ? '' : 'on'}">${esc(g.group)}</button>`).join('');
  const range = (id, label, lo, hi, step, extra) =>
    `<div class="range"><label for="${id}">${esc(label)}</label>` +
    `<input type="range" id="${id}" name="${id}" min="${lo}" max="${hi}" step="${step}" aria-label="${esc(label)}" ${extra || ''}>` +
    `<div class="ends"><span>${lo}</span><b class="val"></b><span>${hi}</span></div></div>`;
  $('ph-sliders').innerHTML = spec.physical.map((g, i) =>
    `<div class="sliders-group" data-group="${i}" style="display:contents" ${i ? 'hidden' : ''}>` +
    g.sliders.map(s => range('raw_' + s.metric, s.label, s.min, s.max, s.step, `data-kind="raw" data-metric="${s.metric}"`)).join('') +
    '</div>').join('');
  $('pf-sliders').innerHTML = spec.performance.map(m =>
    range('pct_' + m.metric, m.label, 0, 100, 5, `data-kind="pct" data-metric="${m.metric}"`)).join('');
  syncSliders();
}

function showTab(i) {
  physTab = i;
  document.querySelectorAll('#ph-tabs button').forEach(b => b.classList.toggle('on', Number(b.dataset.tab) === i));
  document.querySelectorAll('#ph-sliders .sliders-group').forEach(g => { g.hidden = Number(g.dataset.group) !== i; });
}

function sliderAtRest(kind, metric, v) {
  if (kind === 'pct') return v <= 0;
  const s = spec.physical.flatMap(g => g.sliders).find(x => x.metric === metric);
  return !s || Math.abs(v - s.rest) < 1e-9;
}

function setMetric(kind, metric, v) {
  const bag = kind === 'pct' ? st.pct : st.raw;
  if (sliderAtRest(kind, metric, v)) delete bag[metric]; else bag[metric] = v;
}

function activeMetrics() {
  return Object.keys(st.pct).filter(m => st.pct[m] > 0).length + Object.keys(st.raw).length;
}

// ---- refresh: fetch the list and render --------------------------------------------------
async function refresh() {
  const mine = ++seq;
  setControls();
  const qs = toQuery(st);
  $('csv').href = '/api/players.csv' + qs;
  renderChips();
  // The slider ranges come first (a small, cached answer, so the Metric filters controls are
  // there at once and the URL state is complete), then the list.
  try { await loadSpec(); } catch (e) { return fail(mine, e); }
  if (mine !== seq) return;
  setControls(); renderChips(); foldText();
  let payload;
  const pre = prefetch && prefetch.qs === qs ? prefetch.list : null;
  prefetch = null;
  try { payload = await (pre || api('/api/players' + qs)); } catch (e) { return fail(mine, e); }
  if (mine !== seq) return;
  lastPayload = payload;
  render(payload);
  rememberState('players');     // owner 2026-11-13: the nav link reopens these settings
}

function fail(mine, e) {
  if (mine !== seq) return;
  $('pl-notice').innerHTML = '<div class="warn">The list could not be loaded. Change a filter or reload the page to try again.</div>';
}

// ---- rendering ---------------------------------------------------------------------------
const ratingClass = x => x >= 4 ? 'c4' : x >= 3 ? 'c3' : x >= 2 ? 'c2' : 'c1';
const ratingChip = v => {
  if (v == null || v === '') return '<span class="chip c0">—</span>';
  const x = Number(v);
  return isNaN(x) ? '<span class="chip c0">—</span>' : `<span class="chip ${ratingClass(x)}">${esc(v)}</span>`;
};
const stylePills = arr => {
  if (!arr || !arr.length) return '<span class="note">—</span>';
  return arr.map(s => s.endsWith('(leans)') ? `<span class="pill lean">${esc(s.replace(' (leans)', ''))}</span>`
    : s === 'No standout style' ? `<span class="note">${esc(s)}</span>` : `<span class="pill strong">${esc(s)}</span>`).join('');
};
const scoutPill = v => !v ? '' : `<span class="pill ${v === 'High priority' ? 'verdict-pos' : v === 'Not recommended' ? 'verdict-neg' : 'verdict-mid'}">${esc(v)}</span>`;

function cell(col, v) {
  switch (col.kind) {
    case 'rating': return `<td class="rating">${ratingChip(v)}</td>`;
    case 'style': return `<td class="sty">${stylePills(v)}</td>`;
    case 'scouts': return `<td>${scoutPill(v)}</td>`;
    case 'bool': return `<td class="c">${v ? '✓' : ''}</td>`;
    case 'num': return `<td class="n">${col.key === 'Mins' ? fmtInt(v) : esc(dash(v))}</td>`;
    // long club / league names are cut with an ellipsis (full text on hover) so every rating
    // column stays on screen at 1440 wide
    default: return col.key === 'Player' ? `<td><div class="pname cut">${esc(dash(v))}</div></td>`
      : `<td><div class="cut" title="${esc(dash(v))}">${esc(dash(v))}</div></td>`;
  }
}

function render(p) {
  document.title = `${p.title} · LOFC Recruitment`;
  // One line: the names are listed in the "Not ranked" section below (full text on hover).
  const noticeLine = t => {
    const cut = t.indexOf('): ');
    const short = cut > 0 ? t.slice(0, cut + 1) + ' · listed under Not ranked below' : t;
    return `<div class="note" style="margin-top:8px" title="${esc(t)}">${esc(short)}</div>`;
  };
  $('pl-title').textContent = p.title;
  $('pl-meta').textContent = p.meta;
  $('pl-notice').innerHTML = p.notice
    ? (p.notice.level === 'info' ? `<div class="info">${esc(p.notice.text)}</div>` : noticeLine(p.notice.text)) : '';
  $('count-cap').innerHTML = md(p.count_caption);
  const lines = [p.contract_caption, p.rank_caption, p.assessed_caption, p.money && p.money.note].filter(Boolean);
  $('cap-lines').innerHTML = lines.map(l => `<div>${md(l)}</div>`).join('');
  $('pl-hidden').innerHTML = p.hidden_text ? `<div class="notice">${esc(p.hidden_text)}</div>` : '';
  $('sw-signable').hidden = !p.money;
  // Market value adds the money columns, Rank as two composite columns: then, where the page is
  // too narrow for them, the list scrolls sideways inside its card (edge shadow shows there is more).
  $('tw').toggleAttribute('data-scroll-x', !!p.money || (!!p.rank_caption && window.innerWidth < 1380));
  $('f-signable').checked = !!p.signable;
  $('f-wagex').value = p.money ? p.money.wage_x : $('f-wagex').value;
  if (p.money) {
    if (st.budget == null) { $('f-budget').value = p.money.budget; $('f-budget-num').value = p.money.budget; }
    $('f-wage').value = p.money.wage; $('wagex-out').textContent = p.money.wage_x + '×';
    $('money-cap').textContent = p.money.caption || '';
  }
  affordableInfo(p.affordable_now);

  const cols = p.columns, sort = p.sort;
  $('pl-head').innerHTML = '<tr>' + cols.map(c => {
    const on = sort && sort.column === c.key, arrow = on ? (sort.descending ? ' ▼' : ' ▲') : '';
    const cls = (c.kind === 'num' || c.kind === 'rating' ? (c.kind === 'num' ? 'n' : 'rating') : '') + (on ? ' sorted' : '');
    return `<th class="${cls.trim()}"${c.help ? ` title="${esc(c.help)}"` : ''}><button type="button" data-sort="${esc(c.key)}">${esc(c.label)}${arrow}</button></th>`;
  }).join('') + '</tr>';
  const back = encodeURIComponent('/players' + location.search);
  $('pl-body').innerHTML = p.rows.map(r =>
    `<tr class="click" tabindex="0" data-href="/player/${r.id[0]}/${r.id[1]}/${r.id[2]}?back=${back}">` +
    cols.map(c => cell(c, r.cells[c.key])).join('') + '</tr>').join('')
    || `<tr><td colspan="${cols.length}" class="note">No ${esc(p.title)} match these filters.</td></tr>`;

  $('nr-sub').textContent = p.not_ranked.sub;
  $('nr-body').innerHTML = p.not_ranked.rows.length
    ? '<div class="tw"><table><thead><tr><th>Player</th><th>Club</th><th>League</th></tr></thead><tbody>' +
      p.not_ranked.rows.map(r => `<tr><td class="pname">${esc(dash(r.name))}</td><td>${esc(dash(r.club))}</td><td>${esc(dash(r.league))}</td></tr>`).join('') + '</tbody></table></div>'
    : `<div class="note">${esc(p.not_ranked.empty)}</div>`;
  $('about-body').innerHTML = p.about.map(t => `<p class="note">${md(t)}</p>`).join('');
  foldText();
}

/** "N affordable now" joins the info bar while affordability is on (as the Streamlit strip). */
function affordableInfo(n) {
  const bar = document.querySelector('#infobar > span');
  if (!bar) return;
  let el = $('affordable-item');
  if (n == null) { if (el) el.remove(); return; }
  if (!el) { el = document.createElement('span'); el.id = 'affordable-item'; bar.appendChild(el); }
  el.innerHTML = ` · <b>${Number(n).toLocaleString('en-GB')}</b> affordable now`;
}

/** Fold-out button captions: arrow follows the panel, Metric filters counts what is active. */
function foldText() {
  const arrow = id => ($(id).classList.contains('open') ? ' ▴' : ' ▾');
  $('more-btn').textContent = 'More filters' + arrow('more');
  $('mf-btn').textContent = (activeMetrics() ? `Metric filters · ${activeMetrics()} active` : 'Metric filters') + arrow('mf');
}

// ---- active-filter chips -----------------------------------------------------------------
function renderChips() {
  const d = defaults(), chips = [];
  const season = opts.seasons.find(s => s.id === st.season);
  chips.push(['Season', season ? season.name : st.season]);
  chips.push(['Position', st.position]);
  if (st.leagues.length && st.leagues.length < opts.leagues.length) chips.push(['Leagues', leaguesLabel(), 'leagues']);
  if (st.rank_as !== d.rank_as) chips.push(['Rank as', st.rank_as, 'rank_as']);
  chips.push(['Minutes', st.min_minutes + '+', st.min_minutes !== d.min_minutes ? 'min_minutes' : null]);
  if (st.max_age < 40) chips.push(['Max age', st.max_age, 'max_age']);
  if (st.foot !== 'Any') chips.push(['Foot', st.foot, 'foot']);
  if (st.contract !== d.contract) chips.push(['Contract', st.contract, 'contract']);
  if (st.loan !== d.loan) chips.push(['Loan', st.loan, 'loan']);
  if (st.style !== 'All styles') chips.push(['Style', st.style + (st.strong_only ? ' (strong only)' : ''), 'style']);
  if (st.money) chips.push(['Affordability', 'on', 'money']);
  if (st.assessed) chips.push(['Ranking', 'scout-verified' + (st.signed_only ? ', signed off' : ''), 'assessed']);
  if (spec) {
    for (const g of spec.physical) for (const s of g.sliders) if (s.metric in st.raw)
      chips.push([s.kind === 'Max' ? 'Max' : 'Min', `${s.label.replace(/^(Min|Max) /, '')} ${s.kind === 'Max' ? '≤' : '≥'} ${st.raw[s.metric]}`, 'raw_' + s.metric]);
    for (const m of spec.performance) if (st.pct[m.metric] > 0)
      chips.push([m.label, `≥ ${st.pct[m.metric]}th pct`, 'pct_' + m.metric]);
  }
  $('active').innerHTML = chips.map(([k, v, rm]) =>
    `<span class="fchip">${esc(k)} <b>${esc(v)}</b>` +
    (rm ? `<button type="button" data-remove="${esc(rm)}" aria-label="Remove ${esc(k)} ${esc(v)}">×</button>` : '') + '</span>').join('');
}

function removeChip(key) {
  const d = defaults();
  if (key === 'leagues') st.leagues = [];
  else if (key === 'money') { st.money = false; st.signable = null; }
  else if (key === 'assessed') { st.assessed = false; st.signed_only = false; }
  else if (key === 'style') { st.style = 'All styles'; st.strong_only = false; }
  else if (key.startsWith('pct_')) delete st.pct[key.slice(4)];
  else if (key.startsWith('raw_')) delete st.raw[key.slice(4)];
  else st[key] = d[key];
  commit();
}

// ---- events ------------------------------------------------------------------------------
const timers = {};
/** Run fn after `ms` quiet; `flush` runs it now (the control's own change event). */
function debounced(name, fn, ms = 250) { clearTimeout(timers[name]); timers[name] = setTimeout(fn, ms); }
function flush(name, fn) { clearTimeout(timers[name]); fn(); }

function onPositionChange(pos) {
  st.position = pos; st.rank_as = opts.default_archetype; st.style = 'All styles';
  st.strong_only = false; st.pct = {}; st.raw = {}; st.sort = '';
  commit();
}

function bind() {
  $('f-season').addEventListener('change', e => { st.season = Number(e.target.value); st.pct = {}; st.raw = {}; commit(); });
  $('f-position').addEventListener('change', e => onPositionChange(e.target.value));
  $('f-rank').addEventListener('change', e => { st.rank_as = e.target.value; st.pct = {}; st.raw = {}; commit(); });
  for (const [id, key] of [['f-foot', 'foot'], ['f-contract', 'contract'], ['f-loan', 'loan']])
    $(id).addEventListener('change', e => { st[key] = e.target.value; commit(); });
  $('f-style').addEventListener('change', e => { st.style = e.target.value; if (st.style === 'All styles') st.strong_only = false; commit(); });
  $('f-strong').addEventListener('change', e => { st.strong_only = e.target.checked && st.style !== 'All styles'; commit(); });

  // paired slider + number box: one value, either control may move it
  const pair = (slider, num, key, lo, hi, round) => {
    const set = v => {
      let x = Number(v); if (!isFinite(x)) return;
      x = Math.min(hi(), Math.max(lo, x)); if (round) x = Math.round(x / round) * round;
      st[key] = x; $(slider).value = x; $(num).value = x;
    };
    $(slider).addEventListener('input', e => { set(e.target.value); debounced(key, () => commit()); });
    $(slider).addEventListener('change', e => { set(e.target.value); flush(key, () => commit()); });
    $(num).addEventListener('change', e => { set(e.target.value); flush(key, () => commit()); });
  };
  pair('f-minutes', 'f-minutes-num', 'min_minutes', 450, () => opts.minutes.max, 10);
  pair('f-budget', 'f-budget-num', 'budget', 0, () => 150, 0.5);

  const age = e => { st.max_age = Number(e.target.value); $('age-out').textContent = st.max_age >= 40 ? '40+' : st.max_age; };
  $('f-age').addEventListener('input', e => { age(e); debounced('age', () => commit()); });
  $('f-age').addEventListener('change', e => { age(e); flush('age', () => commit()); });

  // wage: the £ box wins (typed figures are used exactly); a slider move is converted by the
  // server, which sends the £ back in the response.
  $('f-wage').addEventListener('change', e => { st.wage = Math.max(0, Number(e.target.value) || 0); flush('wage', () => commit()); });
  const wageX = e => { $('wagex-out').textContent = e.target.value + '×'; };
  $('f-wagex').addEventListener('input', e => { wageX(e); debounced('wagex', () => wageSlider(e.target.value)); });
  $('f-wagex').addEventListener('change', e => { wageX(e); flush('wagex', () => wageSlider(e.target.value)); });
  const wageSlider = async x => {
    const r = await api('/api/players/wage?' + new URLSearchParams({position: st.position, x}));
    st.wage = r.wage; commit();
  };
  $('f-money').addEventListener('change', e => { st.money = e.target.checked; if (!st.money) st.signable = null; commit(); });
  $('f-assessed').addEventListener('change', e => { st.assessed = e.target.checked; if (!st.assessed) st.signed_only = false; commit(); });
  $('f-signed').addEventListener('change', e => { st.signed_only = e.target.checked; commit(); });
  $('f-signable').addEventListener('change', e => { st.signable = e.target.checked ? 1 : 0; commit(); });

  // leagues pop-over
  const pop = $('leagues-pop'), btn = $('leagues-btn');
  const togglePop = open => {
    const wasOpen = !pop.hidden;
    pop.hidden = !open; btn.setAttribute('aria-expanded', String(open));
    // boxes cleared with "Untick all" but never used snap back (only when it was really open:
    // this runs on every page click and must not touch other controls mid-click)
    if (wasOpen && !open) setControls();
  };
  btn.addEventListener('click', () => togglePop(pop.hidden));
  $('leagues-all').addEventListener('click', () => { st.leagues = []; commit(); });
  // "Untick all" only clears the boxes so one league can be ticked; the list is unfiltered
  // (every league) until a box is ticked again.
  $('leagues-none').addEventListener('click', () =>
    document.querySelectorAll('#leagues-list input').forEach(i => { i.checked = false; }));
  $('leagues-list').addEventListener('change', () => {
    const on = [...document.querySelectorAll('#leagues-list input:checked')].map(i => i.value);
    st.leagues = on.length === opts.leagues.length ? [] : on; commit();
  });

  // fold-outs
  const fold = (btnId, panelId) => $(btnId).addEventListener('click', () => {
    const open = !$(panelId).classList.contains('open');
    $(panelId).classList.toggle('open', open);
    $(btnId).setAttribute('aria-expanded', String(open));
    foldText();
  });
  fold('more-btn', 'more'); fold('mf-btn', 'mf');

  // metric sliders (delegated: they are rebuilt per position)
  $('mf').addEventListener('input', e => {
    const t = e.target; if (t.type !== 'range') return;
    const v = Number(t.value), s = spec.physical.flatMap(g => g.sliders).find(x => x.metric === t.dataset.metric);
    t.nextElementSibling.querySelector('.val').textContent = t.dataset.kind === 'raw' && s ? v.toFixed(s.decimals) : v;
    setMetric(t.dataset.kind, t.dataset.metric, v);
    debounced('mf', () => commit());
  });
  $('mf').addEventListener('change', e => { if (e.target.type === 'range') flush('mf', () => commit()); });
  $('ph-tabs').addEventListener('click', e => { const b = e.target.closest('button'); if (b) showTab(Number(b.dataset.tab)); });
  $('mf-reset').addEventListener('click', () => { st.pct = {}; st.raw = {}; commit(); });

  $('active').addEventListener('click', e => { const b = e.target.closest('[data-remove]'); if (b) removeChip(b.dataset.remove); });

  // sort: ascending -> descending -> back to the ranking order
  $('pl-head').addEventListener('click', e => {
    const b = e.target.closest('[data-sort]'); if (!b) return;
    const c = b.dataset.sort;
    if (st.sort !== c) { st.sort = c; st.dir = 'asc'; }
    else if (st.dir === 'asc') st.dir = 'desc';
    else { st.sort = ''; st.dir = 'desc'; }
    commit();
  });

  // rows open the card (Ctrl/Cmd-click: new tab)
  const open = (tr, newTab) => { const h = tr.dataset.href; if (!h) return; newTab ? window.open(h, '_blank', 'noopener') : window.location.assign(h); };
  $('pl-body').addEventListener('click', e => { const tr = e.target.closest('tr[data-href]'); if (tr) open(tr, e.ctrlKey || e.metaKey); });
  $('pl-body').addEventListener('keydown', e => { if (e.key === 'Enter') { const tr = e.target.closest('tr[data-href]'); if (tr) open(tr, false); } });

  bindSearch();
  document.addEventListener('click', e => {
    if (!e.target.closest('.popwrap')) togglePop(false);
    if (!e.target.closest('.searchbox')) $('search-results').hidden = true;
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { togglePop(false); $('search-results').hidden = true; } });
  window.addEventListener('popstate', () => { st = fromUrl(); refresh(); });
}

// ---- search: every position and league this season ----------------------------------------
let searchSeq = 0;
function bindSearch() {
  const box = $('f-search'), out = $('search-results'), clear = $('search-clear');
  const run = async () => {
    const q = box.value.trim(), mine = ++searchSeq;
    clear.disabled = !box.value;
    if (!q) { out.hidden = true; return; }
    let r;
    try { r = await api('/api/players/search?' + new URLSearchParams({season: st.season, q})); }
    catch (e) { return; }
    if (mine !== searchSeq) return;
    out.innerHTML = r.results.length
      ? r.results.map((x, i) => `<button type="button" data-action="pick" data-i="${i}">${esc(x.label)}</button>`).join('')
      : '<div class="none">No player found.</div>';
    out.hidden = false;
    out._results = r.results;
  };
  box.addEventListener('input', () => { clear.disabled = !box.value; debounced('search', run, 200); });
  clear.addEventListener('click', () => { box.value = ''; clear.disabled = true; out.hidden = true; ++searchSeq; });
  out.addEventListener('click', e => {
    const b = e.target.closest('[data-action="pick"]'); if (!b) return;
    pickPlayer(out._results[Number(b.dataset.i)]);
  });
}

/** Choosing a result switches Position to his (and adds his league if it was filtered out) so
 *  "Back" returns to a list that contains him, then opens his card. */
function pickPlayer(r) {
  const next = JSON.parse(JSON.stringify(st));
  if (r.position !== st.position) {
    next.position = r.position; next.rank_as = opts.default_archetype; next.style = 'All styles';
    next.strong_only = false; next.pct = {}; next.raw = {};
  }
  if (next.leagues.length && r.league && !next.leagues.includes(r.league)) next.leagues.push(r.league);
  window.location.assign(`/player/${r.player_id}/${r.competition_id}/${r.season_id}?back=` +
    encodeURIComponent('/players' + toQuery(next)));
}

// ---- start -------------------------------------------------------------------------------
(async function init() {
  // The three first-load requests run side by side (the server validates the query itself);
  // the answers are used as long as the URL was already in its normal form.
  restoreState('players');      // a bare /players (the nav link) takes the last settings
  const first = location.search;
  const optsP = api('/api/players/options');
  prefetch = {qs: first, spec: api('/api/players/metrics' + first), list: api('/api/players' + first)};
  prefetch.spec.catch(() => {}); prefetch.list.catch(() => {});
  opts = await optsP;
  buildStaticControls();
  st = fromUrl();
  bind();
  await refresh();
  if (activeMetrics()) { $('mf').classList.add('open'); $('mf-btn').setAttribute('aria-expanded', 'true'); foldText(); }
})();
