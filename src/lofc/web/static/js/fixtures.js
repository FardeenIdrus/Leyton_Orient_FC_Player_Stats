// Fixtures page (owner 2026-11-27, phase 5): which games to watch, which players in them, and
// why. Fetches /api/fixtures and draws it; every fact (form, rising, breaking through, ratings,
// reports) comes from the server -- this file only filters, orders and shows.
//   Nothing is hidden by default; a filter always says how many games it hides.
//   Filters in different groups must all be true of the SAME player; ticks in a group are
//   alternatives. Scout priorities are always listed inside an open game, filters or not.
import {api, esc} from './common.js';

const $ = id => document.getElementById(id);
const PRI = ['Sign', 'Monitor Priority'];
const VIEWS = [
  ['all', 'All games', 'everything', () => true],
  ['pri', 'Scout priorities', 'Sign, Monitor Priority or scouts disagree', p => p.pri || p.dis],
  ['form', 'In form', 'Top in 3+ of last 5 or 6+ of last 10', p => p.f5 || p.f10],
  ['rise', 'Rising', 'last 5 games average 20+ points above the 5 before', p => p.rise],
  ['br', 'Breaking through', 'under 23, minutes doubled to 200+ in 5 games', p => p.br && p.br.on],
  ['ns', 'Not seen yet', 'Overall 3.5+ in his league, never scouted', p => p.ns],
  ['watch', 'Watchlist', 'on the watchlist', p => !!p.watch],
];
let D = null, win = '7', view = 'all', by = 'game';
const open = new Set(), showAll = new Set();

const when = s => new Date(s + (s.endsWith('Z') ? '' : 'Z'));
const day = d => d.toLocaleDateString('en-GB', {weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Europe/London'});
const dShort = d => d.toLocaleDateString('en-GB', {weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Europe/London'});
const hhmm = d => d.toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit', timeZone: 'Europe/London'});
const sDate = s => s ? new Date(s + 'T00:00:00Z').toLocaleDateString('en-GB', {day: 'numeric', month: 'short', timeZone: 'UTC'}) : '';
const club = n => String(n || '').replace(/\b(A?FC)\b/g, '').replace(/\s+/g, ' ').trim();
const ord = n => n + (n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[n % 10] || 'th'));
const lvl = p => p == null ? 'N' : p > 80 ? 'T' : p < 20 ? 'L' : 'A';
const sqName = id => (D.squads[String(id)] || {}).name;
// his player page, opened from Fixtures (the card's back link returns here)
const href = p => `/player/${encodeURIComponent(p.id)}/${p.lg}/${D.season}?back=${encodeURIComponent('/fixtures')}`;

function filt() {
  const g = n => [...document.querySelectorAll(`[data-g="${n}"] input:checked`)].map(i => i.value).filter(Boolean);
  return {verdict: g('verdict'), form: g('form'), ov: +(g('ov')[0] || 0), age: +(g('age')[0] || 0), pos: g('pos'),
    watch: g('watch').length > 0, least: +(g('least')[0] || 1)};
}
const nOn = F => F.verdict.length + F.form.length + (F.ov ? 1 : 0) + (F.age ? 1 : 0) + F.pos.length + (F.watch ? 1 : 0) + (F.least > 1 ? 1 : 0);
const playerFilterOn = F => view !== 'all' || nOn(F) - (F.least > 1 ? 1 : 0) > 0;
function playerOk(p, F, v = view) {
  if (!VIEWS.find(x => x[0] === v)[3](p)) return false;
  if (F.verdict.length && !F.verdict.some(x => x === 'disagree' ? p.dis : x === 'none' ? !p.seen : p.rep.some(r => r.v === x))) return false;
  if (F.form.length && !F.form.some(k => k === 'br' ? p.br && p.br.on : p[k])) return false;
  if (F.ov && !(p.ov != null && p.ov >= F.ov)) return false;
  if (F.age && !(p.age != null && p.age < F.age)) return false;
  if (F.pos.length && !F.pos.includes(p.pos)) return false;
  if (F.watch && !p.watch) return false;
  return true;
}
// a player's reasons, strongest first (the Excel says the same: api/fixtures.why)
function why(p) {
  const w = [];
  // [class, label, what it means (hover)]
  if (p.watch) w.push(['pri', `Watchlist: ${p.watch}`, 'On the watchlist at this stage']);
  const pr = p.rep.find(r => PRI.includes(r.v));
  if (pr) w.push(['pri', pr.d ? `${pr.v} (${sDate(pr.d)})` : pr.v, 'A scout report with this verdict; every report is listed on the right']);
  if (p.dis) w.push(['dis', 'Scouts disagree', 'One report says Sign or Monitor Priority, another Don\'t sign']);
  if (p.f5) w.push(['form', `Top in ${p.t5} of last 5`, 'Top = better than 80% of games at his position in his league (club Overall per game, 45+ min)']);
  else if (p.f10) w.push(['form', `Top in ${p.t10} of last 10`, 'Top = better than 80% of games at his position in his league (club Overall per game, 45+ min)']);
  if (p.rise) w.push(['form', `Rising: avg ${p.rise_from}% → ${p.rise_to}%`, `His average "better than %" over his last 5 games (${p.rise_to}%) against the 5 before (${p.rise_from}%): up ${p.rise_by} points`]);
  if (p.br && p.br.on) w.push(['br', `Breaking through: ${p.br.before} → ${p.br.after} min`, `Under 23. Minutes in his club's last 5 games (${p.br.after}) against the 5 before (${p.br.before})`]);
  if (p.ns) w.push(['new', 'Not seen yet', 'Season Overall 3.5+ in his own league and no scout report']);
  if (p.sug && p.sug.length) w.push(['mu', 'Possible report', 'A scout report that may be about him is not linked to him yet']);
  return w;
}
const weight = p => (p.watch ? 8 : 0) + (p.pri ? 6 : 0) + (p.dis ? 3 : 0) + (p.f5 || p.f10 ? 2 : 0) + (p.rise ? 2 : 0)
  + (p.br && p.br.on ? 2 : 0) + (p.ns ? 2 : 0);
const isKey = p => p.pri || !!p.watch;
const dots = f => f.length ? `<div class="fx-dots" aria-label="Last 5 games">${f.slice(-5).map(x =>
  `<span class="fx-dot ${lvl(x)}" title="${x == null ? 'under 45 min' : 'better than ' + x + '%'}"></span>`).join('')}</div>` : '<span class="note">no game data</span>';

function gamesFor(F, v = view) {
  const q = $('fx-q').value.trim().toLowerCase(), lg = $('fx-lg').value, reg = $('fx-region').value;
  const on = v !== 'all' || nOn(F) - (F.least > 1 ? 1 : 0) > 0;
  return D.games.map(g => {
    const all = Object.entries(D.players).filter(([, p]) => p.sq === g.hs || p.sq === g.as)
      .map(([id, p]) => ({...p, id, side: p.sq === g.hs ? g.home : g.away}));
    const match = (on ? all.filter(p => playerOk(p, F, v)) : all.filter(p => why(p).length))
      .sort((a, b) => weight(b) - weight(a) || (b.ov || 0) - (a.ov || 0));
    return {g, all, match, on};
  }).filter(x => (!x.on || x.match.length >= F.least)
    && (!lg || x.g.lg === lg)
    && (!reg || x.g.region.includes(reg) || x.g.region.some(r => r == null))
    && (!q || `${x.g.home} ${x.g.away} ${x.all.map(p => p.n).join(' ')}`.toLowerCase().includes(q))
    && (!$('fx-mine').checked || x.g.assigned === D.me)
    && (!$('fx-free').checked || !x.g.assigned));
}

function draw() {
  if (!D) return;
  const F = filt(), past = win === 'past';
  $('fx-more-n').textContent = nOn(F) ? `(${nOn(F)} on)` : '';
  $('fx-views').hidden = past;
  if (!past) $('fx-views').innerHTML = VIEWS.map(([k, l, d]) => {
    const n = gamesFor(F, k).length;
    return `<button type="button" class="fx-view" data-v="${k}" aria-pressed="${k === view}" title="${esc(d)}"><b>${n}</b>${esc(l)}<span>${esc(d)}</span></button>`;
  }).join('');
  const rows = gamesFor(F, past ? 'all' : view);
  const total = D.games.length, hidden = total - rows.length;
  $('fx-summary').textContent = past
    ? `Past 3 weeks: ${total} games, ${D.games.filter(g => (g.reports || []).length).length} with scout reports`
    : `Next ${win} days: ${total} games`;
  const filtered = hidden || view !== 'all' || nOn(F) || $('fx-q').value || $('fx-lg').value || $('fx-region').value || $('fx-mine').checked || $('fx-free').checked;
  $('fx-status').innerHTML = `<span>Showing <b>${rows.length}</b> of ${total} games${hidden ? `, <b>${hidden}</b> hidden by filters` : ''}</span>`
    + (filtered ? '<button type="button" class="fx-link" id="fx-clear">Clear filters</button>' : '');
  $('fx-xl').href = `/api/fixtures/xlsx?win=${win}&keys=${encodeURIComponent(rows.map(r => r.g.key).join(','))}`;
  $('fx-by-f').hidden = past;
  if (by === 'player' && !past) return drawPlayers(rows);
  if (!rows.length) { $('fx-list').innerHTML = `<p class="note">${total ? 'No games match. Clear a filter to see more.' : 'No games in this window.'}</p>`; return; }
  rows.sort((a, b) => past ? when(b.g.at) - when(a.g.at) : when(a.g.at) - when(b.g.at));
  const days = [];
  for (const r of rows) { const d = day(when(r.g.at)); let x = days.find(y => y.d === d); if (!x) days.push(x = {d, rows: []}); x.rows.push(r); }
  if ($('fx-sort').value === 'most' && !past) for (const x of days) x.rows.sort((a, b) => b.match.length - a.match.length || when(a.g.at) - when(b.g.at));
  $('fx-list').innerHTML = days.map(x => `<div class="fx-day"><span>${esc(x.d)}</span><span>${x.rows.length} game${x.rows.length > 1 ? 's' : ''}</span></div>`
    + `<div class="tw"><table class="fx-t"><tbody>${x.rows.map(r => past ? pastRow(r) : gameRow(r)).join('')}</tbody></table></div>`).join('');
}

function counts(r) {
  const c = (cls, n, l) => n ? `<span class="fx-cnt ${cls}"><b>${n}</b> ${l}</span>` : '';
  const a = r.all, reps = a.reduce((s, p) => s + p.rep.length, 0);
  return c('pri', a.filter(p => p.pri).length, 'Sign / MP') + c('dis', a.filter(p => p.dis).length, 'disagree')
    + c('form', a.filter(p => p.f5 || p.f10).length, 'in form') + c('form', a.filter(p => p.rise).length, 'rising')
    + c('br', a.filter(p => p.br && p.br.on).length, 'breaking through') + c('new', a.filter(p => p.ns).length, 'not seen')
    + c('', reps, reps === 1 ? 'report' : 'reports');
}
function assignCell(g) {
  const name = (D.users.find(u => u.id === g.assigned) || {}).name;
  if (!D.can_assign) return name ? `<span class="fx-as">${esc(name)}</span>` : '<span class="note">Not assigned</span>';
  return `<select class="ctl fx-assign" data-as="${esc(g.key)}" aria-label="Assign a scout to ${esc(club(g.home))} v ${esc(club(g.away))}">`
    + `<option value="">Not assigned</option>${D.users.map(u => `<option value="${u.id}"${u.id === g.assigned ? ' selected' : ''}>${esc(u.name)}</option>`).join('')}</select>`;
}
function where(g) {
  const reg = [...new Set(g.region.map(r => r || 'Region unknown'))].join(' / ');
  return `${esc(g.lg)}${g.manual ? ' (added by hand)' : ''} · ${esc(reg)}`;
}
function gameRow(r) {
  const g = r.g, o = open.has(g.key), t = when(g.at);
  const top = r.match.slice(0, 3).map(p => `<a class="fx-pl" href="${href(p)}"><b>${esc(p.n)}</b></a> ${esc((why(p)[0] || ['', p.pos])[1])}`).join(' · ');
  const more = r.match.length > 3 ? ` · +${r.match.length - 3} more` : '';
  let h = `<tr class="fx-row${o ? ' open' : ''}" data-k="${esc(g.key)}" tabindex="0" aria-expanded="${o}">`
    + `<td class="fx-time">${hhmm(t)}</td>`
    + `<td class="fx-game"><div><span class="fx-chev" aria-hidden="true">›</span><b>${esc(club(g.home))}</b> v <b>${esc(club(g.away))}</b></div>`
    + `<div class="fx-where">${where(g)}</div>`
    + `<div class="fx-who">${top ? (r.on ? 'Matching: ' : 'Watch: ') + top + more : 'No one flagged'}</div></td>`
    + `<td class="fx-counts">${counts(r) || '<span class="note">—</span>'}</td>`
    + `<td class="fx-assign-c">${assignCell(g)}</td></tr>`;
  if (o) h += `<tr class="fx-open"><td colspan="4">${gameBody(r)}</td></tr>`;
  return h;
}
function playerRow(p, out = false, next = null) {
  const w = why(p);
  const hist = p.rep.length ? p.rep.map(x => `<b>${esc(x.v || '—')}</b> ${esc(sDate(x.d))}${x.s ? ` (${esc(x.s)})` : ''}`).join('<br>') : '<span class="note">Never scouted</span>';
  const sug = (p.sug || []).map(s => `<div class="fx-sug">Possible report: <b>${esc(s.name)}</b>, ${esc(s.club)}, ${esc(s.v || '—')} ${esc(sDate(s.d))}`
    + (D.can_assign ? ` <button type="button" class="fx-link" data-link="${esc(s.sid)}" data-pid="${esc(p.id)}">Link</button>` : '') + '</div>').join('');
  return `<tr class="${out ? 'out' : ''}"><td class="fx-nm"><a href="${href(p)}" class="fx-pl"><b>${esc(p.n)}</b></a>`
    + `<div>${esc(club(p.side || sqName(p.sq)))} · ${esc(p.pos || '—')}${p.age != null ? ' · ' + p.age : ''}</div></td>`
    + `<td>${w.map(([c, t, d]) => `<span class="fx-why ${c}" title="${esc(d)}">${esc(t)}</span>`).join('') || '<span class="note">—</span>'}${out ? '<div class="note">outside your filters</div>' : ''}</td>`
    + `<td>${dots(p.f)}</td>`
    + `<td>${p.ov != null ? `${p.ov.toFixed(2)}<div class="note">${ord(p.rk)} of ${p.of} at position</div>` : '<span class="note">not rated</span>'}</td>`
    + (next ? `<td>${next}</td>` : '') + `<td class="fx-hist">${hist}${sug}</td></tr>`;
}
const HEAD = next => `<table class="fx-ps"><thead><tr><th>Player</th><th>Why watch</th><th>Last 5 games</th><th>Season Overall</th>${next ? '<th>Next game</th>' : ''}<th>Scout reports</th></tr></thead><tbody>`;
function gameBody(r) {
  const shown = new Set(r.match.map(p => p.id));
  const keyOut = r.all.filter(p => isKey(p) && !shown.has(p.id));
  let h = `<div class="fx-sub">${r.on ? 'Matching your filters' : 'Worth watching'} (${r.match.length})</div>`;
  h += r.match.length ? HEAD() + r.match.map(p => playerRow(p)).join('') + '</tbody></table>' : '<p class="note">No one.</p>';
  if (keyOut.length) h += `<div class="fx-sub">Also in this game: scout priorities and watchlist (${keyOut.length})</div>${HEAD()}${keyOut.map(p => playerRow(p, true)).join('')}</tbody></table>`;
  const rest = r.all.filter(p => !shown.has(p.id) && !isKey(p)).sort((a, b) => (b.ov || 0) - (a.ov || 0));
  if (showAll.has(r.g.key)) h += `<div class="fx-sub">Everyone else who has played for these clubs this season (${rest.length})</div>${HEAD()}${rest.map(p => playerRow(p)).join('')}</tbody></table>`;
  else if (rest.length) h += `<p><button type="button" class="fx-link" data-all="${esc(r.g.key)}">Show the other ${rest.length} players</button></p>`;
  if (!r.all.length) h += '<p class="note">We hold no players for these clubs.</p>';
  if (r.g.manual && (D.can_assign || r.g.added_by === D.me)) h += `<p><button type="button" class="fx-link" data-rm="${esc(r.g.key.slice(2))}">Remove this game</button></p>`;
  return h;
}
function pastRow(r) {
  const g = r.g, o = open.has(g.key), n = (g.reports || []).length;
  let h = `<tr class="fx-row${o ? ' open' : ''}" data-k="${esc(g.key)}" tabindex="0" aria-expanded="${o}"><td class="fx-time">${hhmm(when(g.at))}</td>`
    + `<td class="fx-game"><div><span class="fx-chev" aria-hidden="true">›</span><b>${esc(club(g.home))}</b> v <b>${esc(club(g.away))}</b></div><div class="fx-where">${where(g)}</div></td>`
    + `<td class="fx-counts">${n ? `<span class="fx-cnt pri"><b>${n}</b> scout report${n > 1 ? 's' : ''}</span>` : '<span class="note">No scout report</span>'}</td>`
    + `<td class="fx-assign-c">${n ? '<a href="/scout-reports" class="fx-link">Open Scout reports</a>' : ''}</td></tr>`;
  if (o) h += `<tr class="fx-open"><td colspan="4">${n ? '<table class="fx-ps"><thead><tr><th>Player reported</th><th>Verdict</th><th>Scout</th></tr></thead><tbody>'
    + g.reports.map(x => `<tr><td class="fx-nm"><b>${esc(x.p)}</b></td><td>${esc(x.v || '—')}</td><td>${esc(x.s || '')}</td></tr>`).join('') + '</tbody></table>'
    : '<p class="note">No scout report for this game.</p>'}</td></tr>`;
  return h;
}
function drawPlayers(rows) {
  const seen = new Map();
  for (const r of [...rows].sort((a, b) => when(a.g.at) - when(b.g.at)))
    for (const p of r.match) if (!seen.has(p.id)) seen.set(p.id, {p, g: r.g});
  const list = [...seen.values()].sort((a, b) => weight(b.p) - weight(a.p) || (b.p.ov || 0) - (a.p.ov || 0));
  if (!list.length) { $('fx-list').innerHTML = '<p class="note">No players match. Clear a filter to see more.</p>'; return; }
  $('fx-list').innerHTML = `<div class="tw">${HEAD(true)}${list.map(({p, g}) => {
    const t = when(g.at), home = p.sq === g.hs, as = (D.users.find(u => u.id === g.assigned) || {}).name;
    return playerRow(p, false, `${dShort(t)} ${hhmm(t)}<div class="note">${home ? 'v ' + esc(club(g.away)) : '@ ' + esc(club(g.home))}${as ? ' · ' + esc(as) : ''}</div>`);
  }).join('')}</tbody></table></div>`;
}

function fillSelects() {
  const keep = (id, vals, first) => { const el = $(id), cur = el.value;
    el.innerHTML = `<option value="">${first}</option>` + vals.map(v => `<option${v === cur ? ' selected' : ''}>${esc(v)}</option>`).join(''); };
  keep('fx-lg', [...new Set(D.games.map(g => g.lg))].sort(), 'All UK &amp; Irish');
  keep('fx-region', D.regions, 'All regions');
  const posCur = new Set([...document.querySelectorAll('#fx-pos input:checked')].map(i => i.value));
  $('fx-pos').innerHTML = [...new Set(Object.values(D.players).map(p => p.pos).filter(Boolean))].sort()
    .map(p => `<label><input type="checkbox" value="${esc(p)}"${posCur.has(p) ? ' checked' : ''}>${esc(p)}</label>`).join('');
  $('fx-clubs').innerHTML = D.clubs.map(c => `<option value="${esc(c.name)}">${esc(c.lg)}</option>`).join('');
}
async function load() {
  $('fx-list').innerHTML = '<p class="note">Loading…</p>';
  try { D = await api(`/api/fixtures?win=${win}`); }
  catch (e) { $('fx-list').innerHTML = `<p class="note">Could not load the games (${esc(e.message)}).</p>`; return; }
  open.clear(); showAll.clear();
  fillSelects();
  if (win !== 'past') { const r = gamesFor(filt()).sort((a, b) => b.match.length - a.match.length)[0]; if (r) open.add(r.g.key); }
  draw();
}

// ---- wiring ----
const toggle = k => { open.has(k) ? open.delete(k) : open.add(k); draw(); };
$('fx-list').addEventListener('click', async e => {
  const a = e.target.closest('[data-all]'); if (a) { showAll.add(a.dataset.all); draw(); return; }
  const l = e.target.closest('[data-link]');
  if (l) { l.disabled = true; try { await api('/api/fixtures/link', {json: {submission_id: l.dataset.link, player_id: +l.dataset.pid}}); await load(); } catch (err) { l.textContent = 'Could not link'; } return; }
  const rm = e.target.closest('[data-rm]');
  if (rm) { try { await api(`/api/fixtures/games/${rm.dataset.rm}/remove`, {json: {}}); await load(); } catch { rm.textContent = 'Could not remove'; } return; }
  if (e.target.closest('select,a,button,input')) return;
  const tr = e.target.closest('tr.fx-row'); if (tr) toggle(tr.dataset.k);
});
$('fx-list').addEventListener('keydown', e => {
  const tr = e.target.closest && e.target.closest('tr.fx-row');
  if (tr && e.target === tr && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); toggle(tr.dataset.k); }
});
$('fx-list').addEventListener('change', async e => {
  const s = e.target.closest('[data-as]'); if (!s) return;
  const g = D.games.find(x => x.key === s.dataset.as);
  try { await api('/api/fixtures/assign', {json: {key: s.dataset.as, user_id: s.value ? +s.value : null}}); g.assigned = s.value ? +s.value : null; }
  catch { s.value = g.assigned || ''; }
  if ($('fx-mine').checked || $('fx-free').checked) draw();
});
$('fx-views').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { view = b.dataset.v; draw(); } });
$('fx-win').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; win = b.dataset.w;
  for (const x of $('fx-win').querySelectorAll('button')) x.setAttribute('aria-pressed', String(x === b)); load(); });
$('fx-by').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; by = b.dataset.b;
  for (const x of $('fx-by').querySelectorAll('button')) x.setAttribute('aria-pressed', String(x === b)); draw(); });
$('fx-filters').addEventListener('input', e => { if (e.target.closest('#fx-more,#fx-q,#fx-lg,#fx-region,#fx-sort,#fx-mine,#fx-free')) draw(); });
$('fx-filters').addEventListener('click', e => {
  if (e.target.id !== 'fx-clear') return;
  view = 'all';
  for (const id of ['fx-q', 'fx-lg', 'fx-region']) $(id).value = '';
  $('fx-mine').checked = $('fx-free').checked = false;
  for (const i of document.querySelectorAll('#fx-more input')) i.checked = i.type === 'radio' && (i.value === '' || (i.name === 'fx-least' && i.value === '1'));
  draw();
});
// add a game by hand
const clubId = name => (D.clubs.find(c => c.name === name) || {}).id ?? null;
$('fx-add-open').addEventListener('click', () => { $('fx-add').hidden = false; $('fx-add-date').focus(); });
$('fx-add-cancel').addEventListener('click', () => { $('fx-add').hidden = true; });
$('fx-add').addEventListener('submit', async e => {
  e.preventDefault();
  const home = $('fx-add-home').value.trim(), away = $('fx-add-away').value.trim();
  try {
    await api('/api/fixtures/games', {json: {date: $('fx-add-date').value, time: $('fx-add-time').value, competition: $('fx-add-comp').value,
      home: {name: home, id: clubId(home)}, away: {name: away, id: clubId(away)}}});
    $('fx-add').reset(); $('fx-add').hidden = true; await load();
  } catch (err) { $('fx-add-msg').textContent = (err.body && err.body.detail) || 'Could not add the game.'; }
});
load();
