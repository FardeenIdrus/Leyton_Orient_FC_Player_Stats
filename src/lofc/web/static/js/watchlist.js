// Watchlist page (owner 2026-11-23 redesign). Fetches /api/watchlist and draws it; computes no
// number. One shared list, one entry per player, grouped by position with our best (League One)
// for reference only. Edits save as they are made (stage, owner, next step, due date, notes,
// optional drop reason). Filters and the open player live in the URL.
import {api, esc, chip, readState, writeState, rememberState, restoreState} from './common.js';

const $ = id => document.getElementById(id);
let D = null;                     // last payload
let st = {};                      // stage, pos, owner, q, sugg, open

const VCLS = {'Sign': 'sign', 'Monitor Priority': 'pri', 'Monitor': 'mon', "Don't sign": 'no'};
const verdict = v => v ? `<span class="vd ${VCLS[v] || ''}">${esc(v)}</span>` : '<span class="note">—</span>';
const lg = r => r.league_abbr ? `<span class="lg" title="${esc(r.league || '')}">${esc(r.league_abbr)}</span>` : '';
// a player link carries the way back to this list (the card's "← Back")
const backQ = () => '?back=' + encodeURIComponent('/watchlist' + location.search);
const href = h => esc(h + backQ());
const opt = (v, label, cur) => `<option value="${esc(v)}"${String(v) === String(cur) ? ' selected' : ''}>${esc(label)}</option>`;

function readSt() {
  const q = readState();
  st = {stage: q.stage || '', pos: q.pos || '', owner: q.owner || '', q: q.q || '', sugg: q.sugg === 'all' ? 'all' : '',
        open: q.open || ''};
}

function save(patch, {replace = true} = {}) {
  Object.assign(st, patch);
  const keep = Object.fromEntries(Object.entries(st).map(([k, v]) => [k, v || null]));
  writeState(keep, {replace});
  rememberState('watchlist', {drop: ['open']});
}

// ---- drawing ------------------------------------------------------------------------------
function drawTiles() {
  $('wl-tiles').innerHTML = D.tiles.map(t => {
    const on = (t.key === 'Shortlisted' && st.stage === 'Shortlisted');
    const click = t.key === 'Shortlisted' || t.key === 'active';
    return `<div class="tile${on ? ' on' : ''}${click ? ' click' : ''}" data-tile="${esc(t.key)}"><div class="k">${esc(t.label)}</div><div class="v">${t.value}</div></div>`;
  }).join('');
}

function drawSugg() {
  const S = D.suggestions;
  $('wl-sugg').hidden = !S.count_all;
  $('wl-sugg-win').innerHTML = [['', `Last 30 days (${S.count_30})`], ['all', `All (${S.count_all})`]]
    .map(([k, l]) => `<button type="button" data-win="${k}" class="${(st.sugg || '') === k ? 'on' : ''}" aria-pressed="${(st.sugg || '') === k}">${esc(l)}</button>`).join('');
  $('wl-sugg-body').innerHTML = S.rows.length ? S.rows.map(r => `<tr>
      <td class="pc">${r.href ? `<a class="plink" href="${href(r.href)}"><b>${esc(r.name)}</b></a>` : `<b>${esc(r.name)}</b>`}
        <div class="note">${esc(r.club || '—')}${lg(r)}${r.position ? ' · ' + esc(r.position) : ''}</div></td>
      <td class="n">${r.overall == null ? '<span class="note">—</span>' : chip(r.overall)}</td>
      <td>${verdict(r.verdict)}</td><td class="note">${esc(r.report)}</td>
      <td class="n act"><button type="button" class="btn small primary" data-add="${r.report_id}">Add</button>
        <button type="button" class="btn small" data-dismiss="${r.report_id}">Dismiss</button></td></tr>`).join('')
    : `<tr><td class="note">Nothing new in the last 30 days.</td></tr>`;
}

function rowMatches(r) {
  if (st.stage && r.stage !== st.stage) return false;
  if (st.owner === 'none' ? r.owner_id != null : (st.owner && String(r.owner_id) !== st.owner)) return false;
  if (st.q && !`${r.name} ${r.club || ''}`.toLowerCase().includes(st.q.toLowerCase())) return false;
  return true;
}

function stageSelect(r) {
  return `<select class="ctl stage st-${esc(r.stage.replace(/\s+/g, '-').toLowerCase())}" data-field="stage" aria-label="Stage for ${esc(r.name)}">`
    + D.stages.map(s => opt(s, s, r.stage)).join('') + '</select>';
}

function detail(r) {
  const users = [opt('', '—', r.owner_id ?? ''), ...D.users.map(u => opt(u.id, u.name, r.owner_id ?? ''))].join('');
  return `<tr class="wl-det" data-p="${r.player_id}"><td colspan="7"><div class="wl-dgrid">
      <div class="f"><label>Owner</label><select class="ctl" data-field="owner">${users}</select></div>
      <div class="f"><label>Next step</label><input class="ctl" data-field="next_step" value="${esc(r.next_step || '')}" placeholder="e.g. Watch vs Crewe" maxlength="120"></div>
      <div class="f"><label>Due</label><input class="ctl" type="date" data-field="due" value="${esc(r.due || '')}"></div>
      ${r.stage === 'Dropped' ? `<div class="f"><label>Reason (optional)</label><input class="ctl" data-field="drop_reason" value="${esc(r.drop_reason)}" maxlength="120"></div>` : '<div></div>'}
      <div class="f wide"><label>Notes <span class="note">· shared with the department${r.note_meta ? ' · last edit ' + esc(r.note_meta) : ''}</span></label>
        <textarea class="ctl" data-field="note" rows="3" placeholder="What to check, who saw him…">${esc(r.note)}</textarea></div>
      <div class="wl-dfoot"><span class="note">Added ${esc(r.added)}${r.contract ? ' · contract to ' + esc(r.contract) : ''}</span>
        <span class="wl-saved note" aria-live="polite"></span>
        ${r.href ? `<a class="btn small" href="${href(r.href)}">Open player page →</a>` : ''}
        <button type="button" class="btn small" data-remove="${r.player_id}">Remove from list</button></div>
    </div></td></tr>`;
}

function row(r) {
  const open = String(r.player_id) === st.open;
  return `<tr class="wr${open ? ' open' : ''}" data-p="${r.player_id}">
      <td class="pc"><span class="chev">${open ? '▾' : '▸'}</span>${r.href ? `<a class="plink" href="${href(r.href)}"><b>${esc(r.name)}</b></a>` : `<b>${esc(r.name)}</b>`}
        <div class="note">${esc(r.club || '—')}${lg(r)} · ${esc(r.position || '—')}${r.age != null ? ' · ' + r.age : ''}</div></td>
      <td class="c">${r.overall == null ? '<span class="note">—</span>' : chip(r.overall)}</td>
      <td>${stageSelect(r)}</td>
      <td>${verdict(r.verdict)}</td>
      <td class="nx">${r.next_step ? esc(r.next_step) : '<span class="note">—</span>'}<div class="note">${esc(r.owner || '')}</div></td>
      <td class="${r.overdue ? 'due over' : 'due'}">${esc(r.due_text || '—')}</td>
      <td class="note">${esc(r.contract || '—')}</td></tr>` + (open ? detail(r) : '');
}

// the same fixed columns in every group, so the groups line up under each other
const COLS = '<colgroup><col class="c-pl"><col class="c-ov"><col class="c-st"><col class="c-vd"><col class="c-nx"><col class="c-du"><col class="c-co"></colgroup>';
const HEAD = COLS + '<thead><tr><th>Player</th><th class="c">Overall</th><th>Stage</th><th>Scout verdict</th><th>Next step</th><th>Due</th><th>Contract</th></tr></thead>';

function drawList() {
  const groups = D.groups.filter(g => !st.pos || g.group === st.pos)
    .map(g => ({...g, rows: g.rows.filter(rowMatches)})).filter(g => g.rows.length);
  $('wl-empty').hidden = !!groups.length;
  $('wl-empty').textContent = D.empty ? D.text : 'No players match these filters.';
  $('wl-groups').innerHTML = groups.map(g => `<div class="wl-gh"><b>${esc(g.label)} <span class="note">${g.rows.length}</span></b>`
      + (g.our_best ? `<span class="note">Our best: ${esc(g.our_best.name)} ${chip(g.our_best.rating)} <span class="lg">L1</span></span>` : '')
      + `</div><div class="tw"><table class="wl-t">${HEAD}<tbody>${g.rows.map(row).join('')}</tbody></table></div>`).join('');
  const closed = D.closed.filter(rowMatches);
  $('wl-closed').hidden = !D.closed.length;
  $('wl-closed-h').textContent = `Dropped and signed (${D.closed.length})`;
  $('wl-closed-body').innerHTML = closed.map(row).join('');
  $('wl-closed-body').closest('table').querySelector('colgroup') || $('wl-closed-body').insertAdjacentHTML('beforebegin', COLS);
}

function drawFeed() {
  $('wl-feed').innerHTML = D.changes.length ? D.changes.map(c =>
    `<li><span class="ic ${esc(c.kind)}"></span><span><b>${esc(c.name)}</b> ${c.kind === 'rating'
      ? esc(c.text.split(' ')[0]) + ` <span class="${c.dir === 'up' ? 'up' : 'dn'}">${esc(c.text.split(' ').slice(1).join(' '))}</span>`
      : esc(c.text)}</span></li>`).join('')
    : '<li class="note">Nothing new since the players were added.</li>';
}

function drawFilters() {
  $('f-stage').innerHTML = opt('', 'All active', st.stage) + D.active_stages.map(s => opt(s, s, st.stage)).join('');
  $('f-pos').innerHTML = opt('', 'All', st.pos) + D.groups.map(g => opt(g.group, g.label, st.pos)).join('');
  $('f-owner').innerHTML = opt('', 'Anyone', st.owner) + opt('none', 'Unassigned', st.owner)
    + D.users.map(u => opt(u.id, u.name, st.owner)).join('');
  if (document.activeElement !== $('f-q')) $('f-q').value = st.q;
}

function draw() {
  drawTiles(); drawSugg(); drawFilters(); drawList(); drawFeed();
}

async function load() {
  D = await api('/api/watchlist' + (st.sugg === 'all' ? '?sugg=all' : ''));
  draw();
}

// ---- saving -------------------------------------------------------------------------------
function flash(p, text) {
  const el = document.querySelector(`tr.wl-det[data-p="${p}"] .wl-saved`);
  if (el) { el.textContent = text; setTimeout(() => { if (el.textContent === text) el.textContent = ''; }, 1600); }
}

async function saveField(p, field, value) {
  const body = {[field]: field === 'owner' ? (value ? Number(value) : null) : value};
  try {
    await api('/api/watchlist/' + p, {json: body});
    if (field === 'note' || field === 'next_step' || field === 'drop_reason' || field === 'due' || field === 'owner') {
      const keep = document.activeElement;
      D = await api('/api/watchlist' + (st.sugg === 'all' ? '?sugg=all' : ''));
      drawTiles(); drawList(); drawFeed();
      if (keep && keep.dataset && keep.dataset.field) {
        const again = document.querySelector(`tr.wl-det[data-p="${p}"] [data-field="${keep.dataset.field}"]`);
        if (again && again !== keep) again.focus();
      }
    } else {
      await load();
    }
    flash(p, 'Saved');
  } catch (e) {
    flash(p, `Not saved (${e.status || e.message})`);
  }
}

function bind() {
  $('wl-tiles').addEventListener('click', e => {
    const t = e.target.closest('[data-tile]'); if (!t) return;
    const key = t.dataset.tile;
    if (key === 'Shortlisted') save({stage: st.stage === 'Shortlisted' ? '' : 'Shortlisted'}, {replace: false});
    else if (key === 'active') save({stage: ''}, {replace: false});
    else return;
    draw();
  });
  $('wl-sugg-win').addEventListener('click', e => {
    const b = e.target.closest('[data-win]'); if (!b) return;
    save({sugg: b.dataset.win}, {replace: false}); load();
  });
  $('wl-sugg-body').addEventListener('click', async e => {
    const a = e.target.closest('[data-add]'), d = e.target.closest('[data-dismiss]');
    const id = (a || d) && (a || d).dataset[a ? 'add' : 'dismiss'];
    if (!id) return;
    (a || d).disabled = true;
    try { await api('/api/watchlist/suggestions/' + id, {json: {action: a ? 'add' : 'dismiss'}}); } catch { /* reload shows the state */ }
    load();
  });
  for (const [id, key] of [['f-stage', 'stage'], ['f-pos', 'pos'], ['f-owner', 'owner']])
    $(id).addEventListener('change', e => { save({[key]: e.target.value}, {replace: false}); drawList(); });
  $('f-q').addEventListener('input', e => { save({q: e.target.value}); drawList(); });

  const list = e => e.target.closest('#wl-groups, #wl-closed-body');
  document.addEventListener('click', e => {
    if (!list(e)) return;
    const rm = e.target.closest('[data-remove]');
    if (rm) return remove(rm.dataset.remove);
    const tr = e.target.closest('tr.wr');
    if (!tr || e.target.closest('a, select, button, input, textarea')) return;
    save({open: st.open === tr.dataset.p ? '' : tr.dataset.p}, {replace: false});
    drawList();
  });
  document.addEventListener('change', e => {
    if (!list(e)) return;
    const f = e.target.closest('[data-field]'); if (!f) return;
    const p = f.closest('tr[data-p]').dataset.p;
    saveField(p, f.dataset.field, f.value);
  });
}

async function remove(p) {
  const r = [...D.groups.flatMap(g => g.rows), ...D.closed].find(x => String(x.player_id) === String(p));
  const ids = r && r.href ? r.href.split('/').slice(2) : [p, 0, 0];
  try { await api(`/api/card/${ids.join('/')}/watchlist`, {json: {action: 'remove'}}); } catch { /* reload shows it */ }
  save({open: ''});
  load();
}

restoreState('watchlist');
readSt();
bind();
load();
window.addEventListener('popstate', () => { readSt(); draw(); });
