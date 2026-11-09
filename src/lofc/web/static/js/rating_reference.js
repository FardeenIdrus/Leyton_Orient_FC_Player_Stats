// "What goes into each rating": the Streamlit page's table, per position, from /api/rating-reference.
import {api, esc} from './common.js';

const $ = id => document.getElementById(id);
const pos0 = () => new URLSearchParams(location.search).get('position') || '';

async function load(position, push) {
  const d = await api('/api/rating-reference' + (position ? '?position=' + encodeURIComponent(position) : ''));
  if (push) history.pushState({}, '', '/rating-reference?position=' + encodeURIComponent(d.position));
  $('rr-pos').innerHTML = d.positions.map(p =>
    `<button type="button" data-p="${esc(p)}" class="${p === d.position ? 'on' : ''}" aria-pressed="${p === d.position}">${esc(p)}</button>`).join('');
  $('rr-line').innerHTML = `${esc(d.weights_line)}<span>${esc(d.scale)}</span>`;
  // "Counts towards" becomes the section headings (Performance, then Physical)
  const ci = d.columns.indexOf('Counts towards');
  const cols = d.columns.filter((_, i) => i !== ci);
  const wide = c => c === "How it's measured" ? 'how' : c === 'Metric' ? 'm' : 'w';
  let body = '', last = null;
  for (const r of d.rows) {
    if (r[ci] !== last) { last = r[ci]; body += `<tr class="sec"><td colspan="${cols.length}">${esc(last)}</td></tr>`; }
    body += '<tr>' + r.filter((_, i) => i !== ci).map((v, j) => `<td class="${wide(cols[j])}">${esc(v)}</td>`).join('') + '</tr>';
  }
  $('rr-table').innerHTML = '<thead><tr>' + cols.map(c => `<th class="${wide(c) === 'w' ? 'w' : ''}">${esc(c)}</th>`).join('') + '</tr></thead><tbody>' + body + '</tbody>';
  $('rr-note').hidden = !d.note; $('rr-note').textContent = d.note || '';
}

$('rr-pos').addEventListener('click', ev => { const b = ev.target.closest('button[data-p]'); if (b) load(b.dataset.p, true); });
addEventListener('popstate', () => load(pos0(), false));
load(pos0(), false).catch(e => { $('rr-line').textContent = `Could not load (${e.message}).`; });
