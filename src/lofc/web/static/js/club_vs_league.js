// Club vs League One: draws /api/club-vs-league. Every figure comes from the API
// (lofc.core.club_vs_league over the stored ratings); this page computes nothing.
import {api, esc, chip, fmtInt, dash} from './common.js';

const $ = id => document.getElementById(id);
const KEYS = ['group', 'age', 'contract', 'league', 'strong', 'top6', 'sort'];
let D = null;
const st = () => { const q = new URLSearchParams(location.search), s = {}; for (const k of KEYS) s[k] = q.get(k) || ''; return s; };
const two = v => v == null ? '—' : (+v).toFixed(2);
const ord = n => n + ({1: 'st', 2: 'nd', 3: 'rd'}[(n % 100 >= 11 && n % 100 <= 13) ? 0 : n % 10] || 'th');
// his percentile on one of our weakest areas: green 70+, grey 30-69, red below 30
const pctPill = p => p == null ? '<span class="note">—</span>'
  : `<span class="cv-pp ${p >= 70 ? 'hi' : p >= 30 ? 'mid' : 'lo'}">${ord(p)}</span>`;
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

function commit(patch, refetch = true) {
  const q = new URLSearchParams(location.search);
  for (const [k, v] of Object.entries(patch)) v ? q.set(k, v) : q.delete(k);
  history.pushState({}, '', '/club-vs-league' + (q.toString() ? '?' + q : ''));
  return refetch ? load() : drawRec();
}

function rankCell(r) {
  if (!r) return '<td class="n">—</td>';
  const cls = r.rank <= 6 ? 'good' : r.rank > r.of - 6 ? 'bad' : '';
  return `<td class="n"><span class="cv-rk ${cls}">${esc(r.text.split(' of ')[0])}</span> <span class="note">of ${r.of}</span></td>`;
}

function drawTop() {
  $('cv-top6-sub').textContent = `League One · ${D.season} · we are ${D.orient ? D.orient.text : '—'}`;
  $('cv-top6-t').innerHTML = '<thead><tr><th>#</th><th>Club</th><th class="n">Rated players</th><th class="c">Average Overall</th></tr></thead><tbody>'
    + D.top6.map((t, i) => `<tr><td class="n">${i + 1}</td><td class="cv-who">${esc(t.club)}</td><td class="n">${t.players}</td><td class="c">${chip(t.avg)}</td></tr>`).join('')
    + '</tbody>';
  let last = null, body = '';
  for (const b of D.big_picture) {
    if (b.section !== last) { last = b.section; body += `<tr class="sec"><td colspan="3">${esc(b.section)}</td></tr>`; }
    body += `<tr><td>${esc(b.label)}${b.measure.endsWith('_p90') ? ' <span class="note">per 90</span>' : ''}</td>${rankCell(b.now)}${rankCell(b.prev)}</tr>`;
  }
  $('cv-big-t').innerHTML = `<thead><tr><th>Measure</th><th class="n">${esc(D.season)}</th><th class="n">${esc(D.prev_season)}</th></tr></thead><tbody>${body}</tbody>`;
}

function drawGap() {
  const s = st(), sel = D.selected;
  $('cv-gap-t').innerHTML = '<thead><tr><th>Position</th><th>Our level</th><th class="c">Ours</th><th>Top-6 bar</th><th>Gap</th><th>Where it comes from</th></tr></thead><tbody>'
    + D.gaps.map(g => {
      const L = g.level, B = g.bar;
      const others = g.players.filter(p => !L || p.player_id !== L.player_id);
      const tag = p => p.tag ? `<span class="cv-tag away">${esc(p.tag)}</span>` : '';
      const sub = p => p.position !== g.group ? `<span class="cv-tag">${esc(p.position)}</span>` : '';
      const also = others.length ? `<div class="cv-also">${others.map(p => `<div>${esc(p.name)} <b>${p.rating == null ? '—' : two(p.rating)}</b>${tag(p)}${sub(p)}</div>`).join('')}</div>` : '';
      const who = L ? `<div class="cv-who">${esc(L.name)}${sub(L)}</div><div class="note">${fmtInt(L.minutes)} min</div>${also}`
        : `<div class="note">${esc(g.note)}</div>${also}`;
      const named = B.players.length ? `<div class="cv-named">${B.players.map(p => `<div><b>${two(p.rating)}</b> ${esc(p.player)} <span>${esc(p.club)}</span></div>`).join('')}</div>` : '';
      const bar = B.median == null ? '—' : `${chip(B.median)}<div class="note">${B.n} of ${B.of} clubs</div>`;
      const gap = g.gap == null ? '<span class="note">—</span>'
        : `<span class="cv-gapv ${g.gap > 0 ? 'neg' : 'pos'}">${g.gap > 0 ? '−' : '+'}${Math.abs(g.gap).toFixed(2)}</span>`
          + (g.gap > 0 ? `<div class="cv-gapbar"><i style="width:${Math.min(100, g.gap / 1.5 * 100)}%"></i></div>` : '');
      const all = g.all_shortfalls || [];
      const more = all.length ? `<details class="cv-all"><summary>Show all (${all.length})</summary><table><thead><tr><th>Metric</th><th class="n">Ours</th><th class="n">Top-6</th><th class="n">Short</th></tr></thead><tbody>`
        + all.map(x => `<tr><td>${esc(x.label)}</td><td class="n">${ord(x.ours)}</td><td class="n">${ord(x.top6)}</td><td class="n">${x.short}</td></tr>`).join('') + '</tbody></table></details>' : '';
      const why = g.shortfalls.length ? `<div class="cv-why">${g.shortfalls.map(x => `<div>${esc(x.text)}</div>`).join('')}</div>${more}` : '<span class="note">—</span>';
      return `<tr class="pos${g.group === sel ? ' on' : ''}" data-g="${esc(g.group)}" tabindex="0" aria-label="Show players above our level at ${esc(g.group)}">`
        + `<td><span class="cv-pos">${esc(g.group)}</span></td><td>${who}</td><td class="c">${L ? chip(L.rating) : '—'}</td>`
        + `<td class="cv-barc">${bar}${B.label ? `<div class="cv-bar-note">${esc(B.label)}</div>` : ''}${named}</td><td>${gap}</td><td>${why}</td></tr>`;
    }).join('') + '</tbody>';
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
  if (!leagues.length) { $('cv-tabs').innerHTML = ''; $('cv-count').textContent = 'No player above our level with these filters.'; $('cv-rec-t').innerHTML = ''; return; }
  const main = leagues.filter(l => [4, 3, 5].includes(l.competition_id));
  const more = leagues.filter(l => ![4, 3, 5].includes(l.competition_id));
  const cur = leagues.find(l => String(l.competition_id) === s.league) || main[0] || leagues[0];
  $('cv-tabs').innerHTML = main.map(l => `<button type="button" role="tab" data-l="${l.competition_id}" class="cv-tab${l === cur ? ' on' : ''}" aria-selected="${l === cur}">${esc(l.league)}<span>${l.count}</span></button>`).join('')
    + (more.length ? `<label class="cv-more${more.includes(cur) ? ' on' : ''}"><select id="cv-more" aria-label="More leagues"><option value="">+ More leagues</option>${more.map(l => `<option value="${l.competition_id}"${l === cur ? ' selected' : ''}>${esc(l.league)} (${l.count})</option>`).join('')}</select></label>` : '');
  $('cv-count').textContent = `Top ${cur.rows.length} of ${cur.count} ${PL[D.selected] || ''} above our level · ranked within ${cur.league}`;
  const W = R.weak_metrics || [];
  const valid = ['vb', ...W.map((_, k) => `w${k}`)];
  const key = valid.includes((s.sort || '').replace(/^-/, '')) ? s.sort : '';
  const arrow = k => key === k ? ' ▼' : key === '-' + k ? ' ▲' : '';
  const sortTh = (k, text, tip) => `<th class="c cv-sort${key.replace(/^-/, '') === k ? ' on' : ''}" data-sort="${k}" tabindex="0" role="button" aria-label="Sort by ${esc(text)}"${tip ? ` data-tip="${esc(tip)}"` : ''}>${esc(text)}${arrow(k)}</th>`;
  $('cv-rec-t').innerHTML = '<thead><tr><th class="n">#</th><th>Player</th><th>Club</th><th class="n">Age</th><th class="n">Minutes</th>'
    + `<th class="c cv-sort${key ? '' : ' on'}" data-sort="" tabindex="0" role="button" aria-label="Sort by Overall">Overall${key ? '' : ' ▼'}</th>`
    + sortTh('vb', 'vs our best', D.terms['vs our best']) + '<th class="c">Performance</th><th class="c">Physical</th>'
    + W.map((w, k) => sortTh(`w${k}`, w.label)).join('') + '<th></th></tr></thead><tbody>'
    + sorted(cur.rows, key).map(([r, i]) => `<tr class="click" data-href="${esc(r.href)}"><td class="n note">${i + 1}</td><td><a class="pname" href="${esc(r.href)}">${esc(r.name)}</a>${r.position !== D.selected ? `<span class="cv-tag">${esc(r.position)}</span>` : ''}${r.top6_level ? `<span class="cv-t6" data-tip="Top-6 level: ${esc(D.terms['Top-6 level'])}">Top-6 level</span>` : ''}</td><td>${esc(r.club)}</td>`
      + `<td class="n">${r.age == null ? '—' : r.age.toFixed(1)}</td><td class="n">${fmtInt(r.minutes)}</td><td class="c">${chip(r.overall)}</td><td class="c">${vsCell(r.vs_best)}</td><td class="c">${chip(r.performance)}</td><td class="c">${chip(r.physical)}</td>`
      + W.map((_, k) => `<td class="c">${pctPill(r.weak[k])}</td>`).join('')
      + `<td><button type="button" class="cv-star${r.watched ? ' on' : ''}" data-ids="${r.ids.join('/')}" aria-label="${r.watched ? 'On watchlist' : 'Add to watchlist'}: ${esc(r.name)}">${r.watched ? '★' : '☆'}</button></td></tr>`).join('')
    + '</tbody>';
}

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
}

$('cv-gap-t').addEventListener('click', ev => { if (ev.target.closest('.cv-all')) return; const tr = ev.target.closest('tr[data-g]'); if (tr) commit({group: tr.dataset.g, league: '', sort: ''}).then(() => $('cv-rec').scrollIntoView({behavior: 'smooth', block: 'start'})); });
$('cv-gap-t').addEventListener('keydown', ev => { if (ev.target.closest('.cv-all')) return; const tr = ev.target.closest('tr[data-g]'); if (tr && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); commit({group: tr.dataset.g, league: '', sort: ''}); } });
$('cv-group').addEventListener('change', e => commit({group: e.target.value, league: '', sort: ''}));
$('cv-age').addEventListener('change', e => commit({age: e.target.value}));
$('cv-contract').addEventListener('change', e => commit({contract: e.target.value}));
$('cv-tabs').addEventListener('click', ev => { const t = ev.target.closest('button[data-l]'); if (t) commit({league: t.dataset.l}, false); });
$('cv-tabs').addEventListener('change', ev => { if (ev.target.id === 'cv-more' && ev.target.value) commit({league: ev.target.value}, false); });
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
  if (tr && !ev.target.closest('a')) location.assign(tr.dataset.href + '?back=' + encodeURIComponent(location.pathname + location.search));
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
