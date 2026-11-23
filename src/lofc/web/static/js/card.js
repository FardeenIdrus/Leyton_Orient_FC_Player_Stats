// Player card page (mockup v5 v-card + the "Against our <position>s" section).
// Draws what /api/card/... sends; it computes no number. Provider strings go through esc()/md()
// or textContent, never raw into innerHTML.
import {esc, dash, fmtInt, chip, pcol, bar, pctNum, thead, radar, orientSeries, api, readState, writeState, onStateChange} from './common.js';

const $ = id => document.getElementById(id);
const root = $('v-card');
const KEY = `${root.dataset.player}/${root.dataset.competition}/${root.dataset.season}`;
const md = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
const show = (id, on) => { $(id).hidden = !on; };
const INK = '#15171C', ORIENT = '#1F5FA8';

const state = {
  rank_as: readState().rank_as || '',
  money: ['1', 'true', 'on'].includes((readState().money || '').toLowerCase()),
  sq_season: readState().sq_season || '',
};
let card = null;      // the last /api/card response
let sqReq = 0;        // guards a slow squad response from overwriting a newer one

const query = obj => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(obj)) if (v !== '' && v != null && v !== false) q.set(k, v === true ? '1' : v);
  const s = q.toString();
  return s ? '?' + s : '';
};

// ---- small builders -------------------------------------------------------------------
const tile = (label, valueHtml, extra, title) =>
  `<div class="tile"${title ? ` title="${esc(title)}"` : ''}><div class="k">${esc(label)}</div><div class="v">${valueHtml}</div>${extra ? `<div class="x">${esc(extra)}</div>` : ''}</div>`;
const textTile = (t, extra) => tile(t.label, esc(dash(t.value)), extra);
const empty = text => `<p class="note">${esc(text)}</p>`;
const tw = html => `<div class="tw">${html}</div>`;
const NUMERIC = /^(Per|Season total|All phases|In possession|Out of possession|Minutes|Mins|Days|Matches|Goals|Assists|npxG|xA|Age|Saves|Tackles|Interceptions|Pass|Save|Top speed)/;
const fixed = (v, d = 2) => (v == null || !Number.isFinite(+v)) ? '—' : (+v).toFixed(d);

/** Generic table: cell(colName, value, rowIndex) returns inner HTML (already safe). */
function table(columns, rows, cell, {nowrap = false, helps = {}} = {}) {
  const num = c => NUMERIC.test(c) || c === VS;
  const head = '<tr>' + columns.map(c =>
    `<th class="${num(c) ? 'n ' : ''}col-${colSlug(c)}"${helps[c] ? ` title="${esc(helps[c])}"` : ''}>${esc(c)}</th>`).join('') + '</tr>';
  const body = rows.map((r, ri) => '<tr>' + r.map((v, i) =>
    `<td${num(columns[i]) ? ' class="n"' : ''}>${cell(columns[i], v, ri)}</td>`).join('') + '</tr>').join('');
  return `<table${nowrap ? ' style="white-space:nowrap"' : ''}><thead>${head}</thead><tbody>${body}</tbody></table>`;
}
const colSlug = c => String(c).replace(/[^a-z0-9]+/gi, '-').toLowerCase();
const plainCell = (c, v) => esc(dash(v));

// "vs ours": his percentile minus our position median's, computed by the API (core.card).
const VS = 'vs ours';
// his raw value minus our median, in the metric's unit; up = better for him (direction-aware)
const vsCell = v => v == null ? '<span class="vs">—</span>'
  : `<span class="vs ${v.kind || ''}">${esc(v.text)}</span>`;
/** Insert the "vs ours" column after Percentile (only when the API sent the column). */
function withVs(columns, rows, vs) {
  if (!vs) return [columns, rows];
  const at = columns.indexOf('Percentile') + 1 || columns.length;
  return [[...columns.slice(0, at), VS, ...columns.slice(at)],
    rows.map((r, i) => [...r.slice(0, at), vs[i], ...r.slice(at)])];
}
/** Rated-metrics table, optionally under thin weight-group headings (High / Mid / Low). */
function ratedTable(columns, rows, cell, {helps = {}, tiers = null} = {}) {
  const head = '<tr>' + columns.map(c =>
    `<th class="${NUMERIC.test(c) || c === VS || c === 'Band' ? 'n' : ''} col-${esc(colSlug(c))}"${helps[c] ? ` title="${esc(helps[c])}"` : ''}>${esc(c)}</th>`).join('') + '</tr>';
  const line = r => '<tr>' + r.map((v, i) =>
    `<td class="${NUMERIC.test(columns[i]) || columns[i] === VS || columns[i] === 'Band' ? 'n' : ''}">${cell(columns[i], v)}</td>`).join('') + '</tr>';
  let body;
  if (tiers && tiers.some(Boolean)) {
    const order = ['High', 'Mid', 'Low'];
    const groups = [...order, ...new Set(tiers.filter(t => t && !order.includes(t)))];
    body = groups.map(g => {
      const rs = rows.filter((_, i) => tiers[i] === g);
      return rs.length ? `<tr class="sec wt"><td colspan="${columns.length}">${esc(g)} weight</td></tr>` + rs.map(line).join('') : '';
    }).join('') + rows.filter((_, i) => !tiers[i]).map(line).join('');
  } else body = rows.map(line).join('');
  return `<table class="rated"><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

/** raw[i] = the table's per-90 value for that radar axis, when the table has the same label. */
function rawFor(labels, table, col) {
  if (!table || !table.columns) return null;
  const ci = table.columns.indexOf(col), li = 0;
  if (ci < 0) return null;
  const by = new Map(table.rows.map(r => [String(r[li]), r[ci]]));
  return labels.map(l => { const v = by.get(String(l)); return v == null || v === '' ? null : dash(v); });
}

function radarBlock(labels, player, orient, name, orientLabel, raw) {
  const series = [{values: player, name, raw}];
  const hasOrient = orient && orient.some(v => v != null);
  const gaps = hasOrient ? labels.filter((_, i) => orient[i] == null) : [];
  // A missing value would be drawn at the centre, which would be a wrong claim; a line with
  // gaps is not drawn, and a one-line note says which metrics it lacks.
  if (hasOrient && !gaps.length) series.push(orientSeries(orient, orientLabel || 'Leyton Orient median'));
  const note = gaps.length ? `Orient median not drawn: no value for ${gaps.join(', ')}.`
    : !hasOrient ? 'No Orient median: none of ours at this position rated in his league.' : '';
  return radar(labels, series) + (note ? `<p class="rdr-note">${esc(note)}</p>` : '');
}

// ---- header ---------------------------------------------------------------------------
function chipParts(c, cls) {
  return `<span class="st${cls}">` + c.parts.map(([t, b]) => b ? `<b>${esc(t)}</b>` : esc(t)).join('') + '</span>';
}

function renderHeader(c) {
  const H = c.header;
  $('h-pos').textContent = `${H.position} · ${H.league} · ${H.season_name}`;
  $('h-name').textContent = H.name;
  $('h-club').textContent = H.club_text;
  document.title = `${H.name} · LOFC Recruitment`;
  $('h-reg').innerHTML = H.register.map(r =>
    `<div>${esc(r.label)}<b${r.value == null ? ' class="absent"' : ''}>${esc(r.value ?? 'not recorded')}</b></div>`).join('');
  $('h-status').innerHTML = chipParts(H.contract, H.contract.expiring ? ' exp' : '')
    + (H.loan ? chipParts(H.loan, ' loan') : '');
  const m = H.minutes_by_position;
  $('h-mbp').innerHTML = m ? `<div class="note">Minutes by position</div>`
    + `<div class="bar">${m.segments.map(s => `<i style="width:${s.share_pct}%;background:${esc(s.colour)}" title="${esc(s.position)} ${Math.round(s.share_pct)}%"></i>`).join('')}</div>`
    + `<div class="note">${m.segments.map(s => (s.assigned ? `<b>${esc(s.position)}</b>` : esc(s.position)) + ` ${Math.round(s.share_pct)}%`).join(' · ')}</div>`
    + (m.goals_line ? `<div class="note">${esc(m.goals_line)}</div>` : '') : '';
  $('h-notes').innerHTML = (H.scored_as ? `<div class="info">${md(H.scored_as)}</div>` : '')
    + H.other_leagues.map(t => `<p class="note">${md(t)}</p>`).join('');
  setWatch(H.watched);
  const tm = $('h-tm');
  tm.hidden = !H.transfermarkt_url;
  if (H.transfermarkt_url) tm.href = H.transfermarkt_url;
  const sel = $('h-rank');
  const opts = c.meta.rank_as_options;
  show('h-rank-wrap', opts.length > 1);
  sel.innerHTML = opts.map(o => `<option value="${esc(o)}"${o === c.meta.rank_as ? ' selected' : ''}>${esc(o)}</option>`).join('');
  sel.setAttribute('aria-label', 'Rank as');
  // The way back names where it goes: the position list from Players, Squads & loans from
  // there, and a plain "← Back" from any other page (Compare, Scout reports, Watchlist, …).
  const from = new URL($('back').href, location.href).pathname;
  $('back').textContent = from === '/players' ? `← Back to ${c.meta.back_label}`
    : from === '/squads' ? '← Back to Squads & loans'
    : from === '/club-vs-league' ? '← Back to Club vs League One' : '← Back';
}

function setWatch(on) {
  const b = $('h-watch');
  b.textContent = on ? '★ On watchlist — remove' : '☆ Add to watchlist';
  b.dataset.watched = on ? '1' : '0';
  b.classList.toggle('primary', !on);
}

// ---- rating, season by season, current form -------------------------------------------
function renderRating(R) {
  $('r-h').textContent = R.heading;
  $('r-sub').textContent = R.sub;
  $('r-notrated').innerHTML = R.not_rated ? `<div class="notice">${esc(R.not_rated)}</div>` : '';
  $('r-tiles').innerHTML = [R.overall, R.performance, R.physical].map((t, i) =>
    `<div class="score${i === 0 ? ' main' : ''}"${t.help ? ` title="${esc(t.help)}"` : ''}><div class="k">${esc(t.label)}</div>`
    + `<div class="v">${chip(t.value)}</div>${t.rank_text ? `<div class="x">${esc(t.rank_text)}</div>` : ''}`
    // rated against all midfielders: the tag sits where his rank would (he has none)
    + `${i === 0 && R.pool_tag ? `<div class="x"><span class="pill grey">${esc(R.pool_tag)}</span></div>` : ''}</div>`).join('');
  const M = R.money;
  show('r-money', !!(M && M.tiles.length));
  $('r-money').innerHTML = M ? M.tiles.map(t => tile(t.label, esc(t.value))).join('') : '';
  show('r-moneycap', !!(M && M.captions.length));
  $('r-moneycap').innerHTML = M ? M.captions.map(t => `<p class="note money-cap">${esc(t)}</p>`).join('') : '';
  show('r-adv', !!R.advisory);
  $('r-adv').innerHTML = R.advisory ? `<b>⚠️ ${esc(R.advisory.title)}</b><ul>${R.advisory.flags.map(f => `<li>${esc(f)}</li>`).join('')}</ul>` : '';
  const S = R.strengths;
  const line = (cls, label, items) => `<div><span class="${cls}">${label}</span> ${items.map(s => `${esc(s.metric)} (${s.pct})`).join(' · ')}</div>`;
  $('r-sw').innerHTML = S ? line('g', 'Strengths', S.strengths) + line('r', 'Watch-outs', S.watch_outs) : '';
}

const SBS_HELP = {
  Overall: "The club composite that season, in that league: Performance + Physical. Each is a rank against THAT league's peers, so two leagues are not like-for-like.",
  Performance: 'Performance band that season (event data).',
  Physical: 'Physical band that season (SkillCorner).'};

function renderSeasons(c) {
  const B = c.season_by_season;
  $('sbs-sub').textContent = B.sub;
  if (!B.table) {
    $('sbs').innerHTML = empty(B.empty);
  } else {
    const t = B.table;
    $('sbs').innerHTML = table(t.columns, t.rows, (col, v) => {
      if (['Overall', 'Performance', 'Physical'].includes(col)) return chip(v);
      if (col === 'Minutes') return fmtInt(v);
      if (/\/90$/.test(col)) return fixed(v);
      if (/%$/.test(col)) return v == null ? '—' : `${Math.round(v)}`;
      return esc(dash(v));
    }, {nowrap: true, helps: SBS_HELP}) + `<p class="note">${esc(B.note)}</p>`;
  }
  const F = c.current_form;
  show('cf-h', !!F); show('cf-sub', !!F);
  if (!F) { $('cf').innerHTML = ''; $('cf-note').textContent = ''; return; }
  $('cf-h').textContent = F.heading;
  $('cf-sub').textContent = F.sub;
  $('cf').innerHTML = F.tiles ? F.tiles.map(t => textTile(t)).join('') : '';
  const split = F.split ? `Played for: ${F.split.map(s => `${esc(s.club)}${s.league ? ` (${esc(s.league)})` : ''} ${s.minutes == null ? '—' : s.minutes.toLocaleString('en-GB')} min`).join(' · ')}. ` : '';
  $('cf-note').innerHTML = split + esc(F.empty || F.not_scored || '');
}

// ---- playing style --------------------------------------------------------------------
function renderStyle(St) {
  const P = St.pills;
  const pills = P.strong.map(s => `<span class="pill strong">${esc(s)}</span>`).join('')
    + P.leans.map(s => `<span class="pill lean">${esc(s)}</span>`).join('');
  $('sf-pills').innerHTML = `<div class="pills-row">${pills || (P.label ? `<span class="note">${esc(P.label)}</span>` : '')}</div>`;
  if (!St.fit) {
    $('sf-sub').textContent = '';
    $('sf').innerHTML = pills || P.label ? '' : empty('No playing-style data for this player.');
    return;
  }
  const F = St.fit;
  $('sf-sub').textContent = F.sub;
  const fill = v => v >= F.strong ? '#1A1A1A' : v >= F.floor ? '#9A9AA2' : '#D3D3D8';
  $('sf').innerHTML = F.groups.map(g => (g.title ? `<h3>${esc(g.title)}</h3>` : '') + g.styles.map(s => {
    const p = Math.round(s.fit);
    const tag = s.tag === 'Strong' ? '<span class="pill strong">Strong</span>' : s.tag === 'Leans' ? '<span class="pill lean">Leans</span>' : '';
    return `<div class="style-row"><b>${esc(s.style)}</b>`
      + `<div class="pb"><div class="t"><i style="width:${p}%;background:${fill(s.fit)}"></i><u class="m50"></u><u class="m70"></u></div></div>`
      + `<b>${p}</b><span>${tag}</span><div class="style-sig">${esc(s.signals.join(' · '))}</div></div>`;
  }).join('')).join('')
    + `<p class="note">▮ ${F.strong} · Strong &nbsp;│ ${F.floor} · Leans &nbsp; ${esc(F.key)}</p>`;
}

// ---- season output, impect -------------------------------------------------------------
function renderOutput(c) {
  const O = c.season_output;
  $('so-h').textContent = O.heading;
  $('so-sub').textContent = O.sub;
  $('so').innerHTML = [...O.tiles, ...(O.rates ? O.rates.tiles : [])].map(t => textTile(t)).join('');
  $('so-cap').innerHTML = md([O.note, O.rates && O.rates.line].filter(Boolean).join(' '));
  const I = c.impect;
  $('im').innerHTML = I.tiles.length ? I.tiles.map(t => textTile(t, t.pct_text)).join('') : empty('No Impect scores for this player.');
  const bp = I.by_position;
  $('im-pos').innerHTML = bp ? `<p class="note">${esc(bp.caption)}</p>` + table(bp.columns, bp.rows, (col, v) =>
    col === 'Minutes' ? fmtInt(v) : esc(dash(v))) : '';
}

// ---- performance ----------------------------------------------------------------------
const PERF_HELP = {Source: 'Which provider supplies this metric.',
  Percentile: 'Rank vs peers in the same position, league and season (0-100).',
  Band: "The metric's 1-5 band (median→3, 70th→4)."};
const ALL_HELP = {Source: 'Which data provider supplies this metric.',
  Percentile: 'Rank against peers in the same position and league (0-100).'};

function renderPerformance(c) {
  const P = c.performance, base = `/api/card/${KEY}`;
  $('pr-sub').textContent = P.sub;
  const t = P.table;
  if (t) {
    // One source for every row: named once in the heading line instead of a column.
    const si = t.columns.indexOf('Source'), srcs = si < 0 ? [] : [...new Set(t.rows.map(r => r[si]))];
    let tc = t.columns, tr = t.rows;
    if (srcs.length === 1 && srcs[0]) {
      tc = tc.filter((_, i) => i !== si); tr = tr.map(r => r.filter((_, i) => i !== si));
      $('pr-sub').textContent = `${P.sub} · ${srcs[0]}`;
    }
    const [cols, rows] = withVs(tc, tr, P.vs_ours);
    $('pr').innerHTML = ratedTable(cols, rows, (col, v) =>
      col === 'Percentile' ? bar(v) : col === 'Band' ? chip(v) : col === VS ? vsCell(v)
        : col === 'Source' ? `<span class="src">${esc(dash(v))}</span>` : esc(dash(v)),
      {helps: {...PERF_HELP, [VS]: P.vs_ours_help}, tiers: P.tiers});
  } else $('pr').innerHTML = empty('No performance metrics in the rating for this player.');
  $('pr-note').textContent = 'Definitions on the Glossary page' + (P.scored_on_lens ? ' · scored on this archetype' : '') + '.';
  const csv = $('pr-csv');
  csv.hidden = !t;
  csv.href = `${base}/csv${query({kind: 'scorecard', rank_as: card.meta.rank_as})}`;
  const A = P.all_tracked;
  show('at-d', !!A);
  const atCsv = $('at-csv');
  atCsv.hidden = !A;
  if (A) {
    const [cols, rows] = withVs(A.columns, A.rows, A.vs_ours);
    $('at').innerHTML = table(cols, rows, (col, v) =>
      col === 'Percentile' ? bar(v) : col === VS ? vsCell(v)
        : col === 'Source' ? `<span class="note">${esc(dash(v))}</span>` : esc(dash(v)),
      {helps: {...ALL_HELP, [VS]: A.vs_ours_help}});
    $('at-csv').href = `${base}/csv${query({kind: 'metrics', rank_as: card.meta.rank_as})}`;
  }
  const PP = P.profile;
  $('c-pp').querySelector('.sub').textContent = PP ? PP.sub : '';
  $('pp').innerHTML = PP ? radarBlock(PP.labels, PP.player, PP.orient, c.header.name, PP.orient_label, rawFor(PP.labels, P.table, 'Per 90 / rate'))
    : empty('Not enough rated performance metrics for a profile.');
}

// ---- packing zones ---------------------------------------------------------------------
const ZLAYOUT = {IBWL: [1, '1'], IB: [2, '1'], IBWR: [3, '1'], WL: [1, '2 / span 2'], AM: [2, '2'], WR: [3, '2 / span 2'],
  CM: [2, '3'], FBL: [1, '4 / span 2'], DM: [2, '4'], FBR: [3, '4 / span 2'], CB: [2, '5']};
let zMode = 'per_match';

function renderZones(Z) {
  const pitch = $('pz');
  if (!Z) {
    $('pz-sub').textContent = '';
    show('pz-ctl', false); pitch.hidden = true; $('pz-legend').innerHTML = empty('No packing-zone data for this player.');
    return;
  }
  pitch.hidden = false; show('pz-ctl', true);
  $('pz-sub').textContent = Z.caption;
  const sel = $('pz-m'), keep = sel.value;
  sel.innerHTML = Z.metric_options.map(o => `<option value="${esc(o.key)}">${esc(o.label)}</option>`).join('');
  if (keep && Z.measures[keep]) sel.value = keep;
  if (!Z.value_modes.some(m => m.key === zMode)) zMode = Z.value_modes[0].key;
  $('pz-mode').innerHTML = Z.value_modes.map(m =>
    `<button type="button" data-mode="${esc(m.key)}" class="${m.key === zMode ? 'on' : ''}" aria-pressed="${m.key === zMode}">${esc(m.label)}</button>`).join('');
  const draw = () => {
    const m = Z.measures[sel.value], names = Object.fromEntries(Z.zones.map(z => [z.code, z.name]));
    let anyMissing = false;
    pitch.innerHTML = Object.entries(ZLAYOUT).map(([code, [col, row]]) => {
      const cell = (m.cells || {})[code] || {}, p = cell.percentile;
      if (p == null) anyMissing = true;
      const bg = p == null ? 'rgba(255,255,255,.15)' : p >= 70 ? '#2E7D4F' : p >= 30 ? '#E6E8EC' : '#C0392B';
      const ink = p != null && (p >= 70 || p < 30) ? '#fff' : '#15171C';
      const tip = `${names[code]}\n${dash(cell[zMode])} · ${cell.percentile_text || 'no percentile'}`;
      return `<div class="zone" style="grid-column:${col};grid-row:${row};background:${bg};color:${p == null ? '#D7E6DC' : ink}" data-tip="${esc(tip)}">`
        + `<span>${esc(names[code])}</span><b>${esc(dash(cell[zMode]))}</b><span>${p == null ? '' : 'P' + p}</span></div>`;
    }).join('') + '<div class="zone gk" style="grid-row:6">Goalkeeper zone · no data</div>';
    $('pz-legend').innerHTML = `<span><i style="background:var(--hi)"></i>70th percentile and above</span><span><i style="background:#E6E8EC"></i>30th to 69th</span><span><i style="background:var(--lo)"></i>Below 30th</span>`
      + (anyMissing ? '<span><i style="background:rgba(255,255,255,.15);border:1px dashed #8D939C"></i>No percentile (under 450 min)</span>' : '') + '<span>↑ Attacking</span>';
  };
  sel.onchange = draw;
  $('pz-mode').onclick = ev => {
    const b = ev.target.closest('button[data-mode]'); if (!b) return;
    zMode = b.dataset.mode;
    $('pz-mode').querySelectorAll('button').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', x === b); });
    draw();
  };
  draw();
}

function renderReceptions(R, c) {
  $('rc-sub').textContent = `Per 90 · percentile vs ${c.header.league} ${c.header.position}s`;
  $('rc').innerHTML = R ? table(R.columns, R.rows, (col, v) =>
    col === 'Percentile' ? bar(v) : esc(dash(v))) : empty('No reception data for this player.');
}

// ---- physical ---------------------------------------------------------------------------
// The rated table and "Other physical metrics" share ONE fixed column grid (card.css .phys),
// so their columns line up; Other has no Band, so it keeps an empty Band slot.
const PHYS_GRID = ['metric', 'all-phases', 'in-possession', 'out-of-possession', 'percentile', 'vs-ours', 'band'];
function physGrid(html, hasVs) {
  const cols = PHYS_GRID.filter(c => hasVs || c !== 'vs-ours');
  return html.replace(/^<table(?: class="([^"]*)")?>/, (_, cls) => `<table class="${cls ? cls + ' ' : ''}phys${hasVs ? '' : ' novs'}">`
    + '<colgroup>' + cols.map(c => `<col class="pc-${c}">`).join('') + '</colgroup>');
}

function renderPhysical(Ph, c) {
  $('rad-sub').textContent = Ph.sub;
  $('ph-sub').textContent = Ph.table_sub;
  $('prad').innerHTML = Ph.radar ? radarBlock(Ph.radar.labels, Ph.radar.player, Ph.radar.orient, c.header.name, Ph.radar.orient_label, rawFor(Ph.radar.labels, Ph.in_rating, Ph.in_rating && Ph.in_rating.columns[1]))
    : empty(Ph.in_rating ? 'Not enough rated physical metrics for a profile.' : (Ph.gap || "No physical data for this goalkeeper — physical does not count in a goalkeeper's rating."));
  const cell = (col, v) => col === 'Percentile' ? pctNum(v) : col === 'Band' ? chip(v) : esc(dash(v));
  const helps = {Percentile: 'Against the same position in his league.', Band: '1-5.'};
  $('ph-empty').innerHTML = !Ph.in_rating && !Ph.other ? empty(Ph.gap || "No physical data for this goalkeeper — physical does not count in a goalkeeper's rating.") : '';
  const IR = Ph.in_rating;
  if (IR && IR.rows.length) {
    const [cols, rows] = withVs(IR.columns, IR.rows, IR.vs_ours);
    $('ph').innerHTML = physGrid(ratedTable(cols, rows, (col, v) => col === VS ? vsCell(v) : cell(col, v),
      {helps: {...helps, [VS]: IR.vs_ours_help}}), !!IR.vs_ours);
  } else $('ph').innerHTML = '';
  const O = Ph.other;
  show('po-d', !!(O && O.rows.length));
  if (O && O.rows.length) {
    const [cols, rows] = withVs(O.columns, O.rows, O.vs_ours);
    // the empty Band slot: a blank last column, so the row lines run the full width
    $('po').innerHTML = physGrid(table([...cols, ''], rows.map(r => [...r, null]),
      (col, v) => col === VS ? vsCell(v) : col === '' ? '' : cell(col, v),
      {helps: {...helps, [VS]: O.vs_ours_help}}), !!O.vs_ours);
  } else $('po').innerHTML = '';
  $('ph-cap').textContent = Ph.in_rating || Ph.other ? Ph.caption : '';
}

// ---- scouting ---------------------------------------------------------------------------
const tonePill = t => t === 'positive' ? 'verdict-pos' : t === 'negative' ? 'verdict-neg' : 'verdict-mid';

function renderScouting(c) {
  const S = c.scout_reports;
  $('sr-h').textContent = S.heading;
  $('sr-v').innerHTML = S.verdicts.map(v => `<span class="pill ${tonePill(v.tone)}"><b>${v.count}</b> ${esc(v.verdict)}</span>`).join('');
  $('sr').innerHTML = S.empty ? empty(S.empty) : S.reports.map(r =>
    `<details class="report"${S.open_single ? ' open' : ''}><summary>${r.title.map(([t, b]) => b ? `<b>${esc(t)}</b>` : esc(t)).join(' · ')}</summary>`
    + (r.match ? `<p class="note">${esc(r.match)}</p>` : '') + (r.squad_role ? `<p class="note">Squad role: ${esc(r.squad_role)}</p>` : '')
    + (r.comments ? `<p class="txt">${esc(r.comments)}</p>` : '') + '</details>').join('');
}

function renderAvailability(A) {
  $('av-warn').innerHTML = A.warning ? `<div class="warn">${md(A.warning)}</div>` : '';
  $('av').innerHTML = A.tiles ? A.tiles.map(t => textTile(t)).join('') : '';
  $('av-cap').innerHTML = A.caption ? md(A.caption) : '';
  $('av-cov').innerHTML = A.coverage ? md(A.coverage) : '';
  const t = tb => tw(table(tb.columns, tb.rows, (col, v) => esc(dash(v))));
  let h = '';
  if (A.empty) h = `<div class="info">${esc(A.empty)}</div>`;
  else if (A.single) h = t(A.single) + (A.footnote ? `<p class="note">${esc(A.footnote)}</p>` : '');
  else {
    h = `<div class="spell-h">${esc(A.in_window.heading)}</div>` + (A.in_window.table ? `<div class="inwin">${t(A.in_window.table)}</div>` : empty(A.in_window.empty))
      + `<div class="spell-h">${esc(A.earlier.heading)}</div>` + (A.earlier.table ? t(A.earlier.table) : empty(A.earlier.empty))
      + (A.footnote ? `<p class="note">${esc(A.footnote)}</p>` : '');
  }
  $('inj').innerHTML = h;
}

// ---- Against our <position>s -------------------------------------------------------------
function renderSquad(S) {
  const box = $('c-squad');
  const seasons = S.seasons.map(s => `<button type="button" data-season="${s.id}" class="${s.id === S.season ? 'on' : ''}" aria-pressed="${s.id === S.season}">${esc(s.label)}</button>`).join('');
  let h = `<div class="sf-head"><div><h2>${esc(S.title)}</h2><div class="sub">${esc(S.subtitle)}</div></div>`
    + `<div class="seg" id="sq-seg" role="group" aria-label="Season">${seasons}</div></div>`;
  if (S.empty) { box.innerHTML = h + `<p>${esc(S.empty)}</p>`; return bindSquad(); }
  const V = S.verdict;
  // None of ours in his league that season (owner decision 2B): no rank, one line instead
  if (S.not_compared) h += `<p class="note">${esc(S.not_compared)}</p>`;
  else h += `<div class="verdict"><div><div class="k">Where he would sit by rating</div><div class="v">${esc(V.rank_text)}</div><div class="s">${esc(V.among)}</div></div>`
    + `<div><div class="k">His rating</div><div class="v">${fixed(V.his_rating)}</div><div class="s">${esc(V.his_league || '—')}</div></div>`
    + `<div><div class="k">Our best</div><div class="v">${fixed(V.our_best)}</div><div class="s">${esc(V.our_best_sub || '')}</div></div></div>`;
  const cols = ['Player', 'Age', 'Club that season', 'Minutes', 'Overall', 'Performance', 'Physical', 'Playing style', 'Contract to'];
  const rows = S.table.map(p => {
    const name = `${esc(p.name)}${p.is_target ? '<span class="tag">Target</span>' : ''}${p.note ? `<div class="note">${esc(p.note)}</div>` : ''}${p.elsewhere ? `<div class="note">${esc(p.elsewhere)}</div>` : ''}`;
    const club = `${esc(dash(p.club))}${p.league_abbr ? `<span class="lg" title="${esc(p.league || '')}">${esc(p.league_abbr)}</span>` : ''}`;
    const mid = p.unrated ? `<td colspan="4" class="note">${esc(p.unrated)}</td>`
      : `<td>${chip(p.overall)}</td><td>${chip(p.performance)}</td><td>${chip(p.physical)}</td><td>${esc(dash(p.style))}</td>`;
    return `<tr class="${p.is_target ? 'target' : ''}"><td>${name}</td><td class="n">${p.age == null ? '—' : p.age.toFixed(1)}</td><td>${club}</td><td class="n">${fmtInt(p.minutes)}</td>${mid}<td>${esc(dash(p.contract))}</td></tr>`;
  }).join('');
  h += tw(`<table><thead>${thead(cols)}</thead><tbody>${rows}</tbody></table>`);
  // every metric, player by player: raw values, each in his own league (green best, red worst);
  // the physical rows can be shown for All phases / In possession / Out of possession
  const M = S.metrics;
  let matrix = '';
  if (M) {
    const head = '<tr><th>Metric</th>' + M.players.map(p => `<th class="n">${esc(p.short)}${p.is_target ? '<span class="tag">Target</span>' : ''}${p.league_abbr ? `<div class="note" title="${esc(p.league || '')}">${esc(p.league_abbr)}</div>` : ''}</th>`).join('') + '</tr>';
    matrix = `<details class="sq-matrix"><summary>Every metric, player by player</summary><p class="note">${esc(M.note)}</p><div class="tw"><table><thead>${head}</thead><tbody id="sq-mx">${matrixBody(M, sqPhase)}</tbody></table></div></details>`;
  }
  if (S.not_compared) { box.innerHTML = h + matrix; return bindSquad(); }
  if (S.compare_note || !S.radar) { box.innerHTML = h + empty(S.compare_note || '') + matrix; return bindSquad(); }
  const li = it => `<li><span class="${it.kind}">${esc(it.arrow)}</span> ${esc(it.label)} <span class="note">· ${esc(it.detail)}</span></li>`;
  const list = L => `<b>${esc(L.heading)}</b><ul>${L.items.length ? L.items.map(li).join('') : '<li class="note">—</li>'}</ul>`;
  const R = S.radar;
  h += `<div class="sq-cols"><div><b>Performance profile</b> <span class="note">percentile · him vs our median</span>`
    + radarBlock(R.labels, R.target, R.ours_median, R.target_name, R.median_label) + '</div>'
    + `<div class="adds">${list(S.better)}${list(S.worse)}<div class="note">${esc(S.gap_note)}</div></div></div>`;
  h += matrix;
  box.innerHTML = h;
  bindSquad();
}

// the physical part of "Every metric": All phases, or SkillCorner's possession split. Every
// phase's rows are drawn once; the switch only shows one set (no re-render, nothing detached).
let sqPhase = 'All phases';
function matrixBody(M, phase) {
  const n = M.players.length + 1;
  const phases = M.phases ? ['All phases', ...Object.keys(M.phases)] : [];
  const rows = (rs, ph) => rs.map(r => `<tr${ph ? ` data-ph="${esc(ph)}"${ph === phase ? '' : ' hidden'}` : ''}><td>${esc(r.label)}</td>` + r.cells.map(x =>
    `<td class="n ${x.kind || ''}">${x.value == null ? '—' : esc(x.value)}</td>`).join('') + '</tr>').join('');
  return M.sections.map(sec => {
    if (sec.name !== 'Physical' || phases.length < 2)
      return `<tr class="sec"><td colspan="${n}">${esc(sec.name)}</td></tr>` + rows(sec.rows, null);
    const sw = ` <span class="seg sq-phase" role="group" aria-label="Phase">${phases.map(ph =>
      `<button type="button" data-phase="${esc(ph)}" aria-pressed="${ph === phase}" class="${ph === phase ? 'on' : ''}">${esc(ph)}</button>`).join('')}</span>`;
    const split = Object.keys(M.phases).map(ph => rows(M.phases[ph].rows, ph)
      + `<tr data-ph="${esc(ph)}"${ph === phase ? '' : ' hidden'}><td colspan="${n}" class="note">Speed and agility have no possession split.</td></tr>`).join('');
    return `<tr class="sec"><td colspan="${n}">${esc(sec.name)}${sw}</td></tr>` + rows(sec.rows, 'All phases') + split;
  }).join('');
}

function showPhase(mx, phase) {
  sqPhase = phase;
  mx.querySelectorAll('tr[data-ph]').forEach(tr => { tr.hidden = tr.dataset.ph !== phase; });
  mx.querySelectorAll('button[data-phase]').forEach(b => {
    const on = b.dataset.phase === phase; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
  });
}

function bindSquad() {
  const mx = $('sq-mx');
  if (mx) mx.onclick = ev => {
    const b = ev.target.closest('button[data-phase]'); if (b) showPhase(mx, b.dataset.phase);
  };
  const seg = $('sq-seg');
  if (!seg) return;
  seg.onclick = ev => {
    const b = ev.target.closest('button[data-season]'); if (!b) return;
    state.sq_season = b.dataset.season;
    writeState({sq_season: state.sq_season});
    loadSquad();
  };
}

async function loadSquad() {
  const mine = ++sqReq;
  try {
    const S = await api(`/api/card/${KEY}/squad${query({season: state.sq_season, rank_as: state.rank_as})}`);
    if (mine === sqReq) renderSquad(S);
  } catch (e) {
    if (mine === sqReq) $('c-squad').innerHTML = `<h2>Against our players</h2><p class="note">Could not load this section (${esc(e.message)}).</p>`;
  }
}

// ---- similar players (core.similar; owner-approved 2026-11-16) -----------------------------
// Its own request, made once the section nears the screen (or "Find similar" is pressed).
// Filters (owner 2026-11-20): League (All leagues only), Max age, Min minutes, Contract.
const sim = (() => {
  const s = readState();
  return {scope: s.sim_scope === 'all' ? 'all' : 'league', age: s.sim_age || '',
    league: s.sim_league || '', min: s.sim_min || '', contract: s.sim_contract || ''};
})();
let simReq = 0, simAsked = false, simObs = null;
const simBack = () => '?back=' + encodeURIComponent(location.pathname + location.search + '#c-similar');
/** The Similar players page's query for the current filters (+ a selected match). */
const simPageQuery = (match = '') => query({scope: sim.scope === 'all' ? 'all' : '', max_age: sim.age,
  league: sim.scope === 'all' ? sim.league : '', min_minutes: sim.min, contract: sim.contract, match: match});
const simApiQuery = () => simPageQuery();
const simOpts = (list, cur, first = 'Any') => `<option value="">${esc(first)}</option>`
  + list.map(([v, t]) => `<option value="${esc(v)}"${String(v) === String(cur ?? '') ? ' selected' : ''}>${esc(t)}</option>`).join('');

function renderSimilar(D) {
  $('sim-sub').textContent = D.sub || '';
  for (const b of $('sim-scope').querySelectorAll('button')) {
    const on = b.dataset.scope === D.scope;
    b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
  }
  const all = D.scope === 'all';
  $('sim-league-wrap').hidden = !all;
  $('sim-league').innerHTML = simOpts(D.league_options || [], D.league, 'All');
  $('sim-age').innerHTML = simOpts((D.age_options || []).map(a => [a, a]), D.max_age);
  $('sim-min').innerHTML = simOpts((D.min_minutes_options || []).map(m => [m, fmtInt(m)]), D.min_minutes);
  $('sim-contract').innerHTML = simOpts(D.contract_options || [], D.contract);
  $('sim-how').href = `/similar/${KEY}${simPageQuery()}`;
  $('sim-notes').innerHTML = [D.note, D.pool_note, D.physical_note].filter(Boolean)
    .map(t => `<p class="note sim-note">${esc(t)}</p>`).join('');
  if (!D.rows || !D.rows.length) { $('sim').innerHTML = empty(D.empty || ''); return; }
  const cols = ['Player', 'Club', ...(all ? ['League'] : []), 'Age', 'Minutes', 'Overall', 'Similarity %', 'Biggest differences', ''];
  const helps = {'Similarity %': D.similarity_help, 'Biggest differences': D.diff_help,
    Overall: 'Rated in his own league.'};
  const head = '<tr>' + cols.map(c => `<th class="${['Age', 'Minutes', 'Similarity %'].includes(c) ? 'n ' : ''}col-${colSlug(c || 'why')}"${helps[c] ? ` title="${esc(helps[c])}"` : ''}>${esc(c)}</th>`).join('') + '</tr>';
  const body = D.rows.map(r => '<tr>'
    + `<td><a href="${esc(r.href)}${simBack()}">${esc(r.name)}</a></td>`
    + `<td>${esc(dash(r.club))}</td>` + (all ? `<td>${esc(dash(r.league))}</td>` : '')
    + `<td class="n">${r.age == null ? '—' : r.age.toFixed(1)}</td><td class="n">${fmtInt(r.minutes)}</td>`
    + `<td>${chip(r.overall)}</td><td class="n"><b>${r.similarity == null ? '—' : r.similarity}</b></td>`
    + `<td class="sim-diff">${esc(r.differences_text || '—')}</td>`
    + `<td class="sim-why"><a href="/similar/${KEY}${esc(simPageQuery(r.key))}">Why</a></td></tr>`).join('');
  $('sim').innerHTML = `<table class="sim"><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

async function loadSimilar() {
  simAsked = true;
  const mine = ++simReq;
  $('sim').innerHTML = '<div class="skel" style="height:120px"></div>';
  try {
    const D = await api(`/api/card/${KEY}/similar${simApiQuery()}`);
    if (mine !== simReq) return;
    renderSimilar(D);
    if (location.hash === '#c-similar') $('c-similar').scrollIntoView();
  } catch (e) {
    if (mine === simReq) $('sim').innerHTML = empty(`Could not load this section (${e.message}).`);
  }
}

function armSimilar(c) {
  const on = !!(c.similar && c.similar.available);
  show('h-similar', on); show('c-similar', on);
  if (!on || simAsked) return;
  if (location.hash === '#c-similar' || !('IntersectionObserver' in window)) return loadSimilar();
  if (simObs) simObs.disconnect();
  simObs = new IntersectionObserver(es => {
    if (es.some(e => e.isIntersecting) && !simAsked) { simObs.disconnect(); loadSimilar(); }
  }, {rootMargin: '400px'});
  simObs.observe($('c-similar'));
}

function bindSimilar() {
  $('h-similar').onclick = () => {
    $('c-similar').scrollIntoView({behavior: 'smooth', block: 'start'});
    if (!simAsked) loadSimilar();
  };
  $('sim-scope').onclick = ev => {
    const b = ev.target.closest('button[data-scope]'); if (!b || b.dataset.scope === sim.scope) return;
    sim.scope = b.dataset.scope;
    writeState({sim_scope: sim.scope === 'all' ? 'all' : ''});
    loadSimilar();
  };
  const pick = (id, key, stateKey) => {
    $(id).onchange = ev => {
      sim[key] = ev.target.value;
      writeState({[stateKey]: sim[key]});
      loadSimilar();
    };
  };
  pick('sim-age', 'age', 'sim_age');
  pick('sim-league', 'league', 'sim_league');
  pick('sim-min', 'min', 'sim_min');
  pick('sim-contract', 'contract', 'sim_contract');
}

// ---- page ---------------------------------------------------------------------------------
function renderAll(c) {
  card = c;
  renderHeader(c);
  renderRating(c.rating);
  renderSeasons(c);
  renderStyle(c.style);
  renderOutput(c);
  renderPerformance(c);
  renderZones(c.packing_zones);
  renderReceptions(c.receptions, c);
  renderPhysical(c.physical, c);
  renderScouting(c);
  renderAvailability(c.availability);
  armSimilar(c);
}

function setSwitch() {
  const sw = $('money-sw');
  sw.classList.toggle('on', state.money);
  sw.setAttribute('aria-checked', state.money);
}

let cardReq = 0;       // guards a slow card response from overwriting a newer one

// Rank as: build the other lenses' card and squad answers ahead of a switch, one at a time
// (lofc.web.prefetch hand-off) when the pointer rests on, or focus reaches, the select.
let lensPf = false;
function prefetchLenses() {
  if (lensPf || !card) return;
  lensPf = true;
  const others = [...$('h-rank').options].map(o => o.value).filter(v => v !== (state.rank_as || 'All Metrics'));
  const urls = others.flatMap(v => {
    const ra = v === 'All Metrics' ? '' : v;
    return [`/api/card/${KEY}${query({rank_as: ra, money: state.money})}`,
            `/api/card/${KEY}/squad${query({season: state.sq_season, rank_as: ra})}`];
  });
  urls.reduce((p, u) => p.then(() => fetch(u, {headers: {'X-LOFC-Prefetch': '1', 'Accept': 'application/json'},
    credentials: 'same-origin'}).then(r => r.text()).catch(() => {})), Promise.resolve());
}
// ---- game performances (owner 2026-11-23, phase 4) ----------------------------------------
// a short club name under the dot (the full one on hover): no "FC", at most 11 characters
const shortClub = n => { const t = String(n || '').replace(/\b(A?FC|Glasgow)\b/g, '').replace(/\s+/g, ' ').trim();
  return t.length > 11 ? t.slice(0, 10).trim() + '…' : t; };
// Each of his last games: better than X% of that position's games in his league (45+ minutes),
// Top above 80 / Low below 20, as in Impect. Hollow dot = under 45 minutes (not counted).
// Owner 2026-11-23 (N21): the club's own Overall / Performance / Physical per game beside
// Impect's scores; click a game for every metric behind it; Excel holds every game.
let GP = null, gpTab = 'overall', gpImp = 'impect', gpSel = null, gpW = 0;
const GP_TABS = [['overall', 'Overall'], ['performance', 'Performance'], ['physical', 'Physical'], ['impect', 'Impect']];
const GP_IMP = [['impect', 'IMPECT'], ['offensive', 'Offensive'], ['defensive', 'Defensive']];
const gpKey = () => gpTab === 'impect' ? gpImp : gpTab;
const gpClub = k => ['overall', 'performance', 'physical'].includes(k);
const gpDetail = new Map();
function drawGames() {
  const box = $('c-games');
  if (!GP) { box.hidden = true; return; }
  box.hidden = false;
  if (!GP.has_club && gpClub(gpTab)) gpTab = 'impect';
  // With Impect's scores only, the one switch is IMPECT / Offensive / Defensive (owner
  // 2026-11-23: an "Impect" tab above its own switch read as a duplicate).
  $('gp-tabs').hidden = !GP.has_club;
  $('gp-tabs').innerHTML = (GP.has_club ? GP_TABS : []).map(([k, l]) =>
    `<button type="button" data-gp="${k}" class="${k === gpTab ? 'on' : ''}" aria-pressed="${k === gpTab}">${esc(l)}</button>`).join('');
  $('gp-imp').hidden = gpTab !== 'impect';
  $('gp-imp').innerHTML = GP_IMP.map(([k, l]) =>
    `<button type="button" data-gpi="${k}" class="${k === gpImp ? 'on' : ''}" aria-pressed="${k === gpImp}">${esc(l)}</button>`).join('');
  $('gp-xl').href = `/api/card/${KEY}/games.xlsx`;
  $('gp-xl').hidden = !GP.has_club;
  const key = gpKey(), name = GP.labels[key];
  // Drawn at the card's real width in pixels (owner 2026-11-24: a scaled drawing grew the text
  // with the page, so the chart was huge on wide screens and when zoomed out). Fixed height and
  // fixed text sizes; opponent names on two staggered rows when the games sit close together.
  // The box has no width while the page is still hidden (loading): draw nothing then -- the
  // ResizeObserver below draws it the moment it gets its real width (owner 2026-11-23: it was
  // drawn at a small fallback width and never redrawn).
  const cw = Math.round($('gp').clientWidth);
  gpW = cw;
  const g = GP.games, W = Math.max(520, cw), PH = 200;
  const x0 = 78, x1 = W - 40, top = 26;
  const y = p => top + (100 - p) * (PH - top - 8) / 100;
  const step = g.length > 1 ? (x1 - x0) / (g.length - 1) : 0;
  const rows = g.length > 1 && step < 96 ? 2 : 1;
  const H = PH + (rows === 2 ? 58 : 44);
  if (gpSel == null || !g.some(m => m.match_id === gpSel)) gpSel = g.length ? g[g.length - 1].match_id : null;
  const xs = i => g.length > 1 ? x0 + i * step : (x0 + x1) / 2;
  const si = g.findIndex(m => m.match_id === gpSel), sw = Math.min(step || 68, 68);
  let svg = `<svg width="${W}" height="${H}" class="gp-svg" role="img" aria-label="Game performances">`
    + (si >= 0 ? `<rect x="${xs(si) - sw / 2}" y="${top - 18}" width="${sw}" height="${PH + rows * 14 + 22 - top}" rx="6" class="gp-sel"/>` : '')
    + `<rect x="${x0 - 14}" y="${y(100)}" width="${x1 - x0 + 28}" height="${y(80) - y(100)}" class="gp-bt"/>`
    + `<rect x="${x0 - 14}" y="${y(20)}" width="${x1 - x0 + 28}" height="${y(0) - y(20)}" class="gp-bl"/>`
    + [80, 20].map(v => `<line x1="${x0 - 14}" x2="${x1 + 14}" y1="${y(v)}" y2="${y(v)}" class="gp-ln"/>`).join('')
    + `<text x="4" y="${y(90) + 4}" class="gp-lbl">Top</text><text x="4" y="${y(50) + 4}" class="gp-lbl">Average</text><text x="4" y="${y(10) + 4}" class="gp-lbl">Low</text>`;
  let short = 0;
  g.forEach((m, i) => {
    const x = xs(i), sc = m.scores[key];
    const row = rows === 2 ? i % 2 : 0, ly = PH + 14 + row * 14;
    const where = (m.home ? 'v ' : '@ ') + m.opponent;
    svg += `<text x="${x}" y="${ly}" class="gp-opp${m.match_id === gpSel ? ' on' : ''}" text-anchor="middle" data-tip="${esc(where)}">${esc((m.home ? '' : '@ ') + shortClub(m.opponent))}</text>`
      + `<text x="${x}" y="${PH + 14 + rows * 14}" class="gp-min" text-anchor="middle">${esc(m.date)}</text>`;
    const base = `${where} · ${m.date} · ${m.minutes ?? '—'} min`;
    if (sc.pct == null) {
      // a club score is not given for a game under 45 minutes: shown, never rated
      if (gpClub(key) && !m.counted) {
        short++;
        svg += `<circle cx="${x}" cy="${y(50)}" r="5.5" class="gp-sub"/>`
          + `<circle cx="${x}" cy="${y(50)}" r="14" class="gp-hit" data-g="${m.match_id}" data-tip="${esc(base + ' · no rating: under 45 min')}" tabindex="0"/>`;
      }
      return;
    }
    const val = gpClub(key) && sc.value != null ? ` · ${name} ${sc.value.toFixed(2)}` : '';
    const tip = base + val + ` · better than ${sc.pct}% (${sc.level})` + (m.counted ? '' : ' · under 45 min, not counted');
    const cls = !m.counted ? 'gp-sub' : sc.level === 'Top' ? 'gp-t' : sc.level === 'Low' ? 'gp-l' : 'gp-a';
    svg += `<text x="${x}" y="${y(sc.pct) - 12}" class="gp-pct" text-anchor="middle">${sc.pct}%</text>`
      + `<circle cx="${x}" cy="${y(sc.pct)}" r="${m.counted ? 7 : 5.5}" class="${cls}"/>`
      + (m.match_id === gpSel ? `<circle cx="${x}" cy="${y(sc.pct)}" r="11" class="gp-ring"/>` : '')
      + `<circle cx="${x}" cy="${y(sc.pct)}" r="14" class="gp-hit" data-g="${m.match_id}" data-tip="${esc(tip)}" tabindex="0"/>`;
  });
  $('gp').innerHTML = cw ? svg + '</svg>' : '';
  const c = GP.counts[key];
  $('gp-counts').innerHTML = `<span class="c t">${c.Top} Top</span><span class="c a">${c.Average} Average</span><span class="c l">${c.Low} Low</span>`
    + (short ? `<span class="c s">${short} under 45 min</span>` : '')
    + `<span class="note">last ${g.length} games · click a dot for the game</span>`;
  $('gp-sub').textContent = gpClub(key) ? `Club ${name.toLowerCase()} score per game` : `Impect ${name} per game`;
  $('gp-note').textContent = gpClub(key) ? GP.club_note : GP.note;
  drawGameDetail();
}
const gpRow = r => {
  const pct = r.pct == null ? '' : `<div class="pb"><div class="t"><i style="width:${r.pct}%;background:${r.pct > 80 ? 'var(--hi)' : r.pct < 20 ? 'var(--lo)' : '#C9A227'}"></i></div><b>${r.pct}</b></div>`;
  const p90 = r.per90 == null ? '—' : Math.abs(r.per90) >= 100
    ? Math.round(r.per90).toLocaleString('en-GB') : r.per90.toLocaleString('en-GB', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  return `<td class="n g">${esc(r.game ?? '—')}</td><td class="n">${p90}</td>`
    + `<td>${r.out ? '' : pct}</td><td class="c">${r.out || r.band == null ? '—' : chip(r.band)}</td>`;
};
async function drawGameDetail() {
  const box = $('gd');
  const m = GP ? GP.games.find(x => x.match_id === gpSel) : null;
  if (!m) { box.hidden = true; return; }
  box.hidden = false;
  const head = `${m.home ? 'v' : '@'} ${esc(m.opponent)} (${m.home ? 'H' : 'A'}) · ${esc(m.date)} · ${m.minutes ?? '—'} min · ${esc(m.position || '')}`;
  const s = m.scores;
  const tile = (k, label, v, sc, extra = '') => `<div class="gd-tile${(gpTab === k || (k === 'impect' && gpTab === 'impect')) ? ' on' : ''}" data-gt="${k}">
      <div class="k">${label}</div><div class="v">${v}${sc.pct == null ? '' : `<small>${sc.pct}%</small>`}</div>
      <div class="x">${sc.level ? `<span class="lv ${sc.level}">${sc.level}</span>` : '<span class="lv">no rating</span>'}${extra}</div></div>`;
  const cv = sc => sc.value == null ? '—' : sc.value.toFixed(2);
  let h = `<div class="gd-h"><b>${head}</b></div><div class="gd-tiles">`
    + tile('overall', 'Overall', cv(s.overall), s.overall)
    + tile('performance', 'Performance', cv(s.performance), s.performance)
    + tile('physical', 'Physical', cv(s.physical), s.physical)
    + tile('impect', 'Impect', s.impect.pct == null ? '—' : `${s.impect.pct}%`, {pct: null, level: s.impect.level},
      `<br>Offensive ${s.offensive.pct ?? '—'}% · Defensive ${s.defensive.pct ?? '—'}%`)
    + `</div><p class="note">Overall = Performance 65% + Physical 35%. Band 1–5 = 3 + (% − 50) ÷ 20.</p>`;
  if (!m.counted) h += `<p class="note">No rating: under 45 min. Values shown, not compared.</p>`;
  if (!GP.has_club) { box.innerHTML = h + '<p class="note">Club scores for this game are not in yet.</p>'; return; }
  box.innerHTML = h + '<div id="gd-t" class="muted">Loading the game…</div>';
  let d = gpDetail.get(m.match_id);
  if (!d) {
    try { d = await api(`/api/card/${KEY}/games/${m.match_id}`); gpDetail.set(m.match_id, d); }
    catch { if ($('gd-t')) $('gd-t').textContent = 'Could not load this game.'; return; }
  }
  if (gpSel !== m.match_id || !$('gd-t')) return;
  const perf = d.perf.map(r => `<tr class="${r.out ? 'out' : ''}"><td>${esc(r.label)}${r.lower_better ? ' <span class="lib">lower is better</span>' : ''}</td>`
    + gpRow(r) + `<td>${esc(r.weight || '')}</td><td class="kpi">${esc(r.source)}</td></tr>`).join('');
  const phys = d.phys.map(r => `<tr class="${r.out ? 'out' : ''}"><td>${esc(r.label)}</td>`
    + gpRow(r) + `<td class="kpi">${esc(r.source)}</td></tr>`).join('');
  $('gd-t').outerHTML = `<h3>Performance <span class="lib">Impect</span></h3><div class="tw"><table class="gd-tbl">
      <thead><tr><th>Metric</th><th class="n">This game</th><th class="n">Per 90</th><th>% vs games</th><th class="c">Band</th><th>Weight</th><th>Impect KPI</th></tr></thead><tbody>${perf}</tbody></table></div>`
    + (phys ? `<h3>Physical <span class="lib">SkillCorner</span></h3><div class="tw"><table class="gd-tbl">
      <thead><tr><th>Metric</th><th class="n">This game</th><th class="n">Per 90</th><th>% vs games</th><th class="c">Band</th><th>SkillCorner column</th></tr></thead><tbody>${phys}</tbody></table></div>` : '');
}
async function loadGames() {
  try { GP = (await api(`/api/card/${KEY}/games`)).block; } catch { GP = null; }
  drawGames();
}

async function loadCard({squad = true} = {}) {
  const mine = ++cardReq;
  const url = `/api/card/${KEY}${query({rank_as: state.rank_as, money: state.money})}`;
  // The squad section is its own request and needs nothing from the card's answer (the
  // server resolves the lens the same way), so both are asked for at once.
  if (squad) loadSquad();
  if (squad) loadGames();
  try {
    const c = await api(url);
    if (mine !== cardReq) return;
    state.rank_as = c.meta.rank_as === 'All Metrics' ? '' : c.meta.rank_as;
    lensPf = false;
    show('card-status', false);
    const first = $('card-body').hidden;
    renderAll(c);
    show('card-skel', false); show('card-body', true);
    if (first) $('card-body').classList.add('fade-in');
  } catch (e) {
    if (mine !== cardReq) return;
    show('card-skel', false);
    $('card-status').hidden = false;
    $('card-status').textContent = e.status === 404 ? 'No such player and season.' : `Could not load the player (${e.message}).`;
  }
}

function init() {
  // Selects exist before the data does, holding the URL's choice, so a page opened from a
  // shared link already shows it.
  $('h-rank').innerHTML = `<option value="${esc(state.rank_as || 'All Metrics')}">${esc(state.rank_as || 'All Metrics')}</option>`;
  const back = readState().back || '';
  // Only a path on this site: never follow an arbitrary address from the query string.
  if (/^\/(?!\/)[^\\]*$/.test(back)) $('back').href = back;
  // Name the way back at once (the position is filled in when the card arrives), so the
  // link never shows the wrong page while the player loads.
  const from = new URL($('back').href, location.href).pathname;
  if (from === '/squads') $('back').textContent = '← Back to Squads & loans';
  else if (from === '/club-vs-league') $('back').textContent = '← Back to Club vs League One';
  else if (from !== '/players') $('back').textContent = '← Back';
  setSwitch();
  bindSimilar();
  const flip = () => { state.money = !state.money; setSwitch(); writeState({money: state.money ? '1' : ''}); loadCard({squad: false}); };
  $('money-sw').onclick = flip;
  $('money-sw').onkeydown = ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); flip(); } };
  let lensTimer = 0;
  $('h-rank-wrap').addEventListener('pointerenter', () => { lensTimer = setTimeout(prefetchLenses, 80); });
  $('h-rank-wrap').addEventListener('pointerleave', () => clearTimeout(lensTimer));
  $('h-rank').addEventListener('focus', prefetchLenses);
  $('h-rank').onchange = ev => {
    state.rank_as = ev.target.value === 'All Metrics' ? '' : ev.target.value;
    writeState({rank_as: state.rank_as});
    loadCard();
  };
  $('h-watch').onclick = async () => {
    const b = $('h-watch'), was = b.dataset.watched === '1';
    b.disabled = true;
    try {
      const r = await api(`/api/card/${KEY}/watchlist`, {json: {action: was ? 'remove' : 'add'}});
      setWatch(r.watched);
    } catch (e) {
      $('card-status').hidden = false;
      $('card-status').textContent = `Could not update the watchlist (${e.message}).`;
    } finally { b.disabled = false; }
  };
  // Browser back / forward: the URL is the state, so read it and redraw.
  onStateChange(q => {
    state.rank_as = q.rank_as || '';
    state.money = ['1', 'true', 'on'].includes((q.money || '').toLowerCase());
    state.sq_season = q.sq_season || '';
    const next = {scope: q.sim_scope === 'all' ? 'all' : 'league', age: q.sim_age || '',
      league: q.sim_league || '', min: q.sim_min || '', contract: q.sim_contract || ''};
    const changed = Object.keys(next).some(k => next[k] !== sim[k]);
    Object.assign(sim, next);
    if (simAsked && changed) loadSimilar();
    setSwitch();
    loadCard();
  });
  loadCard();
}
init();

document.addEventListener('click', e => {
  const b = e.target.closest('#gp-tabs [data-gp]');
  if (b) { gpTab = b.dataset.gp; drawGames(); return; }
  const i = e.target.closest('#gp-imp [data-gpi]');
  if (i) { gpImp = i.dataset.gpi; drawGames(); return; }
  const t = e.target.closest('#gd [data-gt]');
  if (t) { gpTab = t.dataset.gt; drawGames(); return; }
  const d = e.target.closest('#gp [data-g]');
  if (d && GP) { gpSel = +d.dataset.g; drawGames(); }
});
document.addEventListener('keydown', e => {
  const d = e.target.closest && e.target.closest('#gp [data-g]');
  if (d && GP && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); gpSel = +d.dataset.g; drawGames(); }
});
// redrawn at the new width (the chart is drawn in real pixels)
// Redrawn whenever its box changes width: the page appearing after loading, a window resize,
// zoom (the chart is drawn in real pixels).
let gpResize = null;
new ResizeObserver(() => {
  clearTimeout(gpResize);
  gpResize = setTimeout(() => { const w = Math.round($('gp').clientWidth); if (GP && w && w !== gpW) drawGames(); }, 60);
}).observe($('gp'));
