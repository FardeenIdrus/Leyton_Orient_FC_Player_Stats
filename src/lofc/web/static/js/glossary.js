// Glossary: every metric in the provider's own words (/api/glossary). The search runs here on
// that list -- name or definition, case-insensitive, as the Streamlit page's search does.
import {api, esc} from './common.js';

const $ = id => document.getElementById(id);
const html = t => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\n\n/g, '<br><br>').replace(/\n/g, '<br>');
let D = null;
const st = () => { const q = new URLSearchParams(location.search); return {q: q.get('q') || '', tab: q.get('tab') || ''}; };

function draw() {
  const {q, tab} = st();
  const needle = q.trim().toLowerCase();
  const hits = needle ? D.entries.filter(e => e.label.toLowerCase().includes(needle) || e.text.toLowerCase().includes(needle)) : D.entries;
  if ($('gl-q').value !== q) $('gl-q').value = q;
  const groups = D.groups.filter(g => hits.some(e => e.group === g));
  if (!groups.length) { $('gl-tabs').innerHTML = ''; $('gl-list').innerHTML = '<p class="note">No metric matches that search.</p>'; return; }
  const cur = groups.includes(tab) ? tab : groups[0];
  $('gl-tabs').innerHTML = groups.map(g => `<span role="tab" tabindex="0" data-g="${esc(g)}" aria-selected="${g === cur}" class="${g === cur ? 'on' : ''}">${esc(g)} <i>${hits.filter(e => e.group === g).length}</i></span>`).join('');
  $('gl-list').innerHTML = hits.filter(e => e.group === cur).map(e =>
    `<div class="gl-row"><div class="gl-head"><span class="gl-name">${esc(e.label)}</span>${e.in_rating ? '<span class="gl-tag">In rating</span>' : ''}<span class="gl-src">${esc(e.source)}</span></div><div class="gl-text">${html(e.text)}</div></div>`).join('');
}
function set(patch, replace) {
  const q = new URLSearchParams(location.search);
  for (const [k, v] of Object.entries(patch)) v ? q.set(k, v) : q.delete(k);
  const url = '/glossary' + (q.toString() ? '?' + q : '');
  history[replace ? 'replaceState' : 'pushState']({}, '', url);
  draw();
}
// One history entry per search: the first keystroke pushes, the rest of the same burst of
// typing replaces it (so Back leaves the search, not one letter).
let typing = 0;
$('gl-q').addEventListener('input', e => {
  const burst = typing > 0;
  clearTimeout(typing); typing = setTimeout(() => { typing = 0; }, 700);
  set({q: e.target.value}, burst);
});
$('gl-tabs').addEventListener('click', ev => { const t = ev.target.closest('[data-g]'); if (t) set({tab: t.dataset.g}); });
$('gl-tabs').addEventListener('keydown', ev => { const t = ev.target.closest('[data-g]'); if (t && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); set({tab: t.dataset.g}); } });
addEventListener('popstate', draw);
api('/api/glossary').then(d => { D = d; $('gl-intro').textContent = d.intro; draw(); })
  .catch(e => { $('gl-list').innerHTML = `<p class="note">Could not load (${esc(e.message)}).</p>`; });
