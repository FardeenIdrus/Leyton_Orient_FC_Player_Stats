// Report page (mockup v5 v-report). Draws what /api/report/... sends; it computes no number.
// Every provider or user string goes through esc() or textContent.
import {esc, chip, pcol, radar, orientSeries, api, readState, writeState, onStateChange} from './common.js';

const $ = id => document.getElementById(id);
const root = $('v-report');
const INK = '#15171C', ORIENT = '#1F5FA8';

let cur = null;          // {player, competition, season} of the open report
let view = null;         // last view drawn
let spec = null;         // the form's criteria for the open player
let loadSeq = 0, previewSeq = 0, searchSeq = 0;
const timers = {};
const debounce = (key, fn, ms) => { clearTimeout(timers[key]); timers[key] = setTimeout(fn, ms); };

const status = (text, cls = 'note') => {
  const s = $('rp-status');
  s.className = 'rp-status ' + (text ? cls : '');
  s.textContent = text || '';
};
const base = ids => `/api/report/${ids.player}/${ids.competition}/${ids.season}`;
const seasonName = id => {
  const o = [...$('rp-season').options].find(x => x.value === String(id));
  return o ? o.text : String(id);
};
const tip = t => t ? ` title="${esc(t)}"` : '';

// ---- drawing ----------------------------------------------------------------------------
function drawHead(v) {
  $('h-sub').textContent = `${v.position} · ${v.league} · ${seasonName(cur.season)}`;
  $('h-name').textContent = v.name;
  $('h-club').textContent = v.club;
  $('h-bio').innerHTML = v.bio.map(b => `<div>${esc(b.label)}<b>${esc(b.text)}</b></div>`).join('');
  const split = [v.splits ? `Minutes by position: <b>${esc(v.splits)}</b>` : '',
                 v.minority_note ? esc(v.minority_note) : ''].filter(Boolean);
  $('h-split').innerHTML = split.join(' · ');
  $('h-split').hidden = !split.length;
  $('h-cmp').textContent = v.comparison;
  const st = $('h-stamp');
  st.textContent = v.stamp;
  st.className = 'pill ' + (v.authored ? 'strong' : v.stamp === 'Data only' ? 'grey' : 'verdict-pos');
  $('h-asof').textContent = v.data_as_at;
  $('rp-dl-data').href = base(cur) + '/download?variant=data_only';
}

function drawVerdict(v) {
  const V = v.verdict;
  $('v-rank').textContent = V.rank || '';
  $('v-rank').hidden = !V.rank;
  const left = V.not_rated ? `<div class="warn rp-notrated">${esc(V.not_rated)}</div>`
    : `<div class="rp-composite">${V.composite == null ? '<span class="chip c0">—</span>' : chip(V.value)}</div>`;
  const rows = V.bands.map(b =>
    `<div class="rp-brow"><span>${esc(b.name)}${b.author ? ' <span class="note">(your view)</span>' : ''}</span>`
    + `${b.value == null ? `<span class="rp-absent">${esc(b.text)}</span>` : chip(b.value)}</div>`).join('');
  let h = `<div class="rp-verdict">${left}<div class="rp-blist">${rows}</div></div>`;
  if (V.screening.length)
    h += `<div class="rp-line"><b>Medical checks:</b> ${V.screening.map(s => `${s.ok ? '✓' : '✗'} ${esc(s.text)}`).join(' · ')}</div>`;
  if (V.flags.length)
    h += `<div class="warn rp-flags">${V.flags.map(f => `<div>⚠ ${esc(f)}</div>`).join('')}<div class="note">Flags are advisory and never exclude a player.</div></div>`;
  if (v.author_note) h += `<p class="note">${esc(v.author_note)}</p>`;
  $('v-body').innerHTML = h;
}

function drawSummary(v) {
  const N = v.narrative;
  let h = N.summary.length ? N.summary.map(p => `<p>${esc(p)}</p>`).join('') : `<p class="note">${esc(N.absent)}</p>`;
  if (N.why_sign.length) h += `<h3>Why sign</h3><ul>${N.why_sign.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
  if (N.considerations.length) h += `<h3>Considerations</h3><ul>${N.considerations.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
  if (N.byline) h += `<p class="note rp-byline">${esc(N.byline)}</p>`;
  if (!N.summary.length && $('rp-form').hidden) h += '<button class="btn small rp-write2" type="button" data-action="write">✎ Write your report</button>';
  $('n-body').innerHTML = h;
}

function drawTechnical(v) {
  const T = v.technical;
  $('t-sub').textContent = `Percentile vs ${T.vs}`;
  $('t-key').innerHTML = (T.orient ? `<span><i class="rp-tick"></i>${esc(T.orient.label)}</span>` : '')
    + (T.orient_note ? `<span>${esc(T.orient_note)}</span>` : '');
  $('t-counts').innerHTML = T.counts.map(c =>
    `<div class="tile"${tip(c.help)}><div class="k">${esc(c.label)}${c.help ? ' <span class="hlp">?</span>' : ''}</div><div class="v">${esc(c.text)}</div></div>`).join('');
  $('t-whence').textContent = T.whence || '';
  $('t-whence').hidden = !T.whence;
  $('t-bars').innerHTML = T.bars.length ? T.bars.map(b => {
    const tick = b.orient == null ? '' : `<u style="left:${b.orient}%"></u>`;
    const fill = b.value == null ? '' : `<i style="width:${Math.max(0.5, b.value)}%;background:${pcol(b.value)}"></i>`;
    return `<div class="rp-bar"><span class="l">${esc(b.label)}</span><div class="t">${fill}${tick}</div>`
      + `<b class="${b.value == null ? 'nm' : ''}">${b.text == null ? 'not measured' : esc(b.text)}</b></div>`;
  }).join('') : '<p class="note">No performance metrics for this position.</p>';
}

function drawStyle(v) {
  const S = v.style;
  const rows = S ? S.groups.reduce((n, g) => n + g.rows.length, 0) : 0;
  // No style rows (goalkeeper, too few minutes): no empty card; the label goes in the header.
  $('c-style').hidden = !rows;
  $('r-bottom').classList.toggle('solo', !rows);
  $('h-style').hidden = !S || !!rows;
  if (S && !rows) $('h-style').innerHTML = `Playing style: <b>${esc(S.label)}</b>`;
  if (!rows) return;
  $('s-sub').innerHTML = `vs ${esc(S.vs)} · Strong ${S.strong}+, Leans ${S.floor}+ <span class="hlp"${tip(S.help)}>?</span>`;
  const fill = r => r.level === 'Strong' ? '#1A1A1A' : r.level === 'Leans' ? '#9A9AA2' : '#D3D3D8';
  $('s-body').innerHTML = `<div class="rp-style-label">${esc(S.label)}</div>` + S.groups.map(g =>
    (g.title ? `<h3>${esc(g.title)}</h3>` : '') + g.rows.map(r =>
      `<div class="rp-srow"><b>${esc(r.name)}</b>`
      + `<div class="t"><i style="width:${Math.max(0.5, r.fit)}%;background:${fill(r)}"></i><u class="m50" style="left:${S.floor}%"></u><u class="m70" style="left:${S.strong}%"></u></div>`
      + `<span class="tag ${r.level ? r.level.toLowerCase() : ''}">${esc(r.tag)}</span>`
      + `<div class="sig">${esc(r.signals)}</div></div>`).join('')).join('');
}

function drawPhysical(v) {
  const P = v.physical, A = v.availability;
  $('p-sub').textContent = `Percentile vs ${P.vs}`;
  $('p-radar').classList.toggle('empty', !P.has_data);
  if (!P.has_data) {
    $('p-radar').innerHTML = '<p class="note">No physical data for this player-season.</p>';
  } else {
    const series = [{values: P.player, name: v.name}];
    const full = P.orient && P.orient.every(x => x != null);
    if (full) series.push(orientSeries(P.orient, P.orient_label));
    $('p-radar').innerHTML = radar(P.axes, series);
  }
  $('p-avail').innerHTML = `<div class="k">Availability</div><div class="v">${esc(A.figure)}</div><div class="note">${esc(A.note)}</div>`;
}

function draw(v) {
  view = v;
  drawHead(v); drawVerdict(v); drawSummary(v); drawTechnical(v); drawStyle(v); drawPhysical(v);
  $('f-psych-band').textContent = v.psych_caption;
}

// ---- the form ---------------------------------------------------------------------------
function buildForm(F) {
  spec = F;
  $('f-text').innerHTML = F.text_areas.map(t =>
    `<label class="rp-field"><span>${esc(t.label)}</span><textarea class="ctl" data-key="${esc(t.key)}" rows="${t.rows}" aria-label="${esc(t.label)}"></textarea></label>`).join('');
  const opts = '<option value="">—</option>' + F.scores.map(s => `<option value="${s}">${s}</option>`).join('');
  $('f-psych').innerHTML = F.psychological.length ? F.psychological.map((c, i) =>
    `<label class="rp-crit"><span>${esc(c.text)}</span><select class="ctl" data-psych="${i}" aria-label="${esc(c.text)}">${opts}</select></label>`).join('')
    : '<p class="note">No club criteria for this position.</p>';
  $('f-med').innerHTML = F.medical.map((c, i) => c.kind === 'screening'
    ? `<div class="rp-crit rp-screen"><span>${esc(c.text)}</span><div class="seg" role="radiogroup" aria-label="${esc(c.text)}">`
      + ['—', ...F.screen_choices].map((o, j) =>
        `<label><input type="radio" name="med${i}" data-med="${i}" value="${j ? esc(o) : ''}"${j ? '' : ' checked'}>${esc(o)}</label>`).join('') + '</div></div>'
    : `<p class="note rp-crit">${esc(c.text)}</p>`).join('')
    + `<label class="rp-crit"><span><b>Medical band</b></span><select class="ctl" id="f-mband" aria-label="Medical band">${opts}</select></label>`;
}

function formBody() {
  const body = {psych: {}, screening: {}};
  document.querySelectorAll('#f-text textarea').forEach(t => { body[t.dataset.key] = t.value; });
  document.querySelectorAll('#f-psych select').forEach(s => {
    if (s.value) body.psych[spec.psychological[+s.dataset.psych].text] = +s.value;
  });
  document.querySelectorAll('#f-med input:checked').forEach(r => {
    if (r.value) body.screening[spec.medical[+r.dataset.med].text] = r.value;
  });
  const mb = $('f-mband');
  if (mb && mb.value) body.medical_band = +mb.value;
  return body;
}

async function preview() {
  if (!cur) return;
  const mine = ++previewSeq, ids = {...cur};
  try {
    const v = await api(base(ids), {json: formBody()});
    if (mine !== previewSeq || !same(ids, cur)) return;
    if (v.error) { status(v.error.text, 'warn'); return; }
    status('');
    draw(v);
  } catch (e) {
    if (mine === previewSeq) status('The report could not be updated.', 'warn');
  }
}

// ---- downloads ----------------------------------------------------------------------------
async function downloadReport() {
  if (!cur) return;
  const btn = $('rp-dl');
  btn.disabled = true;
  try {
    const res = await fetch(base(cur) + '/download', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-LOFC-Request': '1'},
      body: JSON.stringify(formBody())});
    if (res.status === 401) { window.location.href = '/login'; return; }
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = view ? view.filename : 'report.html';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  } catch {
    status('The report could not be downloaded.', 'warn');
  } finally {
    btn.disabled = false;
  }
}

// ---- loading ------------------------------------------------------------------------------
/** No report on screen: the body and the form's fields go (a fresh load of the URL has none). */
function clearReport() {
  $('rp-body').hidden = true;
  ['f-text', 'f-psych', 'f-med'].forEach(id => { $(id).innerHTML = ''; });
  spec = null; view = null;
}
const same = (a, b) => a && b && a.player === b.player && a.competition === b.competition && a.season === b.season;

async function load(ids) {
  const mine = ++loadSeq;
  cur = ids;
  if (!ids) {
    clearReport();
    status('Search for a player to build their report.');
    return;
  }
  status('Building the report…');
  try {
    const v = await api(base(ids));
    if (mine !== loadSeq) return;
    if (v.error) {
      clearReport();
      status(v.error.kind === 'missing' ? `No report for this player in ${seasonName(ids.season)}.`
        : v.error.text, v.error.kind === 'missing' ? 'info' : 'warn');
      return;
    }
    buildForm(v.form);   // a new player-season starts a blank form, as on Streamlit
    status('');
    $('rp-body').hidden = false;
    draw(v);
  } catch (e) {
    if (mine !== loadSeq) return;
    clearReport();
    status('The report could not be built.', 'warn');
  }
}

function idsFromState(s) {
  const n = k => (s[k] != null && /^\d+$/.test(s[k])) ? +s[k] : null;
  const p = n('player'), c = n('competition');
  if (p == null || c == null) return null;
  return {player: p, competition: c, season: n('season') ?? +root.dataset.defaultSeason};
}

function applyState(s) {
  const def = +root.dataset.defaultSeason;
  const season = (s.season && [...$('rp-season').options].some(o => o.value === s.season)) ? +s.season : def;
  $('rp-season').value = String(season);
  const ids = idsFromState({...s, season: String(season)});
  if (!same(ids, cur)) load(ids);
}

// ---- search -------------------------------------------------------------------------------
function wireSearch() {
  const box = $('rp-search'), out = $('rp-results'), clear = $('rp-clear');
  const run = async () => {
    const q = box.value.trim(), mine = ++searchSeq;
    if (!q) { out.hidden = true; return; }
    let r;
    try { r = await api('/api/players/search?' + new URLSearchParams({season: $('rp-season').value, q})); }
    catch { r = {results: []}; }
    if (mine !== searchSeq) return;
    out._results = r.results;
    out.innerHTML = r.results.length
      ? r.results.map((x, i) => `<button type="button" data-action="pick" data-i="${i}">${esc(x.label)}</button>`).join('')
      : '<div class="none">No player matches that name in the selected season.</div>';
    out.hidden = false;
  };
  box.addEventListener('input', () => { clear.disabled = !box.value; debounce('search', run, 200); });
  box.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); clearTimeout(timers.search); run(); } });
  clear.addEventListener('click', () => { box.value = ''; clear.disabled = true; out.hidden = true; ++searchSeq; });
  out.addEventListener('click', e => {
    const b = e.target.closest('button[data-action="pick"]');
    if (!b) return;
    const x = out._results[+b.dataset.i];
    out.hidden = true;
    const ids = {player: x.player_id, competition: x.competition_id, season: x.season_id};
    writeState({player: ids.player, competition: ids.competition, season: ids.season});
    load(ids);
  });
  document.addEventListener('click', e => { if (!e.target.closest('.searchbox')) out.hidden = true; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') out.hidden = true; });
}

// ---- wiring -------------------------------------------------------------------------------
function wire() {
  wireSearch();
  $('rp-season').addEventListener('change', () => {
    const season = +$('rp-season').value;
    writeState({season});
    if ($('rp-search').value.trim()) $('rp-search').dispatchEvent(new Event('input'));
    if (cur) load({...cur, season});
  });
  const toggleForm = force => {
    const open = force ?? $('rp-form').hidden;
    $('rp-form').hidden = !open;
    $('rp-write').setAttribute('aria-expanded', String(open));
    const b2 = document.querySelector('.rp-write2');
    if (b2) b2.hidden = open;
    if (open) $('rp-form').scrollIntoView({block: 'nearest'});
  };
  $('rp-write').addEventListener('click', () => toggleForm());
  $('n-body').addEventListener('click', e => { if (e.target.closest('[data-action=write]')) toggleForm(true); });
  $('rp-form').addEventListener('input', () => debounce('preview', preview, 250));
  $('rp-form').addEventListener('change', () => debounce('preview', preview, 50));
  $('rp-dl').addEventListener('click', downloadReport);
  onStateChange(applyState);
  applyState(readState());
}

wire();
