// Users page (admin only). Draws /api/users and sends the account actions; the server applies
// every rule (lofc.store.users, model.user_admin). Passwords are only ever sent, never shown.
import {api, esc} from './common.js';

const $ = id => document.getElementById(id);
let D = null, openId = null;

const flash = (text, ok = true) => {
  $('us-msg').innerHTML = text ? `<div class="${ok ? 'info' : 'notice'}">${esc(text)}</div>` : '';
};
const errOf = e => (e.body && (e.body.error || e.body.detail)) || e.message;

function drawList() {
  $('us-body').innerHTML = D.users.map(u =>
    `<tr data-action="open" data-id="${u.id}" tabindex="0" class="${u.id === openId ? 'on' : ''}" aria-label="Manage ${esc(u.username)}">`
    + `<td><b>${esc(u.username)}</b></td><td>${esc(u.full_name)}</td><td>${esc(u.role_label)}</td>`
    + `<td class="${u.active ? '' : 'tag-off'}">${esc(u.status)}</td><td class="${u.locked ? 'tag-lock' : 'dim'}">${esc(u.lockout)}</td>`
    + `<td>${esc(u.created)}</td></tr>`).join('') || '<tr><td colspan="6" class="note">No accounts yet.</td></tr>';
}

function drawPanel() {
  const u = D.users.find(x => x.id === openId);
  $('us-panel').hidden = !u;
  document.querySelector('.us-layout').classList.toggle('open', !!u);
  if (!u) return;
  $('us-panel').innerHTML =
    `<button type="button" class="btn small x" data-action="close" aria-label="Close">✕</button>`
    + `<h2>${esc(u.full_name)}</h2><div class="note">@${esc(u.username)} · ${esc(u.role_label)} · ${esc(u.status)} · created ${esc(u.created)}</div>`
    + `<div class="sec"><h3>Reset password</h3><p class="note">Clears any lockout. They change it at their next sign-in.</p>`
    + `<form id="p-reset" autocomplete="off"><div class="f"><label for="p-pw">New temporary password</label><input class="ctl" id="p-pw" type="password" autocomplete="new-password" required></div>`
    + `<div class="f"><label for="p-pw2">Confirm</label><input class="ctl" id="p-pw2" type="password" autocomplete="new-password" required></div>`
    + `<button class="btn primary" type="submit">Reset password</button></form></div>`
    + `<div class="sec"><h3>Lockout</h3>` + (u.locked
      ? `<div>${esc(u.lockout)}</div><button type="button" class="btn" data-action="unlock">Clear lockout</button>`
      : '<div class="note">Not locked.</div>') + '</div>'
    + `<div class="sec"><h3>Account status</h3>` + (u.active
      ? (u.deactivate_reason ? `<div class="warn">${esc(u.deactivate_reason)}</div>` : '<p class="note">Blocks sign-in. Past assessments stay attributed.</p>')
        + `<button type="button" class="btn" data-action="deactivate"${u.can_deactivate ? '' : ' disabled'}>Deactivate account</button>`
      : `<p class="note">Cannot sign in. Past assessments stay attributed.</p><button type="button" class="btn primary" data-action="reactivate">Reactivate account</button>`)
    + '</div>';
  $('p-reset').addEventListener('submit', async ev => {
    ev.preventDefault();
    await act(`/api/users/${u.id}/reset`, {password: $('p-pw').value, confirm: $('p-pw2').value});
  });
}

async function load() {
  D = await api('/api/users');
  if (!$('c-role').options.length) $('c-role').innerHTML = D.roles.map(r => `<option value="${esc(r)}">${esc(D.role_labels[r] || r)}</option>`).join('');
  drawList(); drawPanel();
}

async function act(url, json) {
  try {
    const r = await api(url, {method: 'POST', json: json ?? {}});
    flash(r.message);
    await load();
    return true;
  } catch (e) {
    flash(errOf(e), false);
    return false;
  }
}

$('us-new').addEventListener('click', () => {
  openId = null; drawList(); drawPanel();
  const f = $('us-create'), open = f.hidden;
  f.hidden = !open; $('us-new').setAttribute('aria-expanded', String(open));
  if (open) $('c-username').focus();
});
$('c-cancel').addEventListener('click', () => { $('us-create').hidden = true; $('us-new').setAttribute('aria-expanded', 'false'); });
$('us-create').addEventListener('submit', async ev => {
  ev.preventDefault();
  const ok = await act('/api/users', {username: $('c-username').value, full_name: $('c-name').value,
    role: $('c-role').value, password: $('c-pw').value, confirm: $('c-pw2').value});
  if (ok) { $('us-create').reset(); $('us-create').hidden = true; $('us-new').setAttribute('aria-expanded', 'false'); }
});
const openRow = tr => { openId = +tr.dataset.id; flash(''); drawList(); drawPanel(); };
$('us-body').addEventListener('click', ev => { const tr = ev.target.closest('tr[data-id]'); if (tr) openRow(tr); });
$('us-body').addEventListener('keydown', ev => { const tr = ev.target.closest('tr[data-id]'); if (tr && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); openRow(tr); } });
$('us-panel').addEventListener('click', ev => {
  const b = ev.target.closest('[data-action]'); if (!b) return;
  const a = b.dataset.action;
  if (a === 'close') { openId = null; drawList(); drawPanel(); }
  else if (a === 'unlock') act(`/api/users/${openId}/unlock`);
  else if (a === 'deactivate') act(`/api/users/${openId}/active`, {active: false});
  else if (a === 'reactivate') act(`/api/users/${openId}/active`, {active: true});
});
document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && openId != null) { openId = null; drawList(); drawPanel(); } });
load().catch(e => flash(`Could not load the accounts (${errOf(e)}).`, false));
