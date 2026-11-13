// Scout reports page (mockup v5 v-scout). Draws what /api/scout-reports sends: every row, label,
// caption and option comes from the API (the Streamlit page's own functions). The URL query
// string is the page state (tab, filters, sort, open report). Scout text is free text written by
// people: it only ever reaches the page through esc() or textContent.
import {api, esc, dash, rememberState, restoreState} from './common.js';

const $ = id => document.getElementById(id);
const FILTERS = ['q', 'league', 'max_age', 'foot', 'scout', 'verdict', 'grade', 'position', 'club', 'seen', 'data', 'dvs', 'role'];
const SELECTS = {league: 'League', foot: 'Foot', scout: 'Scout', verdict: 'Verdict', grade: 'Grade',
  position: 'Position', club: 'Club', seen: 'Seen', data: 'Our data', dvs: 'Data vs scout', role: 'Squad role'};
const TONE = {positive: 'verdict-pos', negative: 'verdict-neg', neutral: 'verdict-mid'};

let seq = 0, last = null, detailSeq = 0;

// ---- state <-> URL -----------------------------------------------------------------------
function state() {
  const q = new URLSearchParams(location.search), s = {};
  for (const k of [...FILTERS, 'tab', 'sort', 'dir', 'open']) s[k] = q.get(k) || '';
  return s;
}
function push(patch, {replace = false} = {}) {
  const q = new URLSearchParams(location.search);
  for (const [k, v] of Object.entries(patch)) {
    if (v == null || v === '' || v === 'All' || (k === 'max_age' && String(v) === '40') || (k === 'tab' && v === 'all')) q.delete(k);
    else q.set(k, String(v));
  }
  const url = location.pathname + (q.toString() ? '?' + q : '');
  if (url !== location.pathname + location.search) history[replace ? 'replaceState' : 'pushState']({}, '', url);
  remember();
}
const apiQuery = s => {
  const q = new URLSearchParams();
  for (const k of [...FILTERS, 'tab']) if (s[k]) q.set(k, s[k]);
  return q.toString() ? '?' + q : '';
};
const backQ = () => '?back=' + encodeURIComponent('/scout-reports' + location.search);

// ---- drawing -----------------------------------------------------------------------------
const chipFor = text => {
  const x = Number(text);
  if (text === '—' || !Number.isFinite(x)) return '<span class="chip c0">—</span>';
  return `<span class="chip ${x >= 4 ? 'c4' : x >= 3 ? 'c3' : x >= 2 ? 'c2' : 'c1'}">${esc(text)}</span>`;
};

function drawControls(d, s) {
  for (const [k, label] of Object.entries(SELECTS)) {
    const el = $('f-' + k), opts = d.options[label] || ['All'];
    const want = opts.includes(s[k]) ? s[k] : (s[k] && s[k] !== 'All' ? s[k] : 'All');
    const list = opts.includes(want) ? opts : [...opts, want];   // a shared value not in the list still shows
    el.innerHTML = list.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
    el.value = want;
  }
  if (document.activeElement !== $('f-q')) $('f-q').value = s.q;
  $('f-max_age').value = s.max_age || '40';
}

function drawTabs(d) {
  $('sr-tabs').innerHTML = d.tabs.map(t =>
    `<button type="button" role="tab" data-tab="${esc(t.key)}" aria-selected="${t.key === d.tab}" class="${t.key === d.tab ? 'on' : ''}">${esc(t.label)}</button>`).join('');
}

function sortRows(rows, s) {
  if (!s.sort) return rows;
  const dir = s.dir === 'desc' ? -1 : 1;
  const cmp = (a, b) => {
    const x = a.cells[s.sort] ?? '—', y = b.cells[s.sort] ?? '—';
    if (x === '—' && y === '—') return 0;
    if (x === '—') return 1;                     // blanks last either way
    if (y === '—') return -1;
    return dir * x.localeCompare(y, 'en', {numeric: true, sensitivity: 'base'});
  };
  return rows.map((r, i) => [r, i]).sort((p, q) => cmp(p[0], q[0]) || p[1] - q[1]).map(p => p[0]);
}

function drawTable(d, s) {
  const cols = d.columns;
  $('sr-thead').innerHTML = '<tr>' + cols.map(c => {
    const on = s.sort === c.key, arrow = on ? (s.dir === 'desc' ? ' ▼' : ' ▲') : '';
    const tip = c.help ? ` title="${esc(c.help)}"` : '';
    return `<th class="${on ? 'sorted' : ''}${/Rating/.test(c.key) || c.key === 'This season' ? ' c' : ''}"${tip}><button type="button" data-sort="${esc(c.key)}" aria-label="Sort by ${esc(c.label)}">${esc(c.label)}${arrow}</button></th>`;
  }).join('') + '</tr>';
  const rows = sortRows(d.rows, s);
  $('sr-body').innerHTML = rows.map(r => '<tr data-row="' + esc(r.id) + '" class="click' + (r.id === s.open ? ' me' : '') + '">' + cols.map(c => {
    const v = dash(r.cells[c.key]);
    if (c.key === 'Player') {
      const name = `<span class="pname">${esc(v)}</span>`;
      return `<td class="cut pcell">${r.href ? `<a href="${esc(r.href + backQ())}" class="plink">${name}</a>` : name}</td>`;
    }
    if (c.key === 'Verdict') return `<td>${v === '—' ? '—' : `<span class="pill ${TONE[r.tone] || 'verdict-mid'}">${esc(v)}</span>`}</td>`;
    if (c.key === 'Rating' || c.key === 'This season') return `<td class="c">${chipFor(v)}</td>`;
    if (c.key === 'Club' || c.key === 'Fixture') return `<td class="cut" title="${esc(v)}">${esc(v)}</td>`;
    if (c.key === 'Data vs scout') return `<td class="dvs">${esc(v)}</td>`;
    return `<td>${esc(v)}</td>`;
  }).join('') + '</tr>').join('');
  $('sr-none').hidden = d.rows.length > 0;
  $('sr-tw').hidden = d.rows.length === 0;
}

function drawActivity(d) {
  const a = d.activity;
  $('sr-thead').innerHTML = '<tr>' + a.columns.map((c, i) => `<th class="${i ? 'n' : ''}">${esc(c)}</th>`).join('') + '</tr>';
  $('sr-body').innerHTML = a.rows.map(r => '<tr>' + r.map((v, i) => `<td class="${i ? 'n' : ''}">${esc(dash(v))}</td>`).join('') + '</tr>').join('');
  $('sr-none').hidden = true;
  $('sr-tw').hidden = false;
}

function drawSync(sync) {
  const el = $('sr-sync');
  el.textContent = sync.line;
  el.className = sync.warn ? 'warn sr-warn' : 'meta';
}

function draw(d, s) {
  last = d;
  drawSync(d.sync);
  if (d.empty) {
    $('sr-empty').hidden = false; $('sr-empty').textContent = d.text; $('sr-main').hidden = true;
    return;
  }
  $('sr-empty').hidden = true; $('sr-main').hidden = false;
  drawTabs(d);
  $('sr-filters').hidden = d.tab !== 'all';
  drawControls(d, s);
  $('sr-cap').textContent = d.caption || '';
  $('sr-cap').hidden = !d.caption;
  if (d.tab === 'activity') drawActivity(d); else drawTable(d, s);
  loadDetail(d.tab === 'activity' ? '' : s.open, d);
}

// ---- detail ------------------------------------------------------------------------------
async function loadDetail(id, d, {scroll = false} = {}) {
  const box = $('sr-detail'), mine = ++detailSeq;
  if (!id || !(d.rows || []).some(r => r.id === id)) { box.innerHTML = ''; return; }
  try {
    const r = await api('/api/scout-reports/report/' + encodeURIComponent(id));
    if (mine !== detailSeq) return;
    const c = r.card;
    const facts = c.facts.map(([k, v]) => `<div>${esc(k)}<b>${esc(v)}</b></div>`).join('');
    box.innerHTML = `<div class="card sr-report" style="border-left-color:${esc(c.accent)}">
      <div class="sr-rhead"><div><span class="sr-rname"></span> <span class="pclub sr-rclub"></span></div>
        <button type="button" class="btn small" data-action="close-report" aria-label="Close report">✕ Close</button></div>
      <div class="meta sr-rmeta"><span class="sr-rmeta-t"></span> <span class="pill ${TONE[c.tone] || 'verdict-mid'} sr-pill"></span></div>
      ${facts ? `<div class="reg sr-facts">${facts}</div>` : ''}
      <div class="sr-body"></div>
      <div class="sr-below"></div></div>`;
    box.querySelector('.sr-rname').textContent = dash(c.player);
    box.querySelector('.sr-rclub').textContent = c.club || '';
    box.querySelector('.sr-rmeta-t').textContent = c.meta;
    box.querySelector('.sr-pill').textContent = dash(c.verdict);
    const body = box.querySelector('.sr-body');
    if (c.body) body.textContent = c.body; else { body.textContent = 'No written report.'; body.classList.add('sr-empty'); }
    const below = box.querySelector('.sr-below');
    if (r.open) below.innerHTML = `<a class="btn primary" href="${esc(r.open.href + backQ())}">${esc(r.open.label)}</a>`;
    else below.innerHTML = `<p class="note">${esc(r.caption)}</p>`;
    if (scroll) box.scrollIntoView({block: 'nearest'});
  } catch (e) {
    if (mine === detailSeq) box.innerHTML = `<div class="warn">Could not load the report (${esc(e.message)}).</div>`;
  }
}

// ---- loading -----------------------------------------------------------------------------
async function load() {
  const s = state(), mine = ++seq;
  try {
    const d = await api('/api/scout-reports' + apiQuery(s));
    if (mine === seq) { draw(d, s); remember(); }
  } catch (e) {
    if (mine === seq) { $('sr-sync').textContent = `Could not load the reports (${e.message}).`; }
  }
}

// owner 2026-11-13: the nav link (a bare URL) reopens the last filters and sort; the open row
// is a one-off and is not kept
const remember = () => rememberState('scout-reports', {drop: ['open']});

function init() {
  restoreState('scout-reports');
  for (const k of Object.keys(SELECTS)) $('f-' + k).onchange = ev => { push({[k]: ev.target.value, open: ''}); load(); };
  let t = null;
  $('f-q').oninput = ev => {
    clearTimeout(t);
    t = setTimeout(() => { push({q: ev.target.value.trim(), open: ''}, {replace: true}); load(); }, 200);
  };
  $('f-q').onkeydown = ev => { if (ev.key === 'Enter') { clearTimeout(t); push({q: ev.target.value.trim(), open: ''}, {replace: true}); load(); } };
  $('f-max_age').onchange = ev => {
    const n = Number(ev.target.value);
    if (!Number.isInteger(n) || n < 16 || n > 40) { ev.target.value = state().max_age || '40'; return; }
    push({max_age: n, open: ''}); load();
  };
  $('sr-tabs').onclick = ev => {
    const b = ev.target.closest('[data-tab]');
    if (!b) return;
    push({tab: b.dataset.tab, open: ''}); load();
  };
  $('sr-thead').onclick = ev => {
    const b = ev.target.closest('[data-sort]');
    if (!b || !last) return;
    const s = state(), k = b.dataset.sort;
    const next = s.sort !== k ? {sort: k, dir: ''} : s.dir !== 'desc' ? {sort: k, dir: 'desc'} : {sort: '', dir: ''};
    push(next);
    drawTable(last, state());
  };
  $('sr-body').onclick = ev => {
    if (ev.target.closest('a')) return;                     // the name opens the card
    const tr = ev.target.closest('tr[data-row]');
    if (!tr || !last) return;
    push({open: tr.dataset.row});
    document.querySelectorAll('#sr-body tr.me').forEach(x => x.classList.remove('me'));
    tr.classList.add('me');
    loadDetail(tr.dataset.row, last, {scroll: true});
  };
  $('sr-detail').onclick = ev => {
    if (!ev.target.closest('[data-action=close-report]')) return;
    push({open: ''});
    document.querySelectorAll('#sr-body tr.me').forEach(x => x.classList.remove('me'));
    $('sr-detail').innerHTML = '';
  };
  $('sr-refresh').onclick = async () => {
    const b = $('sr-refresh'), msg = $('sr-sync-msg');
    b.disabled = true; msg.textContent = 'Reading the scouting sheet…';
    try {
      const r = await api('/api/scout-reports/sync', {json: {}});
      if (r.ok) { msg.textContent = ''; await load(); drawSync(r.sync); }
      else msg.textContent = r.error;
    } catch (e) {
      msg.textContent = `Could not read the scouting sheet (${e.message}).`;
    } finally { b.disabled = false; }
  };
  window.addEventListener('popstate', load);
  load();
}
init();
