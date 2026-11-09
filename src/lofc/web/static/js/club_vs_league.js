// Club vs League One: draws /api/club-vs-league. Every figure comes from the API
// (lofc.core.club_vs_league over the stored ratings); this page computes nothing.
import {api, esc, chip, fmtInt, dash} from './common.js';

const $ = id => document.getElementById(id);
const KEYS = ['group', 'age', 'contract', 'league', 'strong'];
let D = null;
const st = () => { const q = new URLSearchParams(location.search), s = {}; for (const k of KEYS) s[k] = q.get(k) || ''; return s; };
const two = v => v == null ? '—' : (+v).toFixed(2);

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
      const why = g.shortfalls.length ? `<div class="cv-why">${g.shortfalls.map(x => `<div>${esc(x.text)}</div>`).join('')}</div>` : '<span class="note">—</span>';
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
  $('cv-strong').classList.toggle('on', D.filters.strong); $('cv-strong').setAttribute('aria-checked', String(D.filters.strong));
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
  $('cv-rec-t').innerHTML = '<thead><tr><th class="n">#</th><th>Player</th><th>Club</th><th class="n">Age</th><th class="n">Minutes</th><th class="c">Overall</th><th class="c">Performance</th><th class="c">Physical</th><th>Strong where we are weak</th><th></th></tr></thead><tbody>'
    + cur.rows.map((r, i) => `<tr class="click" data-href="${esc(r.href)}"><td class="n note">${i + 1}</td><td><a class="pname" href="${esc(r.href)}">${esc(r.name)}</a>${r.position !== D.selected ? `<span class="cv-tag">${esc(r.position)}</span>` : ''}${r.top6_level ? '<span class="cv-t6" data-tip="Top-6 level: ${esc(D.terms['Top-6 level'])}">Top-6 level</span>' : ''}</td><td>${esc(r.club)}</td>`
      + `<td class="n">${r.age == null ? '—' : r.age.toFixed(1)}</td><td class="n">${fmtInt(r.minutes)}</td><td class="c">${chip(r.overall)}</td><td class="c">${chip(r.performance)}</td><td class="c">${chip(r.physical)}</td>`
      + `<td>${r.tags.map(t => `<span class="cv-str">${esc(t)}</span>`).join('')}</td>`
      + `<td><button type="button" class="cv-star${r.watched ? ' on' : ''}" data-ids="${r.ids.join('/')}" aria-label="${r.watched ? 'On watchlist' : 'Add to watchlist'}: ${esc(r.name)}">${r.watched ? '★' : '☆'}</button></td></tr>`).join('')
    + '</tbody>';
}

async function load() {
  const s = st(), q = new URLSearchParams();
  for (const k of ['group', 'age', 'contract', 'strong']) if (s[k]) q.set(k, s[k]);
  try {
    D = await api('/api/club-vs-league' + (q.toString() ? '?' + q : ''));
  } catch (e) { $('cv-msg').innerHTML = `<div class="notice">Could not load (${esc(e.message)}).</div>`; return; }
  const first = $('cv-body').hidden;
  drawTop(); drawGap(); drawRec();
  $('cv-skel').hidden = true; $('cv-body').hidden = false;
  if (first) $('cv-body').classList.add('fade-in');
}

$('cv-gap-t').addEventListener('click', ev => { const tr = ev.target.closest('tr[data-g]'); if (tr) commit({group: tr.dataset.g, league: ''}).then(() => $('cv-rec').scrollIntoView({behavior: 'smooth', block: 'start'})); });
$('cv-gap-t').addEventListener('keydown', ev => { const tr = ev.target.closest('tr[data-g]'); if (tr && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); commit({group: tr.dataset.g, league: ''}); } });
$('cv-group').addEventListener('change', e => commit({group: e.target.value, league: ''}));
$('cv-age').addEventListener('change', e => commit({age: e.target.value}));
$('cv-contract').addEventListener('change', e => commit({contract: e.target.value}));
$('cv-tabs').addEventListener('click', ev => { const t = ev.target.closest('button[data-l]'); if (t) commit({league: t.dataset.l}, false); });
$('cv-tabs').addEventListener('change', ev => { if (ev.target.id === 'cv-more' && ev.target.value) commit({league: ev.target.value}, false); });
$('cv-rec-t').addEventListener('click', async ev => {
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
const flipStrong = () => commit({strong: D && D.filters.strong ? '' : '1'});
$('cv-strong').addEventListener('click', flipStrong);
$('cv-strong').addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); flipStrong(); } });
addEventListener('popstate', load);
load();
