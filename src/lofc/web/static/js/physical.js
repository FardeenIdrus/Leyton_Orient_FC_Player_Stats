// Physical page. Fetches /api/physical (one answer per season, league and position) and draws
// it. It computes no number: values, their text, percentiles, ranks and the leaders' order all
// come from the API (lofc.core.physical_page over the ratings' own frames). The metric, the
// scatter axes, "Show all" and the squad sort only redraw that answer. The URL query string is
// the whole page state: shareable, and back/forward restore it.
import {api, esc, dash, pcol, bar, chip, pctNum, rememberState, restoreState} from './common.js';

const $ = id => document.getElementById(id);
const DASH = '—';
const KEYS = ['season', 'league', 'position', 'age', 'metric', 'x', 'y', 'min', 'sort', 'dir', 'all', 'view'];

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
const keyOf = s => `${s.season}|${s.league}|${s.position}|${s.x}|${s.y}|${s.age}|${s.min}`;

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
// The medians, the reversed axes (S.rev: lower is better, so top right is always better on both)
// and the "Better on both" list (S.top, best first; the first S.top_marked numbered in red) are
// the API's (core.physical_page.better_on_both); here only pixels and tick steps.
let findText = '';
const lastName = n => { const w = String(n).trim().split(/\s+/); return w.length > 1 ? w.slice(1).join(' ') : w[0]; };
// round tick steps (1, 2, 2.5, 5 x 10^k) inside [a, b]
function ticks(a, b, n = 5) {
  const raw = (b - a) / n || 1, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(v => v >= raw * 0.999);
  let dec = Math.max(0, Math.ceil(-Math.log10(step) - 1e-9));
  if (Math.abs(step * 10 ** dec - Math.round(step * 10 ** dec)) > 1e-6) dec += 1;
  const out = [], first = Math.ceil(a / step - 1e-9);
  for (let k = first; k * step <= b + 1e-9; k++) out.push([k * step, (k * step).toFixed(dec)]);
  return out;
}

// owner 2026-11-13: timing measures (lower is better, S.rev) show two decimals on this chart and
// its list, so 1.08 and 1.12 are not both "1.1"; every other value keeps the card's one decimal
const chartVal = (r, k, axis) => (P.scatter.rev || {})[axis] && r.v[k] != null ? r.v[k].toFixed(2) : r.t[k];

function drawTop(top) {
  const S = P.scatter, by = metricBy(), rows = P.pool.players, side = $('sc-side');
  const x = S.x, y = S.y;
  side.hidden = S.idx.length < 3;
  $('sc-top-head').innerHTML = `<tr><th class="n">#</th><th>Player</th><th class="n">${esc(by[x].label)}</th><th class="n">${esc(by[y].label)}</th></tr>`;
  $('sc-top-body').innerHTML = top.map((i, k) => {
    const r = rows[i], n = k + 1;
    return `<tr class="${r.orient ? 'me' : ''}" data-rank="${n}"><td class="n">${n <= S.top_marked ? `<span class="t5b">${n}</span>` : n}</td>` +
      nameCell(r, dash(r.club)) + `<td class="n">${esc(chartVal(r, x, 'x'))}</td><td class="n">${esc(chartVal(r, y, 'y'))}</td></tr>`;
  }).join('');
  $('sc-top').hidden = !top.length;
  $('sc-top-note').hidden = !S.top_note;
  $('sc-top-note').textContent = S.top_note || '';
}

function drawScatter() {
  const pool = P.pool, by = metricBy(), S = P.scatter;
  const x = S.x, y = S.y;
  $('f-x').innerHTML = metricOptions(x); $('f-y').innerHTML = metricOptions(y);
  const R = P.min_range, sl = $('f-min');
  Object.assign(sl, {min: R.min, max: R.max, step: R.step});
  sl.value = P.filters.min; minLabel();
  $('sc-sub').textContent = S.sub;
  const box = $('sc-plot');
  const pts = S.idx.map(i => pool.players[i]);
  const top = S.top.filter(i => S.idx.includes(i));
  drawTop(top);
  if (pts.length < 3) {
    const few = st.age ? 'Too few players in this age group with both metrics.'
      : P.filters.min > P.min_range.min ? `Too few players with both metrics and ${P.filters.min.toLocaleString('en-GB')}+ minutes.`
      : 'Too few players with both metrics.';
    box.innerHTML = `<p class="note">${esc(pool.none || few)}</p>`;
    return;
  }
  // Plot geometry only (pixel positions); every label and the medians are the API's.
  const W = Math.max(320, Math.floor(box.clientWidth)), H = Math.max(360, Math.floor(box.clientHeight));
  box.dataset.size = `${W}x${H}`;
  const vals = k => pts.map(p => p.v[k]);
  const lo = k => Math.min(...vals(k)), hi = k => Math.max(...vals(k));
  const pad = (a, c) => { const d = (c - a) || 1; return [a - d * 0.05, c + d * 0.05]; };
  const [x0, x1] = pad(lo(x), hi(x)), [y0, y1] = pad(lo(y), hi(y));
  const xt = ticks(x0, x1), yt = ticks(y0, y1);
  const CW = 6.3;                                    // ~ width of one 11px character
  const l = 34 + CW * Math.max(...yt.map(([, s]) => s.length)), r = 18, t = 16, b = 48;
  // a lower-is-better axis runs high -> low, so right and up always mean better
  const sx = v => l + (S.rev.x ? x1 - v : v - x0) / (x1 - x0) * (W - l - r);
  const sy = v => H - b - (S.rev.y ? y1 - v : v - y0) / (y1 - y0) * (H - t - b);
  const axTitle = (k, rev) => by[k].label + (rev ? ' (lower is better)' : '');
  const M = S.median;
  let g = `<rect x="${l}" y="${t}" width="${W - l - r}" height="${H - t - b}" class="frame"/>`;
  // "Better on both": the top-right quadrant, shaded
  if (M.x != null && M.y != null)
    g += `<rect x="${sx(M.x).toFixed(1)}" y="${t}" width="${(W - r - sx(M.x)).toFixed(1)}" height="${(sy(M.y) - t).toFixed(1)}" class="quad"/>`;
  // light grid with tick values
  for (const [v, txt] of xt) {
    const px = sx(v).toFixed(1);
    g += `<line x1="${px}" y1="${t}" x2="${px}" y2="${H - b}" class="grid"/><text x="${px}" y="${H - b + 15}" class="ax" text-anchor="middle">${txt}</text>`;
  }
  for (const [v, txt] of yt) {
    const py = sy(v).toFixed(1);
    g += `<line x1="${l}" y1="${py}" x2="${W - r}" y2="${py}" class="grid"/><text x="${l - 6}" y="${py}" class="ax" text-anchor="end" dominant-baseline="middle">${txt}</text>`;
  }
  g += `<text x="${(l + W - r) / 2}" y="${H - 10}" class="axl" text-anchor="middle">${esc(axTitle(x, S.rev.x))}</text>`;
  g += `<text transform="translate(16 ${(t + H - b) / 2}) rotate(-90)" class="axl" text-anchor="middle">${esc(axTitle(y, S.rev.y))}</text>`;
  if (M.x != null) g += `<line x1="${sx(M.x)}" y1="${t}" x2="${sx(M.x)}" y2="${H - b}" class="med"/>`;
  if (M.y != null) g += `<line x1="${l}" y1="${sy(M.y)}" x2="${W - r}" y2="${sy(M.y)}" class="med"/>`;

  // every word inside the frame goes through one placement: never on top of another
  const placed = [];
  const hit = (a, c) => a.x1 < c.x2 + 2 && c.x1 < a.x2 + 2 && a.y1 < c.y2 + 1 && c.y1 < a.y2 + 1;
  const inside = bx => bx.x1 >= l + 1 && bx.x2 <= W - r - 1 && bx.y1 >= t + 1 && bx.y2 <= H - b - 1;
  const place = (boxes, force) => {
    const ok = boxes.find(bx => inside(bx) && !placed.some(o => hit(o, bx))) || (force ? boxes.find(inside) : null);
    if (ok) placed.push(ok);
    return ok;
  };
  const at = (x1, y1, w, h) => ({x1, y1, x2: x1 + w, y2: y1 + h});
  let words = '';
  const word = (bx, cls, txt) => { words += `<text x="${(bx.x1 + 2).toFixed(1)}" y="${(bx.y1 + 11).toFixed(1)}" class="${cls}">${esc(txt)}</text>`; };
  // the corner labels first: they always show
  const qw = 'Better on both'.length * 6.6 + 4;
  word(place([at(W - r - 6 - qw, t + 4, qw, 14)], true), 'ql', 'Better on both');
  word(place([at(l + 4, H - b - 18, 'Worse on both'.length * 6.6 + 4, 14)], true), 'ql', 'Worse on both');
  // the numbered five: on the dot; where two would touch, the number moves beside its dot on a short line
  const q = findText.trim().toLowerCase();
  const found = new Set(q ? S.idx.filter(i => pool.players[i].name.toLowerCase().includes(q)) : []);
  const rank = new Map(top.slice(0, S.top_marked).map((i, k) => [i, k + 1]));
  const badge = new Map();
  for (const [i, k] of rank) {
    const p = pool.players[i], cx = sx(p.v[x]), cy = sy(p.v[y]), R = 10;
    const ring = [[0, 0], ...[0, 1, 2, 3, 4, 5, 6, 7].map(n => [Math.cos(n * Math.PI / 4 - Math.PI / 4) * 24, Math.sin(n * Math.PI / 4 - Math.PI / 4) * 24]),
                  ...[0, 1, 2, 3, 4, 5, 6, 7].map(n => [Math.cos(n * Math.PI / 4) * 40, Math.sin(n * Math.PI / 4) * 40])];
    const bx = place(ring.map(([dx, dy]) => at(cx + dx - R, cy + dy - R, 2 * R, 2 * R)), true);
    badge.set(i, {cx, cy, bx: bx.x1 + R, by: bx.y1 + R});
  }
  // median values, where they fit
  if (M.x != null) { const w = (7 + M.x_t.length) * CW + 4, mx = sx(M.x);
    const bx = place([at(mx + 4, H - b - 34, w, 14), at(mx - 4 - w, H - b - 18, w, 14), at(mx - 4 - w, t + 4, w, 14), at(mx + 4, t + 22, w, 14)]);
    if (bx) word(bx, 'medt', `median ${M.x_t}`); }
  if (M.y != null) { const w = (7 + M.y_t.length) * CW + 4, my = sy(M.y);
    const bx = place([at(l + 4, my - 17, w, 14), at(l + 4, my + 3, w, 14), at(W - r - 4 - w, my + 3, w, 14)]);
    if (bx) word(bx, 'medt', `median ${M.y_t}`); }

  const tipOf = p => `${p.name}\n${dash(p.club)} · ${p.mins_t} min\n${by[x].label}: ${chartVal(p, x, 'x')}${p.p[x] == null ? '' : ' · P' + p.p[x]}\n${by[y].label}: ${chartVal(p, y, 'y')}${p.p[y] == null ? '' : ' · P' + p.p[y]}`;
  const dot = i => {
    const p = pool.players[i], f = found.has(i), k = rank.get(i);
    const cx = sx(p.v[x]).toFixed(1), cy = sy(p.v[y]).toFixed(1);
    const dim = q && !f ? ' dim' : '';
    const ring = f ? `<circle cx="${cx}" cy="${cy}" r="${k ? 15 : 11}" class="ring"/>` : '';
    let c;
    if (k) {
      const B = badge.get(i), moved = Math.hypot(B.bx - B.cx, B.by - B.cy) > 1;
      c = `<g class="t5${dim}" data-rank="${k}" data-tip="${esc(tipOf(p))}">${ring}` +
        (moved ? `<line x1="${cx}" y1="${cy}" x2="${B.bx.toFixed(1)}" y2="${B.by.toFixed(1)}" class="t5l"/><circle cx="${cx}" cy="${cy}" r="4" class="pt t5 t5s"/>` : '') +
        `<circle cx="${B.bx.toFixed(1)}" cy="${B.by.toFixed(1)}" r="10" class="pt t5${f ? ' found' : ''}"/>` +
        `<text x="${B.bx.toFixed(1)}" y="${(B.by + 4).toFixed(1)}" class="t5n" text-anchor="middle">${k}</text></g>`;
    } else {
      c = `${ring}<circle cx="${cx}" cy="${cy}" r="${p.orient ? 6.5 : 5}" class="pt${p.orient ? ' orient' : ''}${f ? ' found' : ''}${dim}" data-tip="${esc(tipOf(p))}"/>`;
    }
    return p.href ? `<a href="${esc(p.href + backQ())}" aria-label="${esc(p.name)}">${c}</a>` : c;
  };
  // drawing order: others, Orient, the numbered five (1 on top), then the found player
  const tier = i => found.has(i) ? 3 : rank.has(i) ? 2 : pool.players[i].orient ? 1 : 0;
  g += [...S.idx].sort((a, c) => tier(a) - tier(c) || (rank.get(c) || 0) - (rank.get(a) || 0)).map(dot).join('');
  // names: a found player (in full; always, when he is the only one) and Orient's (surname)
  const named = [...found, ...S.idx.filter(i => pool.players[i].orient && !found.has(i))];
  for (const i of named) {
    const p = pool.players[i], B = badge.get(i), cx = B ? B.bx : sx(p.v[x]), cy = B ? B.by : sy(p.v[y]), o = B ? 12 : 9;
    const name = found.has(i) ? p.name : lastName(p.name), w = name.length * (found.has(i) ? 7.8 : 6.8) + 6, h = 15;
    const bx = place([at(cx + o, cy - h / 2, w, h), at(cx - w / 2, cy - o - 2 - h, w, h), at(cx - w / 2, cy + o, w, h), at(cx - o - w, cy - h / 2, w, h)],
                     found.has(i) && found.size === 1);
    if (bx) word(bx, 'ptl ' + (found.has(i) ? 'found' : 'orient'), name);
  }
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(by[x].label)} against ${esc(by[y].label)}">${g}${words}</svg>`;
}
new ResizeObserver(() => {
  const box = $('sc-plot');
  if (P && P.scatter && box.dataset.size !== `${Math.max(320, Math.floor(box.clientWidth))}x${Math.max(360, Math.floor(box.clientHeight))}`) drawScatter();
}).observe($('sc-plot'));

function minLabel() { $('min-out').textContent = `${Number($('f-min').value).toLocaleString('en-GB')}+ min`; }

// ---- Find a player: the plotted players, A-Z (owner 2026-11-13) ----------------------------
// The empty box lists every player on the chart (name · club); typing narrows the list; a pick
// puts his full name in the box, which highlights him exactly as typing it does.
function findList(force = false) {
  const box = $('f-find'), out = $('find-results');
  if (!force && document.activeElement !== box) { out.hidden = true; return; }
  const S = P && !P.empty && P.scatter, rows = P && P.pool ? P.pool.players : [];
  const q = box.value.trim().toLowerCase();
  const items = (S ? S.idx : []).map(i => rows[i])
    .filter(r => !q || r.name.toLowerCase().includes(q))
    .sort((a, b) => a.name.localeCompare(b.name));
  out._items = items;
  out.innerHTML = items.length
    ? items.map((r, i) => `<button type="button" data-i="${i}">${esc(r.name)}<span class="cl"> · ${esc(dash(r.club))}</span></button>`).join('')
    : '<div class="none">No player found.</div>';
  out.hidden = false;
}
function pickFind(r) {
  const box = $('f-find');
  box.value = r.name; findText = r.name;
  $('find-results').hidden = true;
  if (P && P.scatter) drawScatter();
}
function bindFind() {
  const box = $('f-find'), out = $('find-results');
  box.addEventListener('focus', () => findList(true));
  box.addEventListener('click', () => { if (out.hidden) findList(true); });
  box.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); if (!out.hidden && out._items && out._items.length) pickFind(out._items[0]); }
    else if (e.key === 'Escape') out.hidden = true;
  });
  out.addEventListener('mousedown', e => e.preventDefault());     // keep focus until the click
  box.addEventListener('blur', () => { out.hidden = true; });
  out.addEventListener('click', e => {
    const b = e.target.closest('button[data-i]');
    if (b) pickFind(out._items[Number(b.dataset.i)]);
  });
  document.addEventListener('click', e => { if (!e.target.closest('.ph-findbox')) out.hidden = true; });
}

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

// the "Physical | Performance" switch (owner 2026-11-13); Physical is the default
const perfView = () => st.view === 'perf';

function drawPerf() {
  const V = P.perf;
  $('sq-sub').textContent = V.sub;
  const list = xs => xs.length ? xs.map(x => `<div class="sp-ml"><span>${esc(x.label)}</span>${pctNum(x.pct)}</div>`).join('') : `<span class="note">${DASH}</span>`;
  const tag = (t, tip) => t ? `<span class="sp-tag"${tip ? ` data-tip="${esc(tip)}"` : ''}>${esc(t)}</span>` : '';
  $('sp-body').innerHTML = V.groups.map(g => `<tr class="sp-sec"><td colspan="7">${esc(g.group)}</td></tr>` + g.rows.map(r =>
    `<tr><td class="pcell"><a class="plink" href="${esc(r.href + backQ())}"><span class="pname">${esc(r.name)}</span></a>${tag(r.pos_tag)}${tag(r.league, r.league_tip)}</td>` +
    `<td class="n">${esc(r.mins_t)}</td><td class="c">${chip(r.overall)}</td><td class="c">${chip(r.perf)}</td><td class="c">${chip(r.phys)}</td>` +
    `<td class="sp-list">${list(r.strong)}</td><td class="sp-list">${list(r.weak)}</td></tr>`).join('')).join('');
  $('sp-unrated').hidden = !V.unrated_t;
  $('sp-unrated').textContent = V.unrated_t || '';
}

function drawSquad() {
  const on = perfView();
  $('sq-view').querySelectorAll('button').forEach(b => {
    const me = (b.dataset.view === 'perf') === on;
    b.classList.toggle('on', me); b.setAttribute('aria-pressed', String(me));
  });
  $('sq-tw').hidden = on; $('sq-perf').hidden = !on;
  if (on) { drawPerf(); return; }
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
  rememberState('physical');    // owner 2026-11-13: the nav link reopens these settings
  drawFilters();
  $('ph-empty').hidden = !P.empty;
  $('ph-empty').textContent = P.empty || '';
  $('ph-main').hidden = !!P.empty;
  if (P.empty) {   // no league/position/metric to show: empty the hidden selects too
    for (const id of ['f-league', 'f-position', 'f-metric', 'f-x', 'f-y', 'f-min']) $(id).innerHTML = '';
    $('w-age').hidden = true;
    return;
  }
  drawLeaders(); drawScatter(); drawSquad();
  $('sq-xlsx').href = '/api/physical/squad.xlsx?season=' + encodeURIComponent(P.filters.season);
}

async function render() {
  if (P && keyOf(st) === apiKey) { draw(); return; }
  const my = ++seq, k = keyOf(st);
  const q = new URLSearchParams();
  for (const n of ['season', 'league', 'position', 'x', 'y', 'age', 'min']) if (st[n]) q.set(n, st[n]);
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
// owner 2026-11-13: the label follows the handle; the chart redraws when it is released
$('f-min').addEventListener('input', minLabel);
$('f-min').addEventListener('change', e => commit({min: e.target.value === String(P.min_range.min) ? '' : e.target.value}));
$('f-age').addEventListener('change', e => commit({age: e.target.value, all: ''}));
$('f-find').addEventListener('input', e => { findText = e.target.value; if (P && P.scatter) drawScatter(); findList(); });
bindFind();
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
$('sq-view').addEventListener('click', e => {
  const b = e.target.closest('button[data-view]');
  if (b) commit({view: b.dataset.view === 'perf' ? 'perf' : ''});
});
window.addEventListener('popstate', () => { st = fromUrl(); render(); });

restoreState('physical');       // a bare /physical (the nav link) takes the last settings
st = fromUrl();
render();
