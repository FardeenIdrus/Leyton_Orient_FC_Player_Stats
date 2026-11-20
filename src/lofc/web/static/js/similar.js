// Similar players page (owner 2026-11-20): the card's list with its filters, and one match
// broken down measure by measure. Draws what /api/similar/... sends; it computes no number.
// Provider strings go through esc() or textContent, never raw into innerHTML.
import {esc, dash, fmtInt, chip, api, readState, writeState, onStateChange} from './common.js';
import {PAGE, filterRows, rowText} from './report_search.js';

const $ = id => document.getElementById(id);
const root = $('v-similar');
const HAS_PLAYER = !!root.dataset.player;
const KEY = `${root.dataset.player}/${root.dataset.competition}/${root.dataset.season}`;

const fromUrl = q => ({scope: q.scope === 'all' ? 'all' : 'league', max_age: q.max_age || '',
  league: q.league || '', min_minutes: q.min_minutes || '', contract: q.contract || '', match: q.match || ''});
let st = fromUrl(readState());
let req = 0;

const query = (s, {match = true} = {}) => {
  const q = new URLSearchParams();
  if (s.scope === 'all') q.set('scope', 'all');
  for (const k of ['max_age', 'min_minutes', 'contract']) if (s[k]) q.set(k, s[k]);
  if (s.scope === 'all' && s.league) q.set('league', s.league);
  if (match && s.match) q.set('match', s.match);
  const t = q.toString();
  return t ? '?' + t : '';
};
const options = (list, cur, first = 'Any') => `<option value="">${esc(first)}</option>`
  + list.map(([v, t]) => `<option value="${esc(v)}"${String(v) === String(cur ?? '') ? ' selected' : ''}>${esc(t)}</option>`).join('');
/** z to 1 dp with its sign ("+0.4", "−1.2"); "—" when missing. */
const signed = z => {
  if (z == null || !Number.isFinite(+z)) return '—';
  const v = Math.abs(+z).toFixed(1);
  return (+z < 0 && +v > 0 ? '−' : '+') + v;
};
const back = () => '?back=' + encodeURIComponent(location.pathname + location.search);

function renderHead(D) {
  const P = D.player;
  if (!P) { $('sim-player').textContent = 'Similar players'; $('sim-meta').textContent = ''; return; }
  $('sim-player').innerHTML = `<a href="${esc(P.href)}">${esc(P.name)}</a>`;
  $('sim-meta').textContent = [P.club, P.league, P.position, D.season].map(dash).join(' · ');
  document.title = `Similar to ${P.name}`;
}

function renderFilters(D) {
  for (const b of $('sim-scope').querySelectorAll('button')) {
    const on = b.dataset.scope === D.scope;
    b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
  }
  $('sim-league-wrap').hidden = D.scope !== 'all';
  $('sim-league').innerHTML = options(D.league_options || [], D.league, 'All');
  $('sim-age').innerHTML = options((D.age_options || []).map(a => [a, a]), D.max_age);
  $('sim-min').innerHTML = options((D.min_minutes_options || []).map(m => [m, fmtInt(m)]), D.min_minutes);
  $('sim-contract').innerHTML = options(D.contract_options || [], D.contract);
  $('sim-sub').textContent = D.sub || '';
  $('sim-notes').innerHTML = [D.note, D.pool_note, D.physical_note].filter(Boolean)
    .map(t => `<p class="note sim-note">${esc(t)}</p>`).join('');
}

function renderList(D) {
  if (!D.rows || !D.rows.length) { $('sim-list').innerHTML = `<p class="note">${esc(D.empty || '')}</p>`; return; }
  const all = D.scope === 'all';
  const cols = ['Player', 'Club', ...(all ? ['League'] : []), 'Age', 'Minutes', 'Overall', 'Similarity %', 'Biggest differences', ''];
  const helps = {'Similarity %': D.similarity_help, 'Biggest differences': D.diff_help, Overall: 'Rated in his own league.'};
  const n = c => ['Age', 'Minutes', 'Similarity %'].includes(c);
  const head = '<tr>' + cols.map(c => `<th${n(c) ? ' class="n"' : ''}${helps[c] ? ` title="${esc(helps[c])}"` : ''}>${esc(c)}</th>`).join('') + '</tr>';
  const body = D.rows.map(r => `<tr data-key="${esc(r.key)}" class="pick${r.key === D.selected ? ' target' : ''}">`
    + `<td><a href="${esc(r.href)}${back()}">${esc(r.name)}</a></td>`
    + `<td>${esc(dash(r.club))}</td>` + (all ? `<td>${esc(dash(r.league))}</td>` : '')
    + `<td class="n">${r.age == null ? '—' : r.age.toFixed(1)}</td><td class="n">${fmtInt(r.minutes)}</td>`
    + `<td>${chip(r.overall)}</td><td class="n"><b>${r.similarity == null ? '—' : r.similarity}</b></td>`
    + `<td class="sim-diff">${esc(r.differences_text || '—')}</td>`
    + `<td class="sim-why"><a href="${esc(query({...st, match: r.key}))}" data-key="${esc(r.key)}">Why</a></td></tr>`).join('');
  $('sim-list').innerHTML = `<table class="sim"><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

function renderBreakdown(D) {
  const B = D.breakdown;
  $('c-sim-break').hidden = !B;
  if (!B) return;
  const him = D.player.name, other = D.match.name;
  $('sim-break-h').innerHTML = `<a href="${esc(D.player.href)}">${esc(him)}</a> vs <a href="${esc(D.match.href)}">${esc(other)}</a>`;
  $('sim-break-sub').textContent = 'Each measure in the score, largest weighted gap first';
  $('sim-compare').href = D.compare_href;
  $('sim-score').innerHTML = `<b>${B.similarity == null ? '—' : B.similarity}%</b> similar`
    + `<span class="note">${esc(D.similarity_help || '')}</span>`;
  const head = '<tr>' + ['Measure', 'Weight', him, other, `${him} vs league`, `${other} vs league`, 'Difference']
    .map((c, i) => `<th${i ? ' class="n"' : ''}${i === 1 ? ' title="Share of Overall"' : ''}${i >= 4 ? ' title="Standard deviations from his league\'s average"' : ''}>${esc(c)}</th>`).join('') + '</tr>';
  const body = B.rows.map(r => {
    const tags = (r.used ? '' : '<span class="sim-tag off">not used</span>')
      + (r.linked && r.linked.length ? `<span class="sim-tag" title="${esc('Moves with: ' + r.linked.join(', '))}">linked</span>` : '');
    const cls = r.diff == null ? '' : r.diff > 0.05 ? ' up' : r.diff < -0.05 ? ' down' : '';
    return `<tr class="${r.used ? '' : 'unused'}"><td>${esc(r.label)}${tags}</td>`
      + `<td class="n">${r.weight_pct == null ? '—' : r.weight_pct.toFixed(1) + '%'}</td>`
      + `<td class="n">${esc(dash(r.him))}</td><td class="n">${esc(dash(r.match))}</td>`
      + `<td class="n">${signed(r.him_z)}</td><td class="n">${signed(r.match_z)}</td>`
      + `<td class="n diff${cls}">${signed(r.diff)}</td></tr>`;
  }).join('');
  $('sim-break').innerHTML = `<table class="sim-b"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  $('sim-break-note').textContent = B.note || '';
}

async function load() {
  const mine = ++req;
  $('sim-status').textContent = '';
  try {
    const D = await api(`/api/similar/${KEY}${query(st)}`);
    if (mine !== req) return;
    renderHead(D); renderFilters(D); renderList(D); renderBreakdown(D);
    if (!D.available) $('sim-status').textContent = D.empty || '';
  } catch (e) {
    if (mine === req) $('sim-status').textContent = `Could not load this page (${e.message}).`;
  }
}

function set(patch) {
  st = {...st, ...patch};
  writeState({scope: st.scope === 'all' ? 'all' : '', max_age: st.max_age,
    league: st.scope === 'all' ? st.league : '', min_minutes: st.min_minutes, contract: st.contract, match: st.match});
  load();
}

function bind() {
  $('sim-scope').onclick = ev => {
    const b = ev.target.closest('button[data-scope]'); if (!b || b.dataset.scope === st.scope) return;
    set({scope: b.dataset.scope, match: ''});
  };
  for (const [id, k] of [['sim-league', 'league'], ['sim-age', 'max_age'], ['sim-min', 'min_minutes'], ['sim-contract', 'contract']])
    $(id).onchange = ev => set({[k]: ev.target.value, match: ''});
  // a row (or its "Why") selects that match; the player's name still opens his page
  $('sim-list').onclick = ev => {
    if (ev.target.closest('a') && !ev.target.closest('a[data-key]')) return;
    const tr = ev.target.closest('tr[data-key]'); if (!tr) return;
    ev.preventDefault();
    if (tr.dataset.key !== st.match) set({match: tr.dataset.key});
    $('c-sim-break').scrollIntoView({behavior: 'smooth', block: 'nearest'});
  };
  onStateChange(q => { st = fromUrl(q); load(); });
}

// ---- player search (owner 2026-11-20: Similar players is its own page in the nav) ----------
// Every player of the chosen season A-Z (the Report's list, /api/report/players); typing
// filters it; a pick opens /similar/<player>/<league>/<season>, keeping the filters.
const seasonRows = {};
const rowsFor = season => {
  if (!seasonRows[season]) {
    seasonRows[season] = api('/api/report/players?' + new URLSearchParams({season})).then(d => d.rows || []);
    seasonRows[season].catch(() => { delete seasonRows[season]; });
  }
  return seasonRows[season];
};

function wireSearch() {
  const box = $('sim-search'), out = $('sim-results'), season = $('sim-season');
  let shown = [], drawn = 0, seq = 0;
  const more = () => {
    const next = shown.slice(drawn, drawn + PAGE);
    out.insertAdjacentHTML('beforeend', next.map((r, k) =>
      `<button type="button" data-i="${drawn + k}">${esc(rowText(r))}</button>`).join(''));
    drawn += next.length;
  };
  const run = async () => {
    const mine = ++seq, sid = season.value;
    let rows;
    try { rows = await rowsFor(sid); } catch { rows = []; }
    if (mine !== seq) return;
    shown = filterRows(rows, box.value); drawn = 0;
    out.innerHTML = shown.length ? '' : `<div class="none">${esc(rows.length
      ? 'No player matches that name in this season.' : 'No players in this season.')}</div>`;
    out.scrollTop = 0; more(); out.hidden = false;
  };
  out.addEventListener('scroll', () => {
    if (drawn < shown.length && out.scrollTop + out.clientHeight >= out.scrollHeight - 400) more();
  });
  box.addEventListener('focus', run);
  box.addEventListener('input', () => { clearTimeout(box._t); box._t = setTimeout(run, 60); });
  season.addEventListener('change', () => { if (!out.hidden || box.value) run(); });
  out.addEventListener('click', e => {
    const b = e.target.closest('button[data-i]'); if (!b) return;
    const r = shown[+b.dataset.i];
    location.href = `/similar/${r[0]}/${r[1]}/${season.value}${query(st, {match: false})}`;
  });
  document.addEventListener('click', e => { if (!e.target.closest('.searchbox')) out.hidden = true; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') out.hidden = true; });
}

wireSearch();
if (HAS_PLAYER) { bind(); load(); }
else $('sim-status').textContent = 'Search a player to see his closest matches.';
