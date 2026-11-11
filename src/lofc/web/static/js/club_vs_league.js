// Club vs League One: draws /api/club-vs-league. Every figure comes from the API
// (lofc.core.club_vs_league over the stored ratings); this page computes nothing.
import {api, esc, chip, fmtInt} from './common.js';
import {ord, pct, loadLeagues, saveLeagues, pickLeagues, pickerText} from './club_vs_league_rules.js';

const $ = id => document.getElementById(id);
const KEYS = ['group', 'age', 'contract', 'league', 'strong', 'top6', 'sort'];
let D = null;
const st = () => { const q = new URLSearchParams(location.search), s = {}; for (const k of KEYS) s[k] = q.get(k) || ''; return s; };
const two = v => v == null ? '—' : (+v).toFixed(2);
let STORE = null;
try { STORE = window.localStorage; } catch (e) { STORE = null; }
const OPEN = new Set();          // gap-map rows the user has open (first row open by default)
let openInit = false;
// sort: '' = Overall (the ranking); 'vb' = vs our best; 'w0'..'w2' = a weakness column.
// Highest first; a leading '-' = lowest first. Missing figures always last.
const sortVal = (r, key) => key === 'vb' ? r.vs_best : r.weak[+key.slice(1)];
function sorted(rows, key) {
  const k = (key || '').replace(/^-/, ''), dir = key && key[0] === '-' ? 1 : -1;
  const pairs = rows.map((r, i) => [r, i]);
  if (!k) return pairs;
  return pairs.sort((a, b) => {
    const x = sortVal(a[0], k), y = sortVal(b[0], k);
    if (x == null || y == null) return (x == null) - (y == null) || a[1] - b[1];
    return (x - y) * dir || a[1] - b[1];
  });
}
const vsCell = v => v == null ? '<span class="note">—</span>'
  : `<span class="vs ${v > 0 ? 'up' : v < 0 ? 'dn' : ''}">${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(2)}</span>`;

// owner 2026-11-10: a player opened here comes back to "Players who could close the gap" with
// every filter still set -- the filters live in this page's address, so the way back carries it
const backQ = () => '?back=' + encodeURIComponent('/club-vs-league' + location.search + '#cv-rec');

function commit(patch, refetch = true) {
  const q = new URLSearchParams(location.search);
  for (const [k, v] of Object.entries(patch)) v ? q.set(k, v) : q.delete(k);
  history.pushState({}, '', '/club-vs-league' + (q.toString() ? '?' + q : ''));
  return refetch ? load() : drawRec();
}

function rankCell(r) {
  if (!r) return '<td class="n">—</td>';
  const cls = r.rank <= 6 ? 'good' : r.rank > r.of - 6 ? 'bad' : '';
  return `<td class="n"><span class="cv-rk ${cls}">${ord(r.rank)}</span></td>`;
}

const clubRow = (t, n, us) => `<tr${us ? ' class="us"' : ''}><td class="n${us ? '' : ' note'}">${n}</td><td class="cv-who">${esc(t.club)}</td><td class="n">${t.players}</td>`
  + `<td class="c">${chip(t.avg)}</td><td class="c">${chip(t.performance)}</td><td class="c">${chip(t.physical)}</td></tr>`;

function bigTable(rows) {
  let last = null, body = '';
  for (const b of rows) {
    if (b.section !== last) { last = b.section; body += `<tr class="sec"><td colspan="3">${esc(b.section)}</td></tr>`; }
    body += `<tr><td>${esc(b.label)}</td>${rankCell(b.now)}${rankCell(b.prev)}</tr>`;
  }
  return `<colgroup><col><col class="cv-yr"><col class="cv-yr"></colgroup><thead><tr><th>Measure</th><th class="n">${esc(D.season)}</th><th class="n">${esc(D.prev_season)}</th></tr></thead><tbody>${body}</tbody>`;
}

function drawTop() {
  $('cv-top6-sub').textContent = `League One · ${D.season} · minutes-weighted average of rated players`;
  const us = D.us, inTop = us && D.top6.some(t => t.club === us.club);
  $('cv-top6-t').innerHTML = '<colgroup><col class="cv-c-n"><col><col class="cv-c-w"><col class="cv-c-w"><col class="cv-c-w"><col class="cv-c-w"></colgroup>'
    + '<thead><tr><th class="n">#</th><th>Club</th><th class="n">Rated players</th><th class="c">Overall</th><th class="c">Performance</th><th class="c">Physical</th></tr></thead><tbody>'
    + D.top6.map((t, i) => clubRow(t, i + 1, us && t.club === us.club)).join('')
    + (us && !inTop ? clubRow(us, us.rank, true) : '') + '</tbody>';
  // ratings first, then the measure sections split half and half (owner 2026-11-10)
  const BP = D.big_picture, ratings = BP.filter(b => b.kind === 'rating'), meas = BP.filter(b => b.kind !== 'rating');
  const secs = [...new Set(meas.map(b => b.section))];
  $('cv-big-of').textContent = D.clubs;
  $('cv-big-l').innerHTML = bigTable(ratings.concat(meas.filter(b => b.section === secs[0])));
  $('cv-big-r').innerHTML = bigTable(meas.filter(b => b.section !== secs[0]));
}

// the 4-column shortfall grid: label | Ours | Top 6 | Behind (same columns in the summary row,
// the table head and "Every shortfall", so the figures line up)
const sfRows = list => list.map(x => `<span class="sf-l">${esc(x.label)}</span><span class="n">${pct(x.ours)}</span><span class="n">${pct(x.top6)}</span><span class="n sf-b">${x.short}</span>`).join('');
const gapVal = g => g == null ? '<span class="note">—</span>'
  : `<span class="cv-gapv ${g > 0 ? 'neg' : 'pos'}">${g > 0 ? '−' : '+'}${Math.abs(g).toFixed(2)}</span>`;

function drawGap() {
  if (!openInit && D.gaps.length) { OPEN.add(D.gaps[0].group); openInit = true; }
  const tag = p => p.tag ? `<span class="cv-tag away">${esc(p.tag)}</span>` : '';
  $('cv-gap-t').innerHTML = '<colgroup><col class="g-pos"><col class="g-who"><col class="g-chip"><col class="g-bar"><col class="g-gap"><col></colgroup>'
    + '<thead><tr><th>Position</th><th>Our best</th><th class="c">Ours</th><th class="c">Top-6 bar</th><th class="c">Gap</th>'
    + '<th><div class="cv-sfl cv-sfh"><span>Biggest shortfalls</span><span class="n">Ours</span><span class="n">Top 6</span><span class="n">Behind</span></div></th></tr></thead><tbody>'
    + D.gaps.map(g => {
      const L = g.level, B = g.bar, open = OPEN.has(g.group);
      const sub = p => p.position !== g.group ? `<span class="cv-tag">${esc(p.position)}</span>` : '';
      const top = g.shortfalls.length ? `<div class="cv-sfl">${sfRows(g.shortfalls)}</div>` : '<span class="note">—</span>';
      const ours = g.players.length ? g.players.map(p => `<tr><td>${esc(p.name)}${tag(p)}${sub(p)}</td><td class="n"><b>${p.rating == null ? '—' : two(p.rating)}</b></td></tr>`).join('')
        : `<tr><td colspan="2" class="note">${esc(g.note || '—')}</td></tr>`;
      const bar = B.players.map(p => `<tr><td>${esc(p.player)}${sub(p)}</td><td class="note">${esc(p.club)}</td><td class="n"><b>${two(p.rating)}</b></td></tr>`).join('');
      const all = g.all_shortfalls || [];
      return `<tr class="pos${open ? ' open' : ''}" data-g="${esc(g.group)}" tabindex="0" aria-expanded="${open}" aria-label="${esc(g.group)}: show detail">`
        + `<td><span class="cv-chev" aria-hidden="true">›</span><span class="cv-pos">${esc(g.group)}</span></td>`
        + `<td class="cv-who"${L ? '' : ` title="${esc(g.note)}"`}>${L ? esc(L.name) + sub(L) : '—'}</td><td class="c">${L ? chip(L.rating) : chip(null)}</td>`
        + `<td class="c">${chip(B.median)}</td><td class="c">${gapVal(g.gap)}</td><td>${top}</td></tr>`
        + `<tr class="cv-det" data-d="${esc(g.group)}"${open ? '' : ' hidden'}><td colspan="5"><div class="cv-grid2">`
        + `<table class="cv-dt"><colgroup><col><col class="d-ovr"></colgroup><thead><tr><th>Our players</th><th class="n">Overall</th></tr></thead><tbody>${ours}</tbody></table>`
        + `<div><table class="cv-dt"><colgroup><col class="d-name"><col><col class="d-ovr"></colgroup><thead><tr><th>Top-6 bar</th><th>Club</th><th class="n">Overall</th></tr></thead><tbody>${bar || '<tr><td colspan="3" class="note">—</td></tr>'}</tbody></table>`
        + `${B.fallback && B.label ? `<div class="cv-bar-note">${esc(B.label)}</div>` : ''}</div></div></td>`
        + `<td><div class="cv-sfl cv-sfd"><span class="h">Every shortfall</span><span class="h n">Ours</span><span class="h n">Top 6</span><span class="h n">Behind</span>`
        + `${all.length ? sfRows(all) : '<span class="sf-l note">—</span><span></span><span></span><span></span>'}</div></td></tr>`;
    }).join('') + '</tbody>';
}

function toggleGap(tr) {
  const g = tr.dataset.g, det = tr.nextElementSibling, open = det.hidden;
  det.hidden = !open; tr.classList.toggle('open', open); tr.setAttribute('aria-expanded', String(open));
  open ? OPEN.add(g) : OPEN.delete(g);
  // owner 2026-11-10: opening a position also switches "Players who could close the gap" to it
  if (open && D && g !== D.selected) commit({group: g, league: '', sort: ''});
}

const PL = {'Goalkeeper': 'goalkeepers', 'Centre Back': 'centre backs', 'Full Back': 'full backs', 'Midfield': 'midfielders', 'Winger': 'wingers', 'Centre Forward': 'centre forwards'};
const gapText = g => g == null ? '' : `${g > 0 ? '−' : '+'}${Math.abs(g).toFixed(2)}`;

function drawRec() {
  const s = st(), R = D.recommendations, g = D.gaps.find(x => x.group === D.selected);
  $('cv-group').innerHTML = D.gaps.map(x => `<option value="${esc(x.group)}"${x.group === D.selected ? ' selected' : ''}>${esc(x.group)}${x.gap == null ? '' : ` (gap ${gapText(x.gap)})`}</option>`).join('');
  $('cv-age').innerHTML = D.filters.ages.map(a => `<option value="${esc(a.key)}"${a.key === D.filters.age ? ' selected' : ''}>${esc(a.label === 'All' ? 'Any' : a.label)}</option>`).join('');
  $('cv-contract').innerHTML = '<option value="">Any</option>' + D.filters.contracts.map(c => `<option${c === D.filters.contract ? ' selected' : ''}>${esc(c)}</option>`).join('');
  for (const [id, on] of [['cv-strong', D.filters.strong], ['cv-top6only', D.filters.top6]]) { $(id).classList.toggle('on', on); $(id).setAttribute('aria-checked', String(on)); }
  $('cv-rec-sub').textContent = g.level ? `${D.season} · rated above our best at the position · ranked within each league`
    : `${D.season} · no Orient player rated here this season: the best rated players · ranked within each league`;
  const B = g.bar;
  $('cv-level').innerHTML = `<div class="ours"><span>Our best</span><b>${g.level ? two(g.level.rating) : '—'}</b><span>${esc(g.level ? g.level.name : g.note)}</span></div>`
    + `<div><span>Top-6 bar</span><b>${two(B.median)}</b><span>median of ${B.n} named players${B.fallback ? ` · ${esc(D.prev_season)}` : ''}</span></div>`
    + `<div><span>Gap</span><b class="${g.gap > 0 ? 'neg' : 'pos'}">${g.gap == null ? '—' : gapText(g.gap)}</b><span>&nbsp;</span></div>`;
  const leagues = R.leagues;
  drawPicker(leagues);
  if (!leagues.length) { $('cv-tabs').innerHTML = ''; $('cv-count').textContent = 'No player above our level with these filters.'; $('cv-rec-t').innerHTML = ''; return; }
  const by = new Map(leagues.map(l => [l.competition_id, l]));
  const pick = pickLeagues(leagues.map(l => l.competition_id), STORE && loadLeagues(STORE), s.league, R.default_leagues || []);
  const cur = by.get(pick.active);
  $('cv-tabs').innerHTML = pick.tabs.map(id => by.get(id)).map(l => `<button type="button" role="tab" data-l="${l.competition_id}" class="cv-tab${l === cur ? ' on' : ''}" aria-selected="${l === cur}">${esc(l.league)}<span>${l.count}</span></button>`).join('');
  $('cv-count').innerHTML = `<b>${esc(cur.league)}</b> · top ${cur.rows.length} of ${cur.count} ${PL[D.selected] || ''} above our level`;
  const W = R.weak_metrics || [];
  const valid = ['vb', ...W.map((_, k) => `w${k}`)];
  const key = valid.includes((s.sort || '').replace(/^-/, '')) ? s.sort : '';
  const arrow = k => key === k ? ' ▼' : key === '-' + k ? ' ▲' : '';
  const sortTh = (k, text, tip) => `<th class="c cv-sort${key.replace(/^-/, '') === k ? ' on' : ''}" data-sort="${k}" tabindex="0" role="button" aria-label="Sort by ${esc(text)}"${tip ? ` data-tip="${esc(tip)}"` : ''}>${esc(text)}${arrow(k)}</th>`;
  $('cv-rec-t').innerHTML = '<thead><tr><th class="n">#</th><th>Player</th><th>Club</th><th class="n">Age</th><th class="n">Minutes</th>'
    + `<th class="c cv-sort${key ? '' : ' on'}" data-sort="" tabindex="0" role="button" aria-label="Sort by Overall">Overall${key ? '' : ' ▼'}</th>`
    + sortTh('vb', 'vs our best', D.terms['vs our best']) + '<th class="c">Performance</th><th class="c">Physical</th>'
    + W.map((w, k) => sortTh(`w${k}`, w.label)).join('') + '<th></th></tr></thead><tbody>'
    + sorted(cur.rows, key).map(([r, i]) => `<tr class="click" data-href="${esc(r.href)}"><td class="n note">${i + 1}</td><td><a class="pname" href="${esc(r.href + backQ())}">${esc(r.name)}</a>${r.position !== D.selected ? `<span class="cv-tag">${esc(r.position)}</span>` : ''}${r.top6_level ? `<span class="cv-t6" data-tip="Top-6 level: ${esc(D.terms['Top-6 level'])}">Top-6 level</span>` : ''}</td><td>${esc(r.club)}</td>`
      + `<td class="n">${r.age == null ? '—' : r.age.toFixed(1)}</td><td class="n">${fmtInt(r.minutes)}</td><td class="c">${chip(r.overall)}</td><td class="c">${vsCell(r.vs_best)}</td><td class="c">${chip(r.performance)}</td><td class="c">${chip(r.physical)}</td>`
      + W.map((_, k) => `<td class="c">${pct(r.weak[k])}</td>`).join('')
      + `<td><button type="button" class="cv-star${r.watched ? ' on' : ''}" data-ids="${r.ids.join('/')}" aria-label="${r.watched ? 'On watchlist' : 'Add to watchlist'}: ${esc(r.name)}">${r.watched ? '★' : '☆'}</button></td></tr>`).join('')
    + '</tbody>';
}

// Leagues picker: every league with candidates (England's first, the API's order), with counts.
function drawPicker(leagues) {
  const s = st(), ids = leagues.map(l => l.competition_id);
  const pick = pickLeagues(ids, STORE && loadLeagues(STORE), s.league, (D.recommendations.default_leagues) || []);
  const names = Object.fromEntries(leagues.map(l => [l.competition_id, l.league]));
  const btn = $('cv-leagues');
  btn.textContent = leagues.length ? pickerText(pick.tabs, names) : 'No leagues';
  btn.disabled = !leagues.length;
  if (!$('cv-lp-menu').hidden) return;          // open: keep the user's checkboxes (and focus)
  $('cv-lp-menu').style.setProperty('--rows', Math.ceil(leagues.length / 2));   // read down each column
  $('cv-lp-menu').innerHTML = leagues.map(l => `<label><input type="checkbox" value="${l.competition_id}"${pick.tabs.includes(l.competition_id) ? ' checked' : ''}> <span>${esc(l.league)}</span> <span class="note">${l.count}</span></label>`).join('');
}
function menuOpen(on) {
  $('cv-lp-menu').hidden = !on; $('cv-leagues').setAttribute('aria-expanded', String(on));
}
$('cv-leagues').addEventListener('click', ev => { ev.stopPropagation(); menuOpen($('cv-lp-menu').hidden); });
$('cv-lp-menu').addEventListener('click', ev => ev.stopPropagation());
$('cv-lp-menu').addEventListener('change', ev => {
  const boxes = [...$('cv-lp-menu').querySelectorAll('input')];
  const ids = boxes.filter(b => b.checked).map(b => Number(b.value));
  if (!ids.length) { ev.target.checked = true; return; }          // at least one league
  if (STORE) saveLeagues(STORE, ids);
  const s = st();
  if (s.league && !ids.includes(Number(s.league))) commit({league: ''}, false);
  else drawRec();
  menuOpen(true);
});
document.addEventListener('click', () => menuOpen(false));
document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !$('cv-lp-menu').hidden) { menuOpen(false); $('cv-leagues').focus(); } });

async function load() {
  const s = st(), q = new URLSearchParams();
  for (const k of ['group', 'age', 'contract', 'strong', 'top6']) if (s[k]) q.set(k, s[k]);
  try {
    D = await api('/api/club-vs-league' + (q.toString() ? '?' + q : ''));
  } catch (e) { $('cv-msg').innerHTML = `<div class="notice">Could not load (${esc(e.message)}).</div>`; return; }
  const first = $('cv-body').hidden;
  drawTop(); drawGap(); drawRec();
  $('cv-skel').hidden = true; $('cv-body').hidden = false;
  if (first) $('cv-body').classList.add('fade-in');
  if (first && location.hash === '#cv-rec') $('cv-rec').scrollIntoView({block: 'start'});
}

$('cv-gap-t').addEventListener('click', ev => { const tr = ev.target.closest('tr[data-g]'); if (tr) toggleGap(tr); });
$('cv-gap-t').addEventListener('keydown', ev => { const tr = ev.target.closest('tr[data-g]'); if (tr && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); toggleGap(tr); } });
$('cv-group').addEventListener('change', e => commit({group: e.target.value, league: '', sort: ''}));
$('cv-age').addEventListener('change', e => commit({age: e.target.value}));
$('cv-contract').addEventListener('change', e => commit({contract: e.target.value}));
$('cv-tabs').addEventListener('click', ev => { const t = ev.target.closest('button[data-l]'); if (t) commit({league: t.dataset.l}, false); });
$('cv-rec-t').addEventListener('click', async ev => {
  const th = ev.target.closest('th.cv-sort');
  if (th) return sortBy(th);
  const b = ev.target.closest('.cv-star');
  if (b) {
    ev.stopPropagation();
    const on = b.classList.contains('on');
    b.disabled = true;
    try {
      const r = await api(`/api/card/${b.dataset.ids}/watchlist`, {json: {action: on ? 'remove' : 'add'}});
      b.classList.toggle('on', r.watched); b.textContent = r.watched ? '★' : '☆';
      b.setAttribute('aria-label', (r.watched ? 'On watchlist' : 'Add to watchlist'));
    } catch (e) { $('cv-msg').innerHTML = `<div class="notice">Could not update the watchlist (${esc(e.message)}).</div>`; }
    finally { b.disabled = false; }
    return;
  }
  const tr = ev.target.closest('tr[data-href]');
  if (tr && !ev.target.closest('a')) location.assign(tr.dataset.href + backQ());
});
function sortBy(th) {
  const k = th.dataset.sort, cur = st().sort;
  commit({sort: k === '' ? '' : cur === k ? '-' + k : k}, false);
}
$('cv-rec-t').addEventListener('keydown', ev => { const th = ev.target.closest('th.cv-sort'); if (th && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); sortBy(th); } });
const flipStrong = () => commit({strong: D && D.filters.strong ? '' : '1'});
$('cv-strong').addEventListener('click', flipStrong);
$('cv-strong').addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); flipStrong(); } });
const flipTop6 = () => commit({top6: D && D.filters.top6 ? '' : '1'});
$('cv-top6only').addEventListener('click', flipTop6);
$('cv-top6only').addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); flipTop6(); } });
addEventListener('popstate', load);
load();
