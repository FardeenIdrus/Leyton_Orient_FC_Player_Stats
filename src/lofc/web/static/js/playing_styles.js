// "How playing styles work": the Streamlit page's content, per position, from /api/playing-styles.
import {api, esc} from './common.js';

const $ = id => document.getElementById(id);
const md = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
const group0 = () => new URLSearchParams(location.search).get('group') || '';
let drawnStatic = false;

async function load(group, push) {
  const d = await api('/api/playing-styles' + (group ? '?group=' + encodeURIComponent(group) : ''));
  if (push) history.pushState({}, '', '/playing-styles?group=' + encodeURIComponent(d.group));
  if (!drawnStatic) {
    $('ps-steps').innerHTML = d.steps.map(s => `<div class="ps-step"><b class="n">${esc(s.title)}</b>${md(s.text)}</div>`).join('');
    $('ps-labels').innerHTML = d.labels.map(l => `<div class="ps-label"><span class="ps-pill ${esc(l.kind)}">${esc(l.pill)}</span><span class="t">${esc(l.title)}</span>${esc(l.text)}</div>`).join('');
    drawnStatic = true;
  }
  $('ps-group').innerHTML = d.groups.map(g =>
    `<button type="button" data-g="${esc(g)}" class="${g === d.group ? 'on' : ''}" aria-pressed="${g === d.group}">${esc(g)}</button>`).join('');
  const ex = d.example;
  $('ps-example-card').hidden = !ex;
  if (ex) {
    $('ps-ex-h').textContent = `Example: "${ex.style}", League One, ${ex.season}`;
    $('ps-ex').innerHTML = '<thead><tr><th>Player</th>' + ex.signals.map(s => `<th>${esc(s)}</th>`).join('') + '<th>Fit</th><th>Label</th></tr></thead><tbody>'
      + ex.rows.map(r => `<tr><td class="m">${esc(r.name)}<div class="sub">${esc(r.team)}</div></td>`
        + r.pcts.map(p => `<td>${esc(p)}th percentile</td>`).join('')
        + `<td class="m">${esc(r.fit)}</td><td><span class="ps-pill ${r.tier === 'Strong' ? 's' : 'l'}">${esc(ex.style)}</span>${r.tier === 'Strong' ? '' : ' leans'}</td></tr>`).join('') + '</tbody>';
    $('ps-ex-note').textContent = 'Fit = the average of the percentiles. ' + ex.rows.map(r => `${r.name}: fit ${r.fit} → ${r.tier}`).join(' · ') + '.';
  }
  const T = d.table, cls = c => c === 'Style' ? 'm' : c === 'Label' ? 'g' : '';
  $('ps-table').innerHTML = '<thead><tr>' + T.columns.map(c => `<th>${esc(c)}</th>`).join('') + '</tr></thead><tbody>'
    + T.rows.map(r => '<tr>' + r.map((v, i) => `<td class="${cls(T.columns[i])}">${esc(v)}</td>`).join('') + '</tr>').join('') + '</tbody>';
}

$('ps-group').addEventListener('click', ev => { const b = ev.target.closest('button[data-g]'); if (b) load(b.dataset.g, true); });
addEventListener('popstate', () => load(group0(), false));
load(group0(), false).catch(e => { $('ps-steps').innerHTML = `<p class="note">Could not load (${esc(e.message)}).</p>`; });
