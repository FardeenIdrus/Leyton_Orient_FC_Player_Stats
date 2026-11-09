// Player card page (mockup v5 v-card + the "Against our <position>s" section).
// Draws what /api/card/... sends; it computes no number. Provider strings go through esc()/md()
// or textContent, never raw into innerHTML.
import {esc, dash, fmtInt, chip, pcol, bar, thead, radar, orientSeries, api, readState, writeState, onStateChange} from './common.js';

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
  const head = '<tr>' + columns.map(c =>
    `<th${NUMERIC.test(c) ? ' class="n"' : ''}${helps[c] ? ` title="${esc(helps[c])}"` : ''}>${esc(c)}</th>`).join('') + '</tr>';
  const body = rows.map((r, ri) => '<tr>' + r.map((v, i) =>
    `<td${NUMERIC.test(columns[i]) ? ' class="n"' : ''}>${cell(columns[i], v, ri)}</td>`).join('') + '</tr>').join('');
  return `<table${nowrap ? ' style="white-space:nowrap"' : ''}><thead>${head}</thead><tbody>${body}</tbody></table>`;
}
const plainCell = (c, v) => esc(dash(v));

// "vs ours": his percentile minus our position median's, computed by the API (core.card).
const VS = 'vs ours';
const vsCell = v => v == null ? '<span class="vs">—</span>'
  : `<span class="vs ${v > 0 ? 'up' : v < 0 ? 'dn' : ''}">${v > 0 ? '+' + v : v < 0 ? '−' + (-v) : '0'}</span>`;
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
    `<th class="${NUMERIC.test(c) || c === VS || c === 'Band' ? 'n' : ''} col-${esc(c.replace(/[^a-z0-9]+/gi, '-').toLowerCase())}"${helps[c] ? ` title="${esc(helps[c])}"` : ''}>${esc(c)}</th>`).join('') + '</tr>';
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
    : !hasOrient ? 'No Orient median: no current player at this position has percentiles.' : '';
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
  $('h-assess').href = H.assess_url;
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
    : from === '/squads' ? '← Back to Squads & loans' : '← Back';
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
    + `<div class="v">${chip(t.value)}</div>${t.rank_text ? `<div class="x">${esc(t.rank_text)}</div>` : ''}</div>`).join('');
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
    $('at').innerHTML = table(A.columns, A.rows, (col, v) =>
      col === 'Percentile' ? bar(v) : col === 'Source' ? `<span class="note">${esc(dash(v))}</span>` : esc(dash(v)), {helps: ALL_HELP});
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
function renderPhysical(Ph, c) {
  $('rad-sub').textContent = Ph.sub;
  $('ph-sub').textContent = Ph.table_sub;
  $('prad').innerHTML = Ph.radar ? radarBlock(Ph.radar.labels, Ph.radar.player, Ph.radar.orient, c.header.name, Ph.radar.orient_label, rawFor(Ph.radar.labels, Ph.in_rating, Ph.in_rating && Ph.in_rating.columns[1]))
    : empty(Ph.in_rating ? 'Not enough rated physical metrics for a profile.' : (Ph.gap || "No physical data for this goalkeeper — physical does not count in a goalkeeper's rating."));
  const cell = (col, v) => col === 'Percentile' ? bar(v) : col === 'Band' ? chip(v) : esc(dash(v));
  const helps = {Percentile: 'Against the same position in his league.', Band: '1-5.'};
  $('ph-empty').innerHTML = !Ph.in_rating && !Ph.other ? empty(Ph.gap || "No physical data for this goalkeeper — physical does not count in a goalkeeper's rating.") : '';
  const IR = Ph.in_rating;
  if (IR && IR.rows.length) {
    const [cols, rows] = withVs(IR.columns, IR.rows, IR.vs_ours);
    $('ph').innerHTML = ratedTable(cols, rows, (col, v) => col === VS ? vsCell(v) : cell(col, v),
      {helps: {...helps, [VS]: IR.vs_ours_help}});
  } else $('ph').innerHTML = '';
  show('po-d', !!(Ph.other && Ph.other.rows.length));
  $('po').innerHTML = Ph.other && Ph.other.rows.length ? table(Ph.other.columns, Ph.other.rows, cell, {helps}) : '';
  $('ph-cap').textContent = Ph.in_rating || Ph.other ? Ph.caption : '';
}

// ---- scouting ---------------------------------------------------------------------------
const tonePill = t => t === 'positive' ? 'verdict-pos' : t === 'negative' ? 'verdict-neg' : 'verdict-mid';
const badgePill = t => ({approved: 'verdict-pos', pending: 'verdict-mid', rejected: 'verdict-neg'}[t] || 'grey');

function renderScouting(c) {
  const S = c.scout_reports;
  $('sr-h').textContent = S.heading;
  $('sr-v').innerHTML = S.verdicts.map(v => `<span class="pill ${tonePill(v.tone)}"><b>${v.count}</b> ${esc(v.verdict)}</span>`).join('');
  $('sr').innerHTML = S.empty ? empty(S.empty) : S.reports.map(r =>
    `<details class="report"${S.open_single ? ' open' : ''}><summary>${r.title.map(([t, b]) => b ? `<b>${esc(t)}</b>` : esc(t)).join(' · ')}</summary>`
    + (r.match ? `<p class="note">${esc(r.match)}</p>` : '') + (r.squad_role ? `<p class="note">Squad role: ${esc(r.squad_role)}</p>` : '')
    + (r.comments ? `<p class="txt">${esc(r.comments)}</p>` : '') + '</details>').join('');
  const A = c.scout_assessment;
  let h = A.warning ? `<div class="warn">${md(A.warning)}</div>` : '';
  if (A.empty) {
    h += `<div class="badge-row"><span class="pill grey">${esc(A.empty.badge)}</span></div><p class="note">${esc(A.empty.caption)}</p>`;
  }
  h += A.dimensions.map(d => {
    let x = `<div class="dim"><h4>${esc(d.name)}</h4>`;
    if (d.badge) x += `<div class="badge-row"><span class="pill ${badgePill(d.tone)}">${esc(d.badge)}</span></div>`;
    if (d.caption) x += `<p class="note">${esc(d.caption)}</p>`;
    if (d.entries) x += tw(table(d.entries.columns, d.entries.rows, (col, v) => esc(dash(v))));
    x += d.flags.map(f => `<p class="flagline">${md(f)}</p>`).join('');
    x += d.notes.map(n => `<details class="notes-d"><summary>${esc(n.author)}'s notes</summary>${n.blocks.map(b => `<p><b>${esc(b.heading)}</b><br>${esc(b.text)}</p>`).join('')}</details>`).join('');
    const k = d.criteria;
    if (k && k.note) x += `<p class="note">${esc(k.note)}</p>`;
    else if (k) x += `<details class="notes-d"><summary>${esc(k.label)}</summary>${k.empty ? empty(k.empty) : tw(table(k.columns, k.rows, (col, v) => esc(dash(v))))}</details>`;
    return x + '</div>';
  }).join('');
  $('sa').innerHTML = h;
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
  h += `<div class="verdict"><div><div class="k">Where he would sit by rating</div><div class="v">${esc(V.rank_text)}</div><div class="s">${esc(V.among)}</div></div>`
    + `<div><div class="k">His rating</div><div class="v">${fixed(V.his_rating)}</div><div class="s">${esc(V.his_league || '—')}</div></div>`
    + `<div><div class="k">Our best</div><div class="v">${fixed(V.our_best)}</div><div class="s">${esc(V.our_best_sub || '')}</div></div></div>`;
  const cols = ['Player', 'Age', 'Club that season', 'Minutes', 'Overall', 'Performance', 'Physical', 'Playing style', 'Contract to'];
  const rows = S.table.map(p => {
    const name = `${esc(p.name)}${p.is_target ? '<span class="tag">Target</span>' : ''}${p.note ? `<div class="note">${esc(p.note)}</div>` : ''}`;
    const club = `${esc(dash(p.club))}${p.league_abbr ? `<span class="lg" title="${esc(p.league || '')}">${esc(p.league_abbr)}</span>` : ''}`;
    const mid = p.unrated ? `<td colspan="4" class="note">${esc(p.unrated)}</td>`
      : `<td>${chip(p.overall)}</td><td>${chip(p.performance)}</td><td>${chip(p.physical)}</td><td>${esc(dash(p.style))}</td>`;
    return `<tr class="${p.is_target ? 'target' : ''}"><td>${name}</td><td class="n">${p.age == null ? '—' : p.age.toFixed(1)}</td><td>${club}</td><td class="n">${fmtInt(p.minutes)}</td>${mid}<td>${esc(dash(p.contract))}</td></tr>`;
  }).join('');
  h += tw(`<table><thead>${thead(cols)}</thead><tbody>${rows}</tbody></table>`);
  if (S.compare_note || !S.radar) { box.innerHTML = h + empty(S.compare_note || ''); return bindSquad(); }
  const li = it => `<li><span class="${it.kind}">${esc(it.arrow)}</span> ${esc(it.label)} <span class="note">· ${esc(it.detail)}</span></li>`;
  const list = L => `<b>${esc(L.heading)}</b><ul>${L.items.length ? L.items.map(li).join('') : '<li class="note">—</li>'}</ul>`;
  const R = S.radar;
  h += `<div class="sq-cols"><div><b>Performance profile</b> <span class="note">percentile · him vs our median</span>`
    + radarBlock(R.labels, R.target, R.ours_median, R.target_name, R.median_label) + '</div>'
    + `<div class="adds">${list(S.better)}${list(S.worse)}<div class="note">${esc(S.gap_note)}</div></div></div>`;
  const M = S.metrics;
  if (M) {
    const head = '<tr><th>Metric · percentile</th>' + M.players.map(p => `<th>${esc(p.short)}${p.is_target ? '<span class="tag">Target</span>' : ''}</th>`).join('') + '</tr>';
    const body = M.sections.map(sec => `<tr class="sec"><td colspan="${M.players.length + 1}">${esc(sec.name)}</td></tr>`
      + sec.rows.map(r => `<tr><td>${esc(r.label)}</td>` + r.cells.map(x =>
        `<td class="${x.best ? 'best' : ''}">${x.pct == null ? '—' : `<b style="color:${pcol(x.pct)}">${x.pct}</b>`}</td>`).join('') + '</tr>').join('')).join('');
    h += `<details><summary>Every metric, player by player</summary><div class="tw" style="margin-top:8px"><table><thead>${head}</thead><tbody>${body}</tbody></table></div></details>`;
  }
  box.innerHTML = h;
  bindSquad();
}

function bindSquad() {
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
async function loadCard({squad = true} = {}) {
  const mine = ++cardReq;
  const url = `/api/card/${KEY}${query({rank_as: state.rank_as, money: state.money})}`;
  // The squad section is its own request and needs nothing from the card's answer (the
  // server resolves the lens the same way), so both are asked for at once.
  if (squad) loadSquad();
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
  else if (from !== '/players') $('back').textContent = '← Back';
  setSwitch();
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
    setSwitch();
    loadCard();
  });
  loadCard();
}
init();
