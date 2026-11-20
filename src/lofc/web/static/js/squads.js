// Squads & loans page. Fetches /api/squads and draws it; computes no number and filters no
// row (rows, tiles, option lists, cell text and the date line all come from the API). The URL
// query string is the whole page state: shareable, back/forward restore it, and the nav link
// reopens the last settings (common.js rememberState / restoreState).
import {api, esc, chip, rememberState, restoreState} from './common.js';

const $ = id => document.getElementById(id);
const DASH = '—';

let P = null;            // last payload
let st = null;           // current state (mirrors the URL)
let seq = 0;             // newest request; older answers are ignored

// ---- state <-> URL -----------------------------------------------------------------------
const DEFAULTS = {league: '', club: '', view: 'squad', position: 'All', q: '', max_age: 40,
                  contract: 'Any', loan: 'Any', foot: 'Any', sort: '', dir: 'desc'};
const KEYS = ['league', 'club', 'view', 'position', 'q', 'max_age', 'contract', 'loan', 'foot'];

function fromUrl() {
  const q = new URLSearchParams(location.search), s = {...DEFAULTS};
  for (const k of [...KEYS, 'sort', 'dir']) if (q.get(k) != null) s[k] = q.get(k);
  const age = Number(s.max_age);
  s.max_age = isFinite(age) ? Math.min(40, Math.max(16, age)) : 40;
  return s;
}

/** Query string: league and club always (the page opens on Leyton Orient without them), the
 *  rest only where they differ from the defaults. */
function toQuery(s) {
  const q = new URLSearchParams();
  for (const k of KEYS) {
    const always = k === 'league' || k === 'club';
    if (s[k] !== '' && s[k] != null && (always || String(s[k]) !== String(DEFAULTS[k]))) q.set(k, s[k]);
  }
  if (s.sort) { q.set('sort', s.sort); q.set('dir', s.dir); }
  const t = q.toString();
  return t ? '?' + t : '';
}

function commit({replace = false} = {}) {
  const qs = toQuery(st);
  if (qs === location.search && P) { setControls(); return Promise.resolve(); }
  history[replace ? 'replaceState' : 'pushState']({}, '', location.pathname + qs);
  return load();
}

// ---- drawing -----------------------------------------------------------------------------
const opt = v => `<option value="${esc(v)}">${esc(v)}</option>`;

function fillSelect(id, values, current) {
  const el = $(id);
  el.innerHTML = values.map(opt).join('');
  el.value = current;
}

function setControls() {
  const o = P.options;
  fillSelect('f-league', o.league, st.league);
  fillSelect('f-club', o.club, st.club);
  fillSelect('f-position', o.position, st.position);
  fillSelect('f-contract', o.contract, st.contract);
  fillSelect('f-loan', o.loan, st.loan);
  fillSelect('f-foot', o.foot || ['Any'], st.foot);
  if (document.activeElement !== $('f-q')) $('f-q').value = st.q;
  $('f-view').innerHTML = o.view.map(x =>
    `<button type="button" data-view="${esc(x.code)}" aria-pressed="${x.code === st.view}" class="${x.code === st.view ? 'on' : ''}">${esc(x.label)}</button>`).join('');
  $('f-age').value = st.max_age; $('age-out').textContent = st.max_age >= 40 ? 'Any' : st.max_age;
}

function playerCell(v, link) {
  const back = encodeURIComponent('/squads' + location.search);
  const name = link ? `<a href="${esc(link)}?back=${back}">${esc(v.t)}</a>` : esc(v.t);
  const marks = (v.marks || []).map(m => `<span class="mk">${esc(m)}</span>`).join('');
  return `<td class="pname" title="${esc(v.t)}">${name}${marks}</td>`;
}

function cell(c, v, link) {
  if (c.key === 'Player') return playerCell(v, link);
  if (v && typeof v === 'object' && v.tag)   // rated against all midfielders: the tag on hover
    return `<td class="c">${chip(v.t)}<span class="hlp" title="${esc(v.tag)}" aria-label="${esc(v.tag)}">ⓘ</span></td>`;
  if (v && typeof v === 'object')            // a thin pool: withheld, with the not-rated line
    return `<td class="c"><span class="chip c0" title="${esc(v.note)}" aria-label="${esc(v.note)}">${esc(v.t)}</span><span class="hlp" title="${esc(v.note)}">ⓘ</span></td>`;
  if (c.kind === 'rating') return `<td class="c">${v === DASH ? `<span class="chip c0">${DASH}</span>` : chip(v)}</td>`;
  if (c.kind === 'num') return `<td class="n">${esc(v)}</td>`;
  if (c.kind === 'tm') return `<td class="cut${P.stale && v !== DASH ? ' stale' : ''}" title="${esc(v)}">${esc(v)}</td>`;
  return `<td class="cut" title="${esc(v)}">${esc(v)}</td>`;
}

const FIRST_ROWS = 150, NEXT_ROWS = 300;
let drawn = 0;
const rowHtml = i => {
  const link = P.links[i], back = encodeURIComponent('/squads' + location.search);
  const attr = link ? `data-href="${esc(link)}?back=${back}"` : `data-row="${i}"`;
  return `<tr class="click" tabindex="0" ${attr}>` + P.columns.map((c, j) => cell(c, P.rows[i][j], link)).join('') + '</tr>';
};

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
  $('sq-meta').textContent = P.meta || ' ';
  $('sq-asof').innerHTML = P.asof.map(a => `<span${a.stale ? ' class="stale"' : ''}>${esc(a.t)}</span>`).join(' · ');
  $('sq-banner').innerHTML = P.empty ? `<div class="info">${esc(P.empty)}</div>` : '';
  $('sq-tiles').innerHTML = P.tiles.map(t =>
    `<div class="tile"><div class="k">${esc(t.label)}</div><div class="v">${esc(t.value)}</div></div>`).join('');
  $('sq-card').hidden = !!P.empty;
  if (P.empty) return;
  setControls();
  const sort = P.state.sort ? P.state : null;
  $('sq-head').innerHTML = '<tr>' + P.columns.map(c => {
    const on = sort && sort.sort === c.key, arrow = on ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '';
    const cls = (c.kind === 'num' ? 'n' : c.kind === 'rating' ? 'c' : '') + (on ? ' sorted' : '');
    const help = c.help ? '<span class="hlp">ⓘ</span>' : '';
    const label = c.sortable
      ? `<button type="button" data-sort="${esc(c.key)}">${esc(c.label)}${help}${arrow}</button>`
      : `<span class="nosort">${esc(c.label)}${help}</span>`;
    return `<th class="${cls.trim()}"${c.help ? ` title="${esc(c.help)}"` : ''}>${label}</th>`;
  }).join('') + '</tr>';
  drawn = 0;
  $('sq-body').dataset.total = P.rows.length;
  $('sq-body').innerHTML = P.rows.length ? '' : `<tr><td colspan="${P.columns.length}" class="note">No players match these filters.</td></tr>`;
  more(FIRST_ROWS);
  $('tw').scrollTop = 0;
  $('sq-click').innerHTML = '';
  const csv = $('csv');
  csv.textContent = P.csv.label;
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
  if (p.state && p.state.league) {
    Object.assign(st, p.state, {sort: p.state.sort || '', q: st.q});
    const qs = toQuery(st);
    if (qs !== location.search) history.replaceState({}, '', location.pathname + qs);
    rememberState('squads');
  }
  draw();
}

// ---- events ------------------------------------------------------------------------------
const timers = {};
const debounced = (name, fn, ms = 250) => { clearTimeout(timers[name]); timers[name] = setTimeout(fn, ms); };

function bind() {
  $('f-league').addEventListener('change', e => { st.league = e.target.value; st.club = 'All'; st.position = 'All'; commit(); });
  $('f-club').addEventListener('change', e => { st.club = e.target.value; commit(); });
  for (const [id, key] of [['f-position', 'position'], ['f-contract', 'contract'], ['f-loan', 'loan'], ['f-foot', 'foot']])
    $(id).addEventListener('change', e => { st[key] = e.target.value; commit(); });
  $('f-q').addEventListener('input', e => { st.q = e.target.value; debounced('q', () => commit({replace: true}), 300); });
  $('f-q').addEventListener('change', e => { st.q = e.target.value; clearTimeout(timers.q); commit(); });
  $('f-view').addEventListener('click', e => {
    const b = e.target.closest('[data-view]'); if (!b) return;
    st.view = b.dataset.view; commit();
  });
  const age = e => { st.max_age = Number(e.target.value); $('age-out').textContent = st.max_age >= 40 ? 'Any' : st.max_age; };
  $('f-age').addEventListener('input', e => { age(e); debounced('age', () => commit()); });
  $('f-age').addEventListener('change', e => { age(e); clearTimeout(timers.age); commit(); });

  // sort: ascending -> descending -> back to the page's order (most minutes first)
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
  $('sq-body').addEventListener('click', e => {
    if (e.target.closest('a')) return;      // the name link navigates by itself
    const tr = e.target.closest('tr.click'); if (tr) open(tr, e.ctrlKey || e.metaKey);
  });
  $('sq-body').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.target.closest('a')) { const tr = e.target.closest('tr.click'); if (tr) open(tr, false); } });
  window.addEventListener('popstate', () => { st = fromUrl(); load(); });
}

(function init() {
  restoreState('squads');       // a bare /squads (the nav link) takes the last settings
  st = fromUrl();
  bind();
  load();
})();
