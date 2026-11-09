// Physical page. Fetches /api/physical (one answer per season, league and position) and draws
// it. It computes no number: values, their text, percentiles, ranks and the leaders' order all
// come from the API (lofc.core.physical_page over the ratings' own frames). The metric, the
// scatter axes, "Show all" and the squad sort only redraw that answer. The URL query string is
// the whole page state: shareable, and back/forward restore it.
import {api, esc, dash, pcol, bar, chip} from './common.js';

const $ = id => document.getElementById(id);
const DASH = '—';
const KEYS = ['season', 'league', 'position', 'age', 'metric', 'x', 'y', 'sort', 'dir', 'all'];

let P = null;          // last answer
let st = {};           // state (mirrors the URL)
let seq = 0;           // newest request; older answers are ignored
let apiKey = null;     // the season/league/position of P

// ---- state <-> URL -----------------------------------------------------------------------
function fromUrl() {
  const q = new URLSearchParams(location.search), s = {};
  for (const k of KEYS) s[k] = q.get(k) || '';
  return s;
}
function toQuery(s) {
  const q = new URLSearchParams();
  for (const k of KEYS) if (s[k]) q.set(k, s[k]);
  const t = q.toString();
  return t ? '?' + t : '';
}
function commit(patch) {
  Object.assign(st, patch);
  const qs = toQuery(st);
  if (qs !== location.search) history.pushState({}, '', location.pathname + qs);
  return render();
}
const backQ = () => '?back=' + encodeURIComponent('/physical' + location.search);
const keyOf = s => `${s.season}|${s.league}|${s.position}|${s.x}|${s.y}|${s.age}`;

// ---- helpers -----------------------------------------------------------------------------
const opt = (v, label, on) => `<option value="${esc(v)}"${on ? ' selected' : ''}>${esc(label)}</option>`;
const metricBy = () => Object.fromEntries(P.metrics.map(m => [m.key, m]));
const valid = (k, fallback) => (k && metricBy()[k]) ? k : fallback;
const pctPill = p => p == null ? ''
  : `<span class="ph-pp" style="background:${pcol(p)};color:${p >= 30 && p < 70 ? 'var(--ink)' : '#fff'}" data-tip="Percentile ${p}">${p}</span>`;
const ratingCell = r => chip(r.phys) + (r.phys == null || !r.phys_t || r.phys_t === DASH ? '' : `<div class="ph-rk">${esc(r.phys_t)}</div>`);
const MT = 'Tracked matches', MT_HELP = 'Matches SkillCorner tracked for him in this league and season.';
const inAge = r => !st.age || (r.bands || []).includes(st.age);
const nameCell = (r, sub) => {
  const n = `<span class="pname">${esc(dash(r.name))}</span>`;
  const link = r.href ? `<a class="plink" href="${esc(r.href + backQ())}">${n}</a>` : n;
  return `<td class="pcell">${link}${sub ? `<div class="pclub">${esc(sub)}</div>` : ''}</td>`;
};

function metricOptions(cur, withRating = false) {
  const group = (label, list) => `<optgroup label="${esc(label)}">` +
    list.map(m => opt(m.key, m.label, m.key === cur)).join('') + '</optgroup>';
  return (withRating ? opt(P.rating.key, P.rating.label, cur === P.rating.key) : '') +
         group('In the rating', P.metrics.filter(m => m.rated)) +
         group('Other', P.metrics.filter(m => !m.rated));
}

// ---- filters -----------------------------------------------------------------------------
function drawFilters() {
  const f = P.filters;
  $('f-season').innerHTML = f.seasons.map(s => opt(s.id, s.name, s.id === f.season)).join('');
  const has = !P.empty;
  $('w-league').hidden = !has; $('w-position').hidden = !has;
  if (has) {
    $('f-league').innerHTML = f.leagues.map(l => opt(l.id, l.name, l.id === f.league)).join('');
    $('f-position').innerHTML = f.positions.map(p => opt(p, p, p === f.position)).join('');
  }
  $('w-age').hidden = !has;
  $('f-age').innerHTML = P.age_bands.map(b => opt(b.key, b.label, b.key === f.age)).join('');
}

// ---- leaders -----------------------------------------------------------------------------
function drawLeaders() {
  const pool = P.pool;
  const metric = st.metric === P.rating.key ? P.rating.key : valid(st.metric, P.defaults.metric);
  const isRating = metric === P.rating.key, m = isRating ? P.rating : metricBy()[metric];
  $('f-metric').innerHTML = metricOptions(metric, true);
  $('ld-sub').textContent = `${pool.title} · ${pool.sub}`;
  $('ld-def').textContent = m.definition;
  const L = pool.leaders[metric], rows = pool.players;
  const order = L.order.filter(([i]) => inAge(rows[i]));
  const thin = L.thin || (rows.length ? (order.length ? null : 'No players in this age group.') : pool.none);
  $('ld-thin').hidden = !thin; $('ld-thin').textContent = thin || '';
  const ranked = !L.thin && order.length > 0;
  const val = r => isRating ? chip(r.phys) : esc(r.t[metric]);
  // top three, large
  $('ld-tiles').hidden = !ranked;
  $('ld-tiles').innerHTML = ranked ? order.slice(0, 3).map(([i, rank]) => {
    const r = rows[i];
    const sub = isRating ? `${esc(dash(r.club))} · ${esc(r.phys_t)}` : `${esc(dash(r.club))} · P${r.p[metric] ?? DASH}`;
    return `<div class="tile${r.orient ? ' orient' : ''}"><div class="k">${rank} · ${esc(r.name)}</div>` +
      `<div class="v">${val(r)}</div><div class="x">${sub}</div></div>`;
  }).join('') : '';
  const all = st.all === '1', shown = all ? order : order.slice(0, P.leaders_shown);
  const inTop = new Set(shown.map(([i]) => i));
  const ours = all ? [] : order.filter(([i]) => rows[i].orient && !inTop.has(i));
  const cols = [...(ranked ? ['#'] : []), 'Player', 'Age', 'Minutes', MT, m.label,
    ...(ranked && !isRating ? ['Percentile'] : []), ...(isRating ? [] : [P.rating.label])];
  const cls = c => c === '#' || c === 'Age' || c === 'Minutes' || c === MT || (c === m.label && !isRating) ? 'n'
    : c === 'Percentile' ? 'ph-pcol' : (c === P.rating.label) ? 'c' : '';
  $('ld-head').innerHTML = '<tr>' + cols.map(c => `<th class="${cls(c)}"${c === MT ? ` title="${esc(MT_HELP)}"` : ''}>${esc(c)}</th>`).join('') + '</tr>';
  const line = ([i, rank]) => {
    const r = rows[i];
    return `<tr class="${r.orient ? 'me' : ''}">` + (ranked ? `<td class="n">${rank ?? DASH}</td>` : '') +
      nameCell(r, r.club) + `<td class="n">${esc(r.age)}</td><td class="n">${esc(r.mins_t)}</td><td class="n">${r.matches ?? DASH}</td>` +
      (isRating ? `<td class="c">${ratingCell(r)}</td>`
        : `<td class="n ph-val">${esc(r.t[metric])}</td>` + (ranked ? `<td class="ph-pcol">${bar(r.p[metric])}</td>` : '')
          + `<td class="c">${ratingCell(r)}</td>`) + '</tr>';
  };
  $('ld-body').innerHTML = shown.map(line).join('') +
    (ours.length ? `<tr class="sec"><td colspan="${cols.length}">Leyton Orient</td></tr>` + ours.map(line).join('') : '');
  const more = $('ld-more');
  more.hidden = order.length <= P.leaders_shown;
  more.textContent = all ? `Show top ${P.leaders_shown}` : `Show all ${order.length}`;
  more.setAttribute('aria-label', all ? 'Show the top players only' : 'Show all players');
}

// ---- scatter (plain SVG, drawn at the box's own size) --------------------------------------
let findText = '';
const lastName = n => { const w = String(n).trim().split(/\s+/); return w.length > 1 ? w.slice(1).join(' ') : w[0]; };

function drawScatter() {
  const pool = P.pool, by = metricBy(), S = P.scatter;
  const x = S.x, y = S.y;
  $('f-x').innerHTML = metricOptions(x); $('f-y').innerHTML = metricOptions(y);
  $('sc-sub').textContent = pool.title + ' · ' + pool.sub;
  const box = $('sc-plot');
  const pts = S.idx.map(i => pool.players[i]);
  if (pts.length < 3) {
    box.innerHTML = `<p class="note">${esc(pool.none || (st.age ? 'Too few players in this age group with both metrics.' : 'Too few players with both metrics.'))}</p>`;
    return;
  }
  // Plot geometry only (pixel positions); every label and the medians are the API's.
  const W = Math.max(320, Math.floor(box.clientWidth)), H = Math.max(360, Math.floor(box.clientHeight));
  box.dataset.size = `${W}x${H}`;
  const l = 58, r = 18, t = 16, b = 48;
  const vals = k => pts.map(p => p.v[k]);
  const lo = k => Math.min(...vals(k)), hi = k => Math.max(...vals(k));
  const pad = (a, c) => { const d = (c - a) || 1; return [a - d * 0.04, c + d * 0.04]; };
  const [x0, x1] = pad(lo(x), hi(x)), [y0, y1] = pad(lo(y), hi(y));
  const sx = v => l + (v - x0) / (x1 - x0) * (W - l - r);
  const sy = v => H - b - (v - y0) / (y1 - y0) * (H - t - b);
  const lowX = pts.reduce((a, p) => p.v[x] < a.v[x] ? p : a), highX = pts.reduce((a, p) => p.v[x] > a.v[x] ? p : a);
  const lowY = pts.reduce((a, p) => p.v[y] < a.v[y] ? p : a), highY = pts.reduce((a, p) => p.v[y] > a.v[y] ? p : a);
  let g = `<rect x="${l}" y="${t}" width="${W - l - r}" height="${H - t - b}" fill="#FAFAFB" stroke="var(--line)"/>`;
  g += `<text x="${sx(lowX.v[x])}" y="${H - b + 16}" class="ax" text-anchor="start">${esc(lowX.t[x])}</text>`;
  g += `<text x="${sx(highX.v[x])}" y="${H - b + 16}" class="ax" text-anchor="end">${esc(highX.t[x])}</text>`;
  g += `<text x="${l - 6}" y="${sy(lowY.v[y])}" class="ax" text-anchor="end" dominant-baseline="middle">${esc(lowY.t[y])}</text>`;
  g += `<text x="${l - 6}" y="${sy(highY.v[y])}" class="ax" text-anchor="end" dominant-baseline="middle">${esc(highY.t[y])}</text>`;
  g += `<text x="${(l + W - r) / 2}" y="${H - 10}" class="axl" text-anchor="middle">${esc(by[x].label)}</text>`;
  g += `<text transform="translate(16 ${(t + H - b) / 2}) rotate(-90)" class="axl" text-anchor="middle">${esc(by[y].label)}</text>`;
  // medians of the plotted pool (from the API)
  const M = S.median;
  if (M.x != null) g += `<line x1="${sx(M.x)}" y1="${t}" x2="${sx(M.x)}" y2="${H - b}" class="med"/><text x="${sx(M.x) + 4}" y="${t + 12}" class="medt">median ${esc(M.x_t)}</text>`;
  if (M.y != null) g += `<line x1="${l}" y1="${sy(M.y)}" x2="${W - r}" y2="${sy(M.y)}" class="med"/><text x="${W - r - 4}" y="${sy(M.y) - 5}" class="medt" text-anchor="end">median ${esc(M.y_t)}</text>`;
  const q = findText.trim().toLowerCase();
  const found = new Set(q ? S.idx.filter(i => pool.players[i].name.toLowerCase().includes(q)) : []);
  const top = new Set(S.top);
  const tipOf = p => `${p.name}\n${dash(p.club)} · ${p.mins_t} min\n${by[x].label}: ${p.t[x]}${p.p[x] == null ? '' : ' · P' + p.p[x]}\n${by[y].label}: ${p.t[y]}${p.p[y] == null ? '' : ' · P' + p.p[y]}`;
  const dot = i => {
    const p = pool.players[i], f = found.has(i);
    const cls = 'pt' + (p.orient ? ' orient' : '') + (f ? ' found' : '') + (q && !f ? ' dim' : '');
    const c = `<circle cx="${sx(p.v[x]).toFixed(1)}" cy="${sy(p.v[y]).toFixed(1)}" r="${f ? 8 : p.orient ? 6.5 : 5}" class="${cls}" data-tip="${esc(tipOf(p))}"/>`;
    return p.href ? `<a href="${esc(p.href + backQ())}" aria-label="${esc(p.name)}">${c}</a>` : c;
  };
  const order = [...S.idx.filter(i => !pool.players[i].orient && !found.has(i)),
                 ...S.idx.filter(i => pool.players[i].orient && !found.has(i)), ...found];
  g += order.map(dot).join('');
  // names: found players, Orient's, the top five by combined percentile; never on top of another
  const placed = [];
  // the median labels are drawn first: a name never sits on them
  if (M.x != null) placed.push({x1: sx(M.x) + 2, y1: t, x2: sx(M.x) + 8 + 6.2 * (7 + M.x_t.length), y2: t + 15});
  if (M.y != null) placed.push({x1: W - r - 6 - 6.2 * (7 + M.y_t.length), y1: sy(M.y) - 17, x2: W - r, y2: sy(M.y) - 1});
  const hit = (a, c) => a.x1 < c.x2 + 2 && c.x1 < a.x2 + 2 && a.y1 < c.y2 + 1 && c.y1 < a.y2 + 1;
  let labels = '';
  const named = [...found, ...S.idx.filter(i => pool.players[i].orient && !found.has(i)),
                 ...S.top.filter(i => !found.has(i) && !pool.players[i].orient)];
  for (const i of named) {
    const p = pool.players[i], cx = sx(p.v[x]), cy = sy(p.v[y]);
    const name = found.has(i) ? p.name : lastName(p.name), w = name.length * 6.6 + 4, h = 14;
    const tries = [[cx - w / 2, cy - 11 - h], [cx - w / 2, cy + 9], [cx + 9, cy - h / 2], [cx - 9 - w, cy - h / 2]];
    const spot = tries.map(([a, c]) => ({x1: a, y1: c, x2: a + w, y2: c + h}))
      .find(bx => bx.x1 >= l && bx.x2 <= W - r && bx.y1 >= t && bx.y2 <= H - b && !placed.some(o => hit(o, bx)));
    if (!spot) continue;
    placed.push(spot);
    const kind = found.has(i) ? 'found' : p.orient ? 'orient' : 'top';
    labels += `<text x="${spot.x1 + 2}" y="${spot.y1 + 11}" class="ptl ${kind}">${esc(name)}</text>`;
  }
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(by[x].label)} against ${esc(by[y].label)}">${g}${labels}</svg>`;
}
new ResizeObserver(() => {
  const box = $('sc-plot');
  if (P && P.scatter && box.dataset.size !== `${Math.max(320, Math.floor(box.clientWidth))}x${Math.max(360, Math.floor(box.clientHeight))}`) drawScatter();
}).observe($('sc-plot'));

// ---- squad -------------------------------------------------------------------------------
function squadSorted(rows) {
  if (!st.sort) return rows;
  const desc = st.dir !== 'asc';
  const val = r => st.sort === 'mins' ? r.mins : st.sort === 'matches' ? r.matches : st.sort === 'phys' ? r.phys
    : st.sort === 'name' ? null : (r.cells[st.sort] || {}).v;
  if (st.sort === 'name') return [...rows].sort((a, b) => (desc ? -1 : 1) * a.name.localeCompare(b.name));
  return rows.map((r, i) => [r, i]).sort((a, b) => {
    const x = val(a[0]), y = val(b[0]);
    if (x == null && y == null) return a[1] - b[1];
    if (x == null) return 1;
    if (y == null) return -1;
    return (desc ? y - x : x - y) || a[1] - b[1];
  }).map(p => p[0]);
}

function drawSquad() {
  const S = P.squad, by = metricBy();
  $('sq-sub').textContent = S.sub;
  const head = [['name', 'Player', ''], ['mins', 'Minutes', 'n'], ['matches', MT, 'n'], ['phys', 'Physical', 'c'],
    ...S.columns.map(k => [k, by[k].label, 'n'])];
  $('sq-head').innerHTML = '<tr>' + head.map(([k, label, cls]) => {
    const on = st.sort === k, arrow = on ? (st.dir === 'asc' ? ' ▲' : ' ▼') : '';
    return `<th class="${cls}${on ? ' sorted' : ''}"${k === 'matches' ? ` title="${esc(MT_HELP)}"` : ''}><button type="button" data-sort="${esc(k)}" aria-label="Sort by ${esc(label)}">${esc(label)}${arrow}</button></th>`;
  }).join('') + '</tr>';
  $('sq-body').innerHTML = squadSorted(S.rows).map(r => {
    const sub = [r.pos, r.league].filter(Boolean).join(' · ');
    const name = nameCell(r, sub).replace('</td>', r.note ? `<div class="note">${esc(r.note)}</div></td>` : '</td>');
    const phys = ratingCell(r);
    return `<tr>${name}<td class="n">${esc(r.mins_t)}</td><td class="n">${r.matches ?? DASH}</td><td class="c">${phys}</td>` +
      S.columns.map(k => { const c = r.cells[k]; return `<td class="n ph-cell"><span class="ph-v">${esc(c.t)}</span>${pctPill(c.p)}</td>`; }).join('') + '</tr>';
  }).join('');
}

// ---- load / draw -------------------------------------------------------------------------
function draw() {
  drawFilters();
  $('ph-empty').hidden = !P.empty;
  $('ph-empty').textContent = P.empty || '';
  $('ph-main').hidden = !!P.empty;
  if (P.empty) {   // no league/position/metric to show: empty the hidden selects too
    for (const id of ['f-league', 'f-position', 'f-metric', 'f-x', 'f-y']) $(id).innerHTML = '';
    $('w-age').hidden = true;
    return;
  }
  drawLeaders(); drawScatter(); drawSquad();
}

async function render() {
  if (P && keyOf(st) === apiKey) { draw(); return; }
  const my = ++seq, k = keyOf(st);
  const q = new URLSearchParams();
  for (const n of ['season', 'league', 'position', 'x', 'y', 'age']) if (st[n]) q.set(n, st[n]);
  const d = await api('/api/physical' + (q.toString() ? '?' + q : ''));
  if (my !== seq) return;
  P = d; apiKey = k;
  draw();
}

// ---- events ------------------------------------------------------------------------------
$('f-season').addEventListener('change', e => commit({season: e.target.value, league: '', all: ''}));
$('f-league').addEventListener('change', e => commit({league: e.target.value, all: ''}));
$('f-position').addEventListener('change', e => commit({position: e.target.value, all: ''}));
$('f-metric').addEventListener('change', e => commit({metric: e.target.value}));
$('f-x').addEventListener('change', e => commit({x: e.target.value}));
$('f-y').addEventListener('change', e => commit({y: e.target.value}));
$('f-age').addEventListener('change', e => commit({age: e.target.value, all: ''}));
$('f-find').addEventListener('input', e => { findText = e.target.value; if (P && P.scatter) drawScatter(); });
$('ld-more').addEventListener('click', () => commit({all: st.all === '1' ? '' : '1'}));
$('sq-head').addEventListener('click', e => {
  const b = e.target.closest('button[data-sort]');
  if (!b) return;
  const k = b.dataset.sort;
  // first click: highest first (name: A-Z); second: the other way; third: back to the default order
  if (st.sort !== k) commit({sort: k, dir: k === 'name' ? 'asc' : 'desc'});
  else if (st.dir === (k === 'name' ? 'asc' : 'desc')) commit({dir: k === 'name' ? 'desc' : 'asc'});
  else commit({sort: '', dir: ''});
});
window.addEventListener('popstate', () => { st = fromUrl(); render(); });

st = fromUrl();
render();
