// Report page (mockup v5 v-report). Draws what /api/report/... sends; it computes no number.
// Every provider or user string goes through esc() or textContent.
import {esc, chip, pcol, radar, orientSeries, api, readState, writeState, onStateChange, rememberState, restoreState} from './common.js';
import {readDraft, writeDraft, clearDraft, hasWork} from './report_draft.js';
import {PAGE, filterRows, rowText} from './report_search.js';

// While a download copy is painted, `scope` is that copy and $ looks inside it.
let scope = null;
const $ = id => scope ? scope.querySelector('#' + id) : document.getElementById(id);
const root = $('v-report');
const INK = '#15171C', ORIENT = '#1F5FA8';

let cur = null;          // {player, competition, season} of the open report
let view = null;         // last view drawn
let spec = null;         // the form's criteria for the open player
let photo = null;        // the chosen photo as a JPEG data URI: kept in the draft, never sent
const store = (() => { try { return window.localStorage; } catch (e) { return null; } })();
// owner 2026-11-13: the nav link (a bare /report) reopens the last season (the player is not
// kept; his draft has its own storage)
const remember = () => rememberState('report', {keep: ['season']});
const setState = (patch, o) => { writeState(patch, o); remember(); };
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
  const o = [...document.getElementById('rp-season').options].find(x => x.value === String(id));
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
}

function drawVerdict(v) {
  const V = v.verdict;
  // Left: the composite as one large number on its band's tint (the chips' rule), its rank under
  // it; the block is as tall as the four dimension rows beside it (owner 2026-11-13).
  const band = V.not_rated ? 'nr' : V.composite == null ? 'c0' : (chip(V.value).match(/chip (c\d)/) || [])[1] || 'c0';
  const left = `<div class="rp-cleft"><div class="rp-cblock ${band}"><div class="rp-clabel">Composite</div>`
    + (V.not_rated ? `<div class="rp-notrated">${esc(V.not_rated)}</div>`
      : `<div class="rp-composite"><div class="rp-score">${esc(V.composite ?? '—')}</div>`
        + (V.rank ? `<div class="rp-rank">${esc(V.rank)}</div>` : '') + '</div>')
    + '</div></div>';
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
  if (!scope && !N.summary.length && $('rp-form').hidden) h += '<button class="btn small rp-write2" type="button" data-action="write">✎ Write your report</button>';
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
  // The left column also holds the scout verdicts, so it stays when they are there.
  const scouts = (v.scouts || []).length;
  $('c-style').hidden = !rows;
  $('r-left').hidden = !rows && !scouts;
  $('r-bottom').classList.toggle('solo', !rows && !scouts);
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

/** Each scout's latest verdict (owner 2026-11-13); none: no card. Not in the data-only view. */
const VTONE = {positive: 'verdict-pos', negative: 'verdict-neg', neutral: 'verdict-mid'};
function drawScouts(v) {
  const S = v.scouts || [];
  $('c-scouts').hidden = !S.length;
  $('sc-body').innerHTML = S.map(x =>
    `<div class="rp-scout"><b>${esc(x.scout)}</b><span class="pill ${VTONE[x.tone] || 'grey'}">${esc(x.verdict)}</span>`
    + `<span class="note">${esc(x.date)}</span></div>`).join('');
}

function drawPhysical(v, withRadar = true, rows = availRows()) {
  const P = v.physical;
  $('p-sub').textContent = `Percentile vs ${P.vs}`;
  drawAvail(v, rows);
  if (!withRadar) return;
  $('p-radar').classList.toggle('empty', !P.has_data);
  if (!P.has_data) {
    $('p-radar').innerHTML = '<p class="note">No physical data for this player-season.</p>';
  } else {
    const series = [{values: P.player, name: v.name}];
    const full = P.orient && P.orient.every(x => x != null);
    if (full) series.push(orientSeries(P.orient, P.orient_label));
    $('p-radar').innerHTML = radar(P.axes, series);
  }
}

/** Our figure and note, then the writer's own rows (kept in the draft; never sent). */
function drawAvail(v, rows) {
  const A = v.availability;
  $('p-avail').innerHTML = `<div class="v">${esc(A.figure)}</div><div class="note">${esc(A.note)}</div>`
    + (rows.length ? '<table class="rp-avtab"><thead><tr><th>Dates</th><th>Injury</th><th>Matches missed</th></tr></thead><tbody>'
      + rows.map(r => `<tr><td>${esc(r.dates)}</td><td>${esc(r.injury)}</td><td>${esc(r.missed)}</td></tr>`).join('')
      + '</tbody></table>' : '');
}

function paint(v, {withRadar = true, rows = availRows()} = {}) {
  drawHead(v); drawVerdict(v); drawSummary(v); drawTechnical(v); drawStyle(v); drawScouts(v);
  drawPhysical(v, withRadar, rows);
  if (!scope) $('f-psych-band').textContent = v.psych_caption;
}

function draw(v) {
  view = v;
  paint(v);
}

// ---- the writer's availability rows (in this page only) -----------------------------------
const AV_FIELDS = [['dates', 'Dates (from–to)', 'text'], ['injury', 'Injury', 'text'],
                   ['missed', 'Matches missed', 'number']];
function availRows() {
  return [...document.querySelectorAll('#f-avail .rp-avrow')].map(r =>
    Object.fromEntries(AV_FIELDS.map(([k]) => [k, r.querySelector(`[data-av=${k}]`).value.trim()])))
    .filter(r => r.dates || r.injury || r.missed);
}
function addAvailRow(values = null) {
  const row = document.createElement('div');
  row.className = 'rp-avrow';
  row.innerHTML = AV_FIELDS.map(([k, label, type]) =>
    `<input class="ctl" type="${type}"${type === 'number' ? ' min="0"' : ''} data-av="${k}" placeholder="${label}" aria-label="${label}">`).join('')
    + '<button class="btn small" type="button" data-action="av-del" aria-label="Remove row">✕</button>';
  $('f-avail').appendChild(row);
  if (values) AV_FIELDS.forEach(([k]) => { row.querySelector(`[data-av=${k}]`).value = values[k] ?? ''; });
  else row.querySelector('input').focus();
}

// ---- the photo (read and downscaled in the browser; never uploaded) ------------------------
function showPhoto() {
  const img = $('rp-photo-img');
  img.hidden = !photo;
  if (photo) img.src = photo; else img.removeAttribute('src');
  $('rp-photo-del').hidden = !photo;
  $('rp-photo').classList.toggle('has', !!photo);
}
async function pickPhoto(file) {
  if (!file) return;
  try {
    const bmp = await createImageBitmap(file);
    const W = 300, H = 380, c = document.createElement('canvas');
    c.width = W; c.height = H;
    const k = Math.max(W / bmp.width, H / bmp.height), w = bmp.width * k, h = bmp.height * k;
    const g = c.getContext('2d');
    g.fillStyle = '#fff'; g.fillRect(0, 0, W, H);
    g.drawImage(bmp, (W - w) / 2, (H - h) / 2, w, h);
    photo = c.toDataURL('image/jpeg', 0.85);
    showPhoto();
    saveDraftSoon();
  } catch {
    status('That image could not be read.', 'warn');
  }
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

// ---- downloads: the preview sheet itself, saved by the browser ---------------------------
const A4L = {w: 1062, h: 733};    // landscape A4 inside 8 mm margins, CSS px
const PRINT_W = 1600;             // the sheet is printed laid out at this width, then scaled
// Printed only: the same sections, denser, so one landscape page holds them at a readable size.
const PRINT_CSS = '.rp-sheet{box-shadow:none}.rp-head{padding:12px 0}.rp-row{padding:12px 0}'
  + '.rp-bars{grid-template-columns:repeat(3,minmax(0,1fr));margin-top:8px}.rp-bar{padding:4px 0}'
  + '.rp-counts .tile{padding:6px 14px}.rp-srow{padding:4px 0}.rp-srow .sig{font-size:12.5px}'
  + '#c-style h3{margin:8px 0 2px}.rp-scout{padding:4px 0}.rp-brow{padding:5px 0}'
  + '.rp-col>.rp-sec+.rp-sec:not([hidden]){margin-top:10px;padding-top:10px}';

/** app.css + report.css as text. Width rules apply on screen only, so print keeps the wide
 *  layout; fonts are left to the system. */
function pageCss() {
  const out = [];
  for (const sh of document.styleSheets) {
    if (!sh.href || !/\/css\/(app|report)\.css/.test(sh.href)) continue;
    let rules;
    try { rules = sh.cssRules; } catch { continue; }
    for (const r of rules) {
      if (r.type === CSSRule.FONT_FACE_RULE || r.type === CSSRule.IMPORT_RULE) continue;
      if (r.type === CSSRule.MEDIA_RULE && !/print/.test(r.conditionText))
        out.push(`@media screen and ${r.conditionText}{${[...r.cssRules].map(x => x.cssText).join('')}}`);
      else out.push(r.cssText);
    }
  }
  return out.join('\n');
}

// On screen the file is the preview: the sheet as wide as on the page (the window less the
// sidebar, app.css .app; main keeps app.css's padding), centred; columns never wider than their
// track, so the radar (scaled by its viewBox) and the availability table stay inside the sheet.
const FILE_CSS = `html,body{margin:0}
body{background:var(--page)}
@media screen{main{max-width:none;margin:0 auto;padding-top:24px;width:calc(100% - 236px)}}
@media screen and (max-width:1280px){main{width:calc(100% - 208px)}}
@media screen and (max-width:900px){main{width:auto}}
.rp-col{grid-template-columns:minmax(0,1fr)}
.rp-col>*,.rdr,.rdr-stage{min-width:0;max-width:100%}
.rdr-svg{max-width:100%;height:auto}
.rp-photo-pick{cursor:default}
.rdr-key{cursor:default}
@page{size:A4 landscape;margin:8mm}`;

function fileHtml(v, body, fit) {
  // fit null: the print layout itself, on screen, to be measured; else {width, scale}
  const print = fit == null ? `main{width:${PRINT_W}px;max-width:none;padding:0;margin:0}${PRINT_CSS}`
    : fit ? `@media print{body{background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact}`
    + `main{width:${fit.width}px;max-width:none;padding:0;margin:0;zoom:${fit.scale}}${PRINT_CSS}}` : '';
  return `<!doctype html>\n<html lang="en"><head><meta charset="utf-8">`
    + `<meta name="viewport" content="width=device-width,initial-scale=1">`
    + `<title>${esc(v.name)} · Player report</title><style>${pageCss()}\n${FILE_CSS}\n${print}</style></head>`
    + `<body><main id="v-report">${body}</main></body></html>`;
}

/** The layout width and scale that fill one landscape A4 page's width (owner 2026-11-13: the
 *  sheet used ~2/3 of it): the narrowest layout from PRINT_W up that is no taller than the page
 *  once scaled to its full width; if none is, the old fit (whole sheet, height-bound). */
async function printScale(v, body) {
  const f = document.createElement('iframe');
  f.setAttribute('aria-hidden', 'true');
  f.style.cssText = 'position:fixed;left:-30000px;top:0;width:1720px;height:900px;border:0;visibility:hidden';
  const loaded = new Promise(r => f.addEventListener('load', r, {once: true}));
  f.srcdoc = fileHtml(v, body, null);
  document.body.appendChild(f);
  try {
    await loaded;
    const main = f.contentDocument.querySelector('main');
    let h = 1, width = PRINT_W;
    for (width = PRINT_W; width <= PRINT_W * 2; width += 50) {
      main.style.width = width + 'px';
      h = Math.max(main.getBoundingClientRect().height, 1);
      if (h * A4L.w / width <= A4L.h * 0.98) return {width, scale: +(A4L.w / width * 0.99).toFixed(4)};
    }
    width = PRINT_W * 2;
    return {width, scale: +(Math.min(A4L.w / width, A4L.h / h) * 0.97).toFixed(4)};
  } finally {
    f.remove();
  }
}

/** The on-screen sheet as one self-contained file: a copy painted with `v`, without the
 *  page's controls (photo picker, buttons, empty photo box). */
async function reportFile(v, authored) {
  const copy = $('rp-sheet').cloneNode(true);
  scope = copy;
  try { paint(v, {withRadar: false, rows: authored ? availRows() : []}); } finally { scope = null; }
  copy.querySelectorAll('.rp-write2, .rdr-tools, #rp-photo-file, .rp-photo-add, #rp-photo-del')
    .forEach(e => e.remove());
  // on-screen help only (owner 2026-11-13): no ⓘ / ? icons, tooltips or hover targets in the file
  copy.querySelectorAll('.hlp, .hlp-i, .rdr-hits').forEach(e => e.remove());
  copy.querySelectorAll('[title], [data-tip], [tabindex], .has-help').forEach(e => {
    e.removeAttribute('title'); e.removeAttribute('data-tip'); e.removeAttribute('tabindex');
    e.classList.remove('has-help');
    if (!e.classList.length) e.removeAttribute('class');
  });
  if (!photo) copy.querySelector('#rp-photo').remove();
  copy.querySelectorAll('#c-scouts[hidden], #r-left[hidden], #h-style[hidden], #c-style[hidden]').forEach(e => e.remove());
  copy.querySelectorAll('.rdr-svg[data-vb]').forEach(svg => svg.setAttribute('viewBox', svg.dataset.vb));
  copy.querySelectorAll('button').forEach(b => {     // radar key: a key, not a control
    const sp = document.createElement('span');
    sp.className = b.className; sp.innerHTML = b.innerHTML;
    b.replaceWith(sp);
  });
  const body = copy.outerHTML;
  return fileHtml(v, body, await printScale(v, body));
}

function save(html, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([html], {type: 'text/html;charset=utf-8'}));
  a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

async function download(dataOnly) {
  if (!cur || !view) return;
  const btn = $(dataOnly ? 'rp-dl-data' : 'rp-dl'), ids = {...cur};
  btn.disabled = true;
  try {
    const v = dataOnly ? await api(base(ids) + '?variant=data_only') : await api(base(ids), {json: formBody()});
    if (!same(ids, cur)) return;
    if (v.error) throw new Error(v.error.text);
    save(await reportFile(v, !dataOnly), dataOnly ? v.data_only_filename : v.filename);
  } catch {
    status('The report could not be downloaded.', 'warn');
  } finally {
    btn.disabled = false;
  }
}

// ---- the draft: the writer's work, kept in this browser per player-season ------------------
let formGen = 0;         // bumped whenever the form is rebuilt; a save queued for an older form is dropped

function draftNow() {
  const text = {}, psych = {}, med = {};
  document.querySelectorAll('#f-text textarea').forEach(t => { if (t.value) text[t.dataset.key] = t.value; });
  document.querySelectorAll('#f-psych select').forEach(s => {
    if (s.value) psych[spec.psychological[+s.dataset.psych].text] = s.value;
  });
  document.querySelectorAll('#f-med input:checked').forEach(r => {
    if (r.value) med[spec.medical[+r.dataset.med].text] = r.value;
  });
  const mb = document.getElementById('f-mband');
  return {text, psych, med, mband: mb && mb.value ? mb.value : null, avail: availRows(), photo};
}

function saveDraft(ids = cur) {
  clearTimeout(timers.draft); timers.draft = null;
  if (!ids || !spec) return;
  const msg = writeDraft(store, ids, draftNow());
  $('rp-draft-note').textContent = msg === 'unsaved' ? '' : msg;
}
/** Save shortly after the last change, for the form that is on screen now. */
function saveDraftSoon() {
  if (!cur || !spec) return;
  const ids = {...cur}, gen = formGen;
  clearTimeout(timers.draft);
  timers.draft = setTimeout(() => { if (gen === formGen && same(ids, cur)) saveDraft(ids); }, 300);
}
/** A change still waiting to be saved is saved now (before the form goes, or the page). */
function flushDraft() { if (timers.draft) saveDraft(); }

/** Put a stored draft back into the freshly built form. True when there was one. */
function restoreDraft(ids) {
  const d = readDraft(store, ids);
  if (!hasWork(d)) return false;
  const T = d.text || {}, P = d.psych || {}, M = d.med || {};
  document.querySelectorAll('#f-text textarea').forEach(t => { t.value = T[t.dataset.key] ?? ''; });
  document.querySelectorAll('#f-psych select').forEach(s => {
    const x = P[spec.psychological[+s.dataset.psych].text];
    if (x != null && [...s.options].some(o => o.value === String(x))) s.value = String(x);
  });
  document.querySelectorAll('#f-med input[type=radio]').forEach(r => {
    const x = M[spec.medical[+r.dataset.med].text];
    if (x != null && r.value === x) r.checked = true;
  });
  const mb = document.getElementById('f-mband');
  if (mb && d.mband != null && [...mb.options].some(o => o.value === String(d.mband))) mb.value = String(d.mband);
  (Array.isArray(d.avail) ? d.avail : []).forEach(r => addAvailRow(r));
  if (d.photo) { photo = d.photo; showPhoto(); }
  return true;
}

function resetDraft() {
  if (!cur || !spec) return;
  clearTimeout(timers.draft); timers.draft = null;
  clearDraft(store, cur);
  formGen++;
  buildForm(spec);
  $('f-avail').innerHTML = '';
  photo = null; showPhoto();
  $('rp-draft-note').textContent = '';
  preview();
}

// ---- loading ------------------------------------------------------------------------------
/** No report on screen: the body and the form's fields go (a fresh load of the URL has none). */
function clearReport() {
  $('rp-body').hidden = true;
  ['f-text', 'f-psych', 'f-med', 'f-avail'].forEach(id => { $(id).innerHTML = ''; });
  photo = null; showPhoto();
  spec = null; view = null;
  formGen++;
}
const same = (a, b) => a && b && a.player === b.player && a.competition === b.competition && a.season === b.season;

async function load(ids, {follow = false} = {}) {
  const mine = ++loadSeq;
  flushDraft();
  if (!ids || !cur || ids.player !== cur.player) { photo = null; showPhoto(); }   // his photo, from his draft only
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
    buildForm(v.form);   // a new player-season starts a blank form, then his stored draft if any
    formGen++;
    $('f-avail').innerHTML = '';
    $('rp-draft-note').textContent = '';
    status('');
    $('rp-body').hidden = false;
    draw(v);
    if (restoreDraft(ids)) {
      $('rp-draft-note').textContent = 'Draft restored';
      toggleForm(true);
      drawAvail(v, availRows());
      preview();
    }
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
  if (s.position != null) setState({position: null}, {replace: true});   // owner 2026-11-13: no Position
  const ids = idsFromState({...s, season: String(season)});
  if (!same(ids, cur)) load(ids);
}

// ---- search -------------------------------------------------------------------------------
// owner 2026-11-13: one list, every player of the season A-Z (name · position · club · league),
// loaded once per season; the empty box shows it all, typing filters it in place. Drawn PAGE
// rows at a time, more as it scrolls (about 10,000 rows).
const seasonRows = {};
function rowsFor(season) {
  if (!seasonRows[season]) {
    seasonRows[season] = api('/api/report/players?' + new URLSearchParams({season}))
      .then(d => d.rows || []);
    seasonRows[season].catch(() => { delete seasonRows[season]; });
  }
  return seasonRows[season];
}

function wireSearch() {
  const box = $('rp-search'), out = $('rp-results'), clear = $('rp-clear');
  let shown = [], drawn = 0;
  const more = () => {
    const next = shown.slice(drawn, drawn + PAGE);
    out.insertAdjacentHTML('beforeend', next.map((r, k) =>
      `<button type="button" data-action="pick" data-i="${drawn + k}">${esc(rowText(r))}</button>`).join(''));
    drawn += next.length;
  };
  const run = async () => {
    const mine = ++searchSeq, season = $('rp-season').value;
    if (document.activeElement !== box && !box.value.trim()) { out.hidden = true; return; }
    let rows;
    try { rows = await rowsFor(season); } catch { rows = []; }
    if (mine !== searchSeq) return;                          // the box moved on meanwhile
    shown = filterRows(rows, box.value); drawn = 0;
    out._season = +season;
    out.innerHTML = shown.length ? '' : `<div class="none">${esc(rows.length
      ? 'No player matches that name in the selected season.' : 'No players in the selected season.')}</div>`;
    out.scrollTop = 0;
    more();
    out.hidden = false;
  };
  out.addEventListener('scroll', () => {
    if (drawn < shown.length && out.scrollTop + out.clientHeight >= out.scrollHeight - 400) more();
  });
  box.addEventListener('focus', () => run());
  box.addEventListener('click', () => { if (out.hidden) run(); });
  box.addEventListener('input', () => { clear.disabled = !box.value; debounce('search', run, 60); });
  box.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); clearTimeout(timers.search); run(); } });
  clear.addEventListener('click', () => { box.value = ''; clear.disabled = true; out.hidden = true; ++searchSeq; });
  out.addEventListener('click', e => {
    const b = e.target.closest('button[data-action="pick"]');
    if (!b) return;
    const r = shown[+b.dataset.i];
    out.hidden = true;
    const ids = {player: r[0], competition: r[1], season: out._season};
    setState({player: ids.player, competition: ids.competition, season: ids.season});
    load(ids, {follow: true});
  });
  document.addEventListener('click', e => { if (!e.target.closest('.searchbox')) out.hidden = true; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') out.hidden = true; });
}

// ---- wiring -------------------------------------------------------------------------------
function toggleForm(force) {
  const open = force ?? $('rp-form').hidden;
  $('rp-form').hidden = !open;
  $('rp-write').setAttribute('aria-expanded', String(open));
  const b2 = document.querySelector('.rp-write2');
  if (b2) b2.hidden = open;
  if (open) $('rp-form').scrollIntoView({block: 'nearest'});
}

function wire() {
  wireSearch();
  $('rp-season').addEventListener('change', () => {
    const season = +$('rp-season').value;
    setState({season});
    if ($('rp-search').value.trim()) $('rp-search').dispatchEvent(new Event('input'));
    if (cur) load({...cur, season});
  });
  $('rp-write').addEventListener('click', () => toggleForm());
  $('n-body').addEventListener('click', e => { if (e.target.closest('[data-action=write]')) toggleForm(true); });
  $('rp-form').addEventListener('input', () => { debounce('preview', preview, 250); saveDraftSoon(); });
  $('rp-form').addEventListener('change', () => { debounce('preview', preview, 50); saveDraftSoon(); });
  // owner 2026-11-13: Clear draft asks first, inline (no browser dialog)
  const draftConfirm = on => {
    $('rp-draft-clear').hidden = on; $('rp-draft-confirm').hidden = !on;
    (on ? $('rp-draft-no') : $('rp-draft-clear')).focus();
  };
  $('rp-draft-clear').addEventListener('click', () => draftConfirm(true));
  $('rp-draft-no').addEventListener('click', () => draftConfirm(false));
  $('rp-draft-yes').addEventListener('click', () => { draftConfirm(false); resetDraft(); });
  $('rp-draft-confirm').addEventListener('keydown', e => { if (e.key === 'Escape') draftConfirm(false); });
  window.addEventListener('pagehide', flushDraft);
  $('rp-dl').addEventListener('click', () => download(false));
  $('rp-dl-data').addEventListener('click', () => download(true));
  // availability rows: drawn at once, never posted (stopPropagation keeps them out of preview())
  const avail = $('f-avail');
  const redrawAvail = () => { if (view) drawAvail(view, availRows()); saveDraftSoon(); };
  avail.addEventListener('input', e => { e.stopPropagation(); redrawAvail(); });
  avail.addEventListener('change', e => e.stopPropagation());
  avail.addEventListener('click', e => {
    const b = e.target.closest('[data-action=av-del]');
    if (b) { b.closest('.rp-avrow').remove(); redrawAvail(); }
  });
  $('f-avail-add').addEventListener('click', () => addAvailRow());
  $('rp-photo-file').addEventListener('change', e => { pickPhoto(e.target.files[0]); e.target.value = ''; });
  $('rp-photo-del').addEventListener('click', () => { photo = null; showPhoto(); saveDraftSoon(); });
  onStateChange(s => { remember(); applyState(s); });
  restoreState('report');
  remember();
  applyState(readState());
}

wire();
