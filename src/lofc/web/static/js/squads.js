// Squads & loans page. Fetches /api/squads and draws it; computes no number and filters no
// row (every row, tile, option list and cell text comes from the API, which calls the same
// Python as the Streamlit page). The URL query string is the whole page state: shareable,
// back/forward restore it.
import {api, esc, chip} from './common.js';

const $ = id => document.getElementById(id);
const DASH = '—';

let P = null;            // last payload
let st = null;           // current state (mirrors the URL)
let seq = 0;             // newest request; older answers are ignored

// ---- state <-> URL -----------------------------------------------------------------------
const DEFAULTS = {league: 'All', club: 'All', position: 'All', q: '', show: '', max_age: 40,
                  leagues: [], foot: 'Any', contract: 'Any', loan: 'Any', sort: '', dir: 'desc'};

function fromUrl() {
  const q = new URLSearchParams(location.search), s = {...DEFAULTS, leagues: []};
  for (const k of ['league', 'club', 'position', 'q', 'show', 'foot', 'contract', 'loan', 'sort', 'dir'])
    if (q.get(k) != null) s[k] = q.get(k);
  const age = Number(q.get('max_age'));
  if (q.get('max_age') && isFinite(age)) s.max_age = Math.min(40, Math.max(18, age));
  s.leagues = q.getAll('leagues');
  return s;
}

/** Query string: only values that differ from the defaults. */
function toQuery(s) {
  const q = new URLSearchParams();
  for (const k of ['league', 'club', 'position', 'q', 'show', 'max_age', 'foot', 'contract', 'loan'])
    if (s[k] !== '' && s[k] != null && String(s[k]) !== String(DEFAULTS[k])) q.set(k, s[k]);
  s.leagues.forEach(l => q.append('leagues', l));
  if (s.sort) { q.set('sort', s.sort); q.set('dir', s.dir); }
  const t = q.toString();
  return t ? '?' + t : '';
}

function commit({replace = false} = {}) {
  const qs = toQuery(st);
  // Nothing changed (e.g. the Show option already selected): keep the page, no refetch of
  // ~3,800 rows.
  if (qs === location.search && P) { setControls(); return Promise.resolve(); }
  if (qs !== location.search) history[replace ? 'replaceState' : 'pushState']({}, '', location.pathname + qs);
  return load();
}

// ---- drawing -----------------------------------------------------------------------------
const opt = (v, label) => `<option value="${esc(v)}">${esc(label ?? v)}</option>`;

function fillSelect(id, values, current) {
  const el = $(id);
  el.innerHTML = values.map(v => opt(v)).join('');
  el.value = current;
}

function leaguesLabel() {
  const n = st.leagues.length;
  return n === 0 ? 'All leagues' : n === 1 ? st.leagues[0] : `${n} leagues`;
}

function moreCount() {
  return (st.max_age < 40) + (st.leagues.length > 0) + (st.foot !== 'Any') + (st.contract !== 'Any') + (st.loan !== 'Any');
}

function setControls() {
  const o = P.options;
  fillSelect('f-league', o.league, st.league);
  fillSelect('f-club', o.club, st.club);
  fillSelect('f-position', o.position, st.position);
  if (document.activeElement !== $('f-q')) $('f-q').value = st.q;
  $('f-show').innerHTML = o.show.map(x =>
    `<button type="button" data-show="${esc(x.code)}" aria-pressed="${x.code === st.show}" class="${x.code === st.show ? 'on' : ''}">${esc(x.label)}</button>`).join('');
  $('f-age').value = st.max_age; $('age-out').textContent = st.max_age >= 40 ? '40+' : st.max_age;
  if (!$('f-foot').options.length) {
    $('f-foot').innerHTML = o.foot.map(v => opt(v)).join('');
    $('f-contract').innerHTML = o.contract.map(v => opt(v)).join('');
    $('f-loan').innerHTML = o.loan.map(v => opt(v)).join('');
    $('leagues-list').innerHTML = o.leagues.map((l, i) =>
      `<label><input type="checkbox" name="league_${i}" value="${esc(l)}" aria-label="${esc(l)}">${esc(l)}</label>`).join('');
  }
  $('f-foot').value = st.foot; $('f-contract').value = st.contract; $('f-loan').value = st.loan;
  const sel = st.leagues.length ? new Set(st.leagues) : new Set(o.leagues);
  document.querySelectorAll('#leagues-list input').forEach(i => { i.checked = sel.has(i.value); });
  $('leagues-btn').textContent = leaguesLabel();
  const n = moreCount(), open = $('more').classList.contains('open');
  $('more-btn').textContent = `More filters${n ? ` (${n})` : ''} ${open ? '▴' : '▾'}`;
}

function cell(c, v) {
  if (v && typeof v === 'object')            // a thin pool's composite: withheld, with the note
    return `<td class="c"><span class="chip c0" title="${esc(v.note)}" aria-label="${esc(v.note)}">${esc(v.t)}</span><span class="hlp" title="${esc(v.note)}">ⓘ</span></td>`;
  if (c.kind === 'rating') return `<td class="c">${v === DASH ? `<span class="chip c0">${DASH}</span>` : chip(v)}</td>`;
  if (c.kind === 'num') return `<td class="n">${esc(v)}</td>`;
  if (c.key === 'Player') return `<td class="pname cut" title="${esc(v)}">${esc(v)}</td>`;
  if (c.key === 'Club' || c.key === 'On loan from') return `<td class="cut" title="${esc(v)}">${esc(v)}</td>`;
  return `<td>${esc(v)}</td>`;
}

const FIRST_ROWS = 150, NEXT_ROWS = 300;
let drawn = 0;
const rowHtml = i => {
  const r = P.rows[i], link = P.links[i], back = encodeURIComponent('/squads' + location.search);
  const attr = link ? `data-href="${esc(link)}?back=${back}"` : `data-row="${i}"`;
  return `<tr class="click" tabindex="0" ${attr}>` + P.columns.map((c, j) => cell(c, r[j])).join('') + '</tr>';
};

/** Append the next `n` rows (and keep a sentinel row after them while rows remain). */
function more(n) {
  const body = $('sq-body'), stop = Math.min(P.rows.length, drawn + n);
  body.querySelector('tr.sentinel')?.remove();
  const html = [];
  for (let i = drawn; i < stop; i++) html.push(rowHtml(i));
  body.insertAdjacentHTML('beforeend', html.join(''));
  drawn = stop;
  if (drawn < P.rows.length) {
    body.insertAdjacentHTML('beforeend', `<tr class="sentinel"><td colspan="${P.columns.length}" class="note">${(P.rows.length - drawn).toLocaleString('en-GB')} more rows…</td></tr>`);
    watcher.observe(body.querySelector('tr.sentinel'));
  }
}
const watcher = new IntersectionObserver(es => {
  if (es.some(e => e.isIntersecting)) { watcher.disconnect(); more(NEXT_ROWS); }
}, {root: document.getElementById('tw'), rootMargin: '400px'});

function draw() {
  $('sq-title').textContent = P.title;
  $('sq-meta').textContent = P.meta;
  $('sq-asof').textContent = P.asof || '';
  $('sq-asof').hidden = !P.asof;
  $('sq-banner').innerHTML = (P.warning ? `<div class="warn">${esc(P.warning)}</div>` : '')
    + (P.empty ? `<div class="info">${esc(P.empty)}</div>` : '');
  $('sq-tiles').innerHTML = P.tiles.map(t =>
    `<div class="tile"><div class="k">${esc(t.label)}</div><div class="v">${esc(t.value)}</div></div>`).join('');
  $('sq-card').hidden = !!P.empty;
  setControls();
  const cols = P.columns, sort = P.state.sort ? P.state : null;
  $('sq-head').innerHTML = '<tr>' + cols.map(c => {
    const on = sort && sort.sort === c.key, arrow = on ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '';
    const cls = (c.kind === 'num' ? 'n' : c.kind === 'rating' ? 'c' : '') + (on ? ' sorted' : '');
    return `<th class="${cls.trim()}"${c.help ? ` title="${esc(c.help)}"` : ''}><button type="button" data-sort="${esc(c.key)}">${esc(c.label)}${c.help ? '<span class="hlp">ⓘ</span>' : ''}${arrow}</button></th>`;
  }).join('') + '</tr>';
  // Rows are drawn in pages as the table scrolls (the full list is ~3,800 rows; drawing them
  // all at once cost most of a click). Every row is already in P; nothing is refetched.
  drawn = 0;
  $('sq-body').dataset.total = P.rows.length;
  $('sq-body').innerHTML = P.rows.length ? '' : `<tr><td colspan="${cols.length}" class="note">No players match these filters.</td></tr>`;
  more(FIRST_ROWS);
  $('tw').scrollTop = 0;
  $('sq-click').innerHTML = '';
  const csv = $('csv');
  csv.textContent = P.csv.label; csv.title = P.csv.help;
  csv.href = '/api/squads.csv' + location.search;
  csv.setAttribute('download', P.csv.name);
  $('sq-foot').textContent = P.footer;
}

async function load() {
  const mine = ++seq;
  let p;
  try { p = await api('/api/squads' + location.search); }
  catch (e) {
    if (mine === seq) $('sq-banner').innerHTML = `<div class="warn">Could not load the squads (${esc(e.message)}).</div>`;
    return;
  }
  if (mine !== seq) return;
  P = p;
  // the server's resolved choices win (a club not in the chosen league falls back to All)
  Object.assign(st, {league: p.state.league, club: p.state.club, position: p.state.position,
                     show: p.state.show, max_age: p.state.max_age, foot: p.state.foot,
                     contract: p.state.contract, loan: p.state.loan, leagues: p.state.leagues,
                     sort: p.state.sort || '', dir: p.state.dir});
  const qs = toQuery(st);
  if (qs !== location.search) history.replaceState({}, '', location.pathname + qs);
  draw();
}

// ---- events ------------------------------------------------------------------------------
const timers = {};
const debounced = (name, fn, ms = 250) => { clearTimeout(timers[name]); timers[name] = setTimeout(fn, ms); };

function bind() {
  $('f-league').addEventListener('change', e => { st.league = e.target.value; st.club = 'All'; commit(); });
  $('f-club').addEventListener('change', e => { st.club = e.target.value; commit(); });
  $('f-position').addEventListener('change', e => { st.position = e.target.value; commit(); });
  for (const [id, key] of [['f-foot', 'foot'], ['f-contract', 'contract'], ['f-loan', 'loan']])
    $(id).addEventListener('change', e => { st[key] = e.target.value; commit(); });
  $('f-q').addEventListener('input', e => { st.q = e.target.value; debounced('q', () => commit({replace: true}), 300); });
  $('f-q').addEventListener('change', e => { st.q = e.target.value; clearTimeout(timers.q); commit(); });
  $('f-show').addEventListener('click', e => {
    const b = e.target.closest('[data-show]'); if (!b) return;
    st.show = b.dataset.show; commit();
  });
  const age = e => { st.max_age = Number(e.target.value); $('age-out').textContent = st.max_age >= 40 ? '40+' : st.max_age; };
  $('f-age').addEventListener('input', e => { age(e); debounced('age', () => commit()); });
  $('f-age').addEventListener('change', e => { age(e); clearTimeout(timers.age); commit(); });

  $('more-btn').addEventListener('click', () => {
    const open = !$('more').classList.contains('open');
    $('more').classList.toggle('open', open);
    $('more-btn').setAttribute('aria-expanded', String(open));
    setControls();
  });

  // leagues pop-over (the sidebar's Leagues: every league ticked = no league filter)
  const pop = $('leagues-pop'), btn = $('leagues-btn');
  const togglePop = open => {
    const was = !pop.hidden;
    pop.hidden = !open; btn.setAttribute('aria-expanded', String(open));
    if (was && !open && P) setControls();
  };
  btn.addEventListener('click', () => togglePop(pop.hidden));
  $('leagues-all').addEventListener('click', () => { st.leagues = []; commit(); });
  $('leagues-none').addEventListener('click', () =>
    document.querySelectorAll('#leagues-list input').forEach(i => { i.checked = false; }));
  $('leagues-list').addEventListener('change', () => {
    const on = [...document.querySelectorAll('#leagues-list input:checked')].map(i => i.value);
    st.leagues = on.length === P.options.leagues.length ? [] : on; commit();
  });

  // sort: ascending -> descending -> back to the page's order
  $('sq-head').addEventListener('click', e => {
    const b = e.target.closest('[data-sort]'); if (!b) return;
    const c = b.dataset.sort;
    if (st.sort !== c) { st.sort = c; st.dir = 'asc'; }
    else if (st.dir === 'asc') st.dir = 'desc';
    else { st.sort = ''; st.dir = 'desc'; }
    commit();
  });

  // rows: open the card (Ctrl/Cmd-click: new tab), or say why there is no card
  const open = (tr, newTab) => {
    document.querySelectorAll('#sq-body tr.me').forEach(x => x.classList.remove('me'));
    if (tr.dataset.href) { newTab ? window.open(tr.dataset.href, '_blank', 'noopener') : window.location.assign(tr.dataset.href); return; }
    tr.classList.add('me');
    const m = P.messages[Number(tr.dataset.row)];
    $('sq-click').innerHTML = m ? `<div class="info">${esc(m)}</div>` : '';
  };
  $('sq-body').addEventListener('click', e => { const tr = e.target.closest('tr.click'); if (tr) open(tr, e.ctrlKey || e.metaKey); });
  $('sq-body').addEventListener('keydown', e => { if (e.key === 'Enter') { const tr = e.target.closest('tr.click'); if (tr) open(tr, false); } });

  document.addEventListener('click', e => { if (!e.target.closest('.popwrap')) togglePop(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') togglePop(false); });
  window.addEventListener('popstate', () => { st = fromUrl(); load(); });
}

(function init() {
  st = fromUrl();
  bind();
  load().then(() => {
    if (moreCount()) { $('more').classList.add('open'); $('more-btn').setAttribute('aria-expanded', 'true'); setControls(); }
  });
})();
