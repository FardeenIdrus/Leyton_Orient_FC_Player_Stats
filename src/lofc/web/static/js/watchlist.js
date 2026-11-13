// Watchlist page (mockup v5 v-watchlist). Draws what /api/watchlist sends: every value, count and
// label comes from the API (the Streamlit page's own functions). The URL holds the assessment
// status filter, the Market value switch, the sort and the open row. Notes are free text: they
// only reach the page through esc() or .value / textContent.
import {api, esc, dash, rememberState, restoreState} from './common.js';

const $ = id => document.getElementById(id);
let seq = 0, last = null;

// ---- state <-> URL -----------------------------------------------------------------------
function state() {
  const q = new URLSearchParams(location.search);
  return {status: q.has('status') ? q.getAll('status').filter(Boolean) : null,   // null = all
    money: q.get('money') === '1', sort: q.get('sort') || '', dir: q.get('dir') || '',
    open: q.get('open') || ''};
}
function toQuery(s, {forApi = false} = {}) {
  const q = new URLSearchParams();
  if (s.status !== null) { if (s.status.length) s.status.forEach(v => q.append('status', v)); else q.set('status', ''); }
  if (s.money) q.set('money', '1');
  if (!forApi) {
    if (s.sort) q.set('sort', s.sort);
    if (s.dir) q.set('dir', s.dir);
    if (s.open) q.set('open', s.open);
  }
  const t = q.toString();
  return t ? '?' + t : '';
}
function commit(s, {replace = false} = {}) {
  const url = location.pathname + toQuery(s);
  if (url !== location.pathname + location.search) history[replace ? 'replaceState' : 'pushState']({}, '', url);
  remember();
}
const backQ = () => '?back=' + encodeURIComponent('/watchlist' + location.search);

// ---- drawing -----------------------------------------------------------------------------
const chipFor = (text, v) => v == null ? '<span class="chip c0">—</span>'
  : `<span class="chip ${v >= 4 ? 'c4' : v >= 3 ? 'c3' : v >= 2 ? 'c2' : 'c1'}">${esc(text)}</span>`;
const NUM = new Set(['Age', 'Market value', 'Months left']);
const CUT = new Set(['Club', 'League', 'Injury', 'Note']);

function drawFilters(d, s) {
  $('wl-status-help').title = d.status_help;
  const chosen = new Set(d.chosen);
  $('wl-status').innerHTML = d.statuses.map((v, i) =>
    `<label class="wl-check"><input type="checkbox" id="st-${i}" value="${esc(v)}"${chosen.has(v) ? ' checked' : ''}>${esc(v)}</label>`).join('');
  $('f-money').checked = d.money;
  $('sw-money').classList.toggle('on', d.money);
}

function sortRows(rows, s) {
  if (!s.sort) return rows;
  const dir = s.dir === 'desc' ? -1 : 1;
  const val = (r, k) => k === 'Note' ? (r.note || '—') : (r.cells[k] ?? '—');
  const cmp = (a, b) => {
    const x = val(a, s.sort), y = val(b, s.sort);
    if (x === '—' && y === '—') return 0;
    if (x === '—') return 1;
    if (y === '—') return -1;
    return dir * x.localeCompare(y, 'en', {numeric: true, sensitivity: 'base'});
  };
  return rows.map((r, i) => [r, i]).sort((p, q) => cmp(p[0], q[0]) || p[1] - q[1]).map(p => p[0]);
}

function drawTable(d, s) {
  const cols = d.columns;
  $('wl-thead').innerHTML = '<tr>' + cols.map(c => {
    const on = s.sort === c, arrow = on ? (s.dir === 'desc' ? ' ▼' : ' ▲') : '';
    const tip = d.help[c] ? ` title="${esc(d.help[c])}"` : '';
    const cls = [on ? 'sorted' : '', NUM.has(c) ? 'n' : '', ['Composite', 'Performance', 'Physical'].includes(c) ? 'c' : ''].join(' ').trim();
    if (c === 'Transfermarkt') return `<th>${esc(c)}</th>`;
    return `<th class="${cls}"${tip}><button type="button" data-sort="${esc(c)}" aria-label="Sort by ${esc(c)}">${esc(c)}${arrow}</button></th>`;
  }).join('') + '</tr>';
  $('wl-body').innerHTML = sortRows(d.rows, s).map(r => `<tr data-row="${esc(r.key)}" class="click${r.key === s.open ? ' me' : ''}">` + cols.map(c => {
    if (c === 'Player') {
      const name = `<span class="pname">${esc(dash(r.cells.Player))}</span>`;
      const nr = r.not_rated ? `<div class="note wl-nr">${esc(r.not_rated)}</div>` : '';
      return `<td class="pcell">${r.href ? `<a class="plink" href="${esc(r.href + backQ())}">${name}</a>` : name}${nr}</td>`;
    }
    if (['Composite', 'Performance', 'Physical'].includes(c)) return `<td class="c">${chipFor(r.cells[c], r.ratings[c])}</td>`;
    if (c === 'Transfermarkt') return `<td>${r.tm ? `<a href="${esc(r.tm)}" target="_blank" rel="noopener noreferrer">Open profile ↗</a>` : '—'}</td>`;
    if (c === 'Assessed') {
      const v = dash(r.cells[c]);
      return `<td>${v === 'Not assessed' ? `<span class="pill grey">${esc(v)}</span>` : esc(v)}</td>`;
    }
    const v = c === 'Note' ? (r.note || '—') : dash(r.cells[c]);
    if (CUT.has(c)) return `<td class="cut" title="${esc(v)}">${esc(v)}</td>`;
    return `<td class="${NUM.has(c) ? 'n' : ''}">${esc(v)}</td>`;
  }).join('') + '</tr>').join('');
}

function draw(d, s) {
  last = d;
  if (d.empty) {
    $('wl-empty').hidden = false; $('wl-empty').textContent = d.text; $('wl-main').hidden = true;
    return;
  }
  $('wl-empty').hidden = true; $('wl-main').hidden = false;
  drawFilters(d, s);
  $('wl-none').hidden = !d.none_match;
  $('wl-none').textContent = d.none_match || '';
  const any = d.rows.length > 0;
  $('wl-tiles').hidden = !any; $('wl-card').hidden = !any;
  $('wl-tiles').innerHTML = d.tiles.map(t =>
    `<div class="tile"><div class="k">${esc(t.label)}${t.help ? ` <span class="hlp" title="${esc(t.help)}">?</span>` : ''}</div><div class="v">${esc(t.value)}</div></div>`).join('');
  $('wl-dl').href = '/api/watchlist/csv' + toQuery(s, {forApi: true});
  drawTable(d, s);
  openEditor(d.rows.find(r => r.key === s.open) || null, d);
}

// ---- editor ------------------------------------------------------------------------------
function openEditor(row, d) {
  const box = $('wl-edit');
  $('e-msg').textContent = '';
  if (!row) { box.hidden = true; box.dataset.key = ''; return; }
  const sameRow = box.dataset.key === row.key && !box.hidden;
  box.hidden = false; box.dataset.key = row.key;
  $('e-title').textContent = dash(row.cells.Player);
  $('e-sub').textContent = dash(row.cells.Club);
  if (!sameRow) {
    $('e-note').value = row.note || '';
    const opts = d.manual_statuses.includes(row.status) ? d.manual_statuses : [...d.manual_statuses, row.status];
    $('e-status').innerHTML = opts.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
    $('e-status').value = row.status;
  }
  $('e-assess').href = row.assess_href;
}
const openKey = () => $('wl-edit').dataset.key || '';

async function write(fn, okText) {
  const msg = $('e-msg'), btns = ['e-save', 'e-remove'].map($);
  btns.forEach(b => { b.disabled = true; });
  try {
    await fn();
    const s = state(); s.open = ''; commit(s);          // Streamlit closes the dialog on save
    await load();
    msg.textContent = '';
    $('wl-count').textContent = okText;
  } catch (e) {
    msg.textContent = `Not saved (${e.status === 404 ? 'no longer on the watchlist' : e.message}).`;
  } finally { btns.forEach(b => { b.disabled = false; }); }
}

// ---- loading -----------------------------------------------------------------------------
async function load() {
  const s = state(), mine = ++seq;
  try {
    const d = await api('/api/watchlist' + toQuery(s, {forApi: true}));
    if (mine === seq) { $('wl-count').textContent = ''; draw(d, s); remember(); }
  } catch (e) {
    if (mine === seq) { $('wl-empty').hidden = false; $('wl-empty').textContent = `Could not load the watchlist (${e.message}).`; }
  }
}

// owner 2026-11-13: the nav link (a bare URL) reopens the last filters and sort; the open row
// is a one-off and is not kept
const remember = () => rememberState('watchlist', {drop: ['open']});

function init() {
  restoreState('watchlist');
  $('wl-status').onchange = () => {
    const s = state();
    const picked = [...document.querySelectorAll('#wl-status input:checked')].map(i => i.value);
    s.status = last && picked.length === last.statuses.length ? null : picked;
    commit(s); load();
  };
  $('f-money').onchange = ev => { const s = state(); s.money = ev.target.checked; commit(s); load(); };
  $('wl-thead').onclick = ev => {
    const b = ev.target.closest('[data-sort]');
    if (!b || !last) return;
    const s = state(), k = b.dataset.sort;
    if (s.sort !== k) { s.sort = k; s.dir = ''; } else if (s.dir !== 'desc') s.dir = 'desc'; else { s.sort = ''; s.dir = ''; }
    commit(s);
    drawTable(last, s);
  };
  $('wl-body').onclick = ev => {
    if (ev.target.closest('a')) return;                        // name -> card, Transfermarkt -> new tab
    const tr = ev.target.closest('tr[data-row]');
    if (!tr || !last) return;
    const s = state(); s.open = tr.dataset.row; commit(s);
    document.querySelectorAll('#wl-body tr.me').forEach(x => x.classList.remove('me'));
    tr.classList.add('me');
    openEditor(last.rows.find(r => r.key === s.open), last);
    $('wl-edit').scrollIntoView({block: 'nearest'});
  };
  $('e-close').onclick = () => {
    const s = state(); s.open = ''; commit(s);
    document.querySelectorAll('#wl-body tr.me').forEach(x => x.classList.remove('me'));
    openEditor(null, last);
  };
  $('e-save').onclick = () => {
    const k = openKey(); if (!k) return;
    write(() => api('/api/watchlist/' + k.split('-').join('/'),
      {json: {note: $('e-note').value, status: $('e-status').value}}), 'Saved.');
  };
  $('e-remove').onclick = () => {
    const k = openKey(); if (!k) return;
    write(() => api('/api/card/' + k.split('-').join('/') + '/watchlist', {json: {action: 'remove'}}),
      'Removed from the watchlist.');
  };
  window.addEventListener('popstate', load);
  load();
}
init();
