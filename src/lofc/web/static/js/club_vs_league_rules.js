// Club vs League One: the page's pure display rules (no DOM), so they can be checked on their own.

// Ordinals are for league ranks only ("23rd").
export const ord = n => n + ({1: 'st', 2: 'nd', 3: 'rd'}[(n % 100 >= 11 && n % 100 <= 13) ? 0 : n % 10] || 'th');

// A percentile is a plain number (100 = best): green 70+, red below 30, neutral otherwise.
// owner 2026-11-13: Gap closed shows as "94%" ("—" stays)
export const pctSign = p => p == null ? '<span class="cv-pct none">—</span>' : `<span class="cv-pct">${p}%</span>`;
export const pct = p => p == null ? '<span class="cv-pct none">—</span>'
  : `<span class="cv-pct${p >= 70 ? ' hi' : p < 30 ? ' lo' : ''}">${p}</span>`;

// Leagues picker (owner 2026-11-10): the selection is remembered on this computer.
export const STORE_KEY = 'lofc.cvl.leagues';

export function loadLeagues(store) {
  try {
    const v = JSON.parse(store.getItem(STORE_KEY));
    return Array.isArray(v) && v.length ? v.map(Number).filter(Number.isFinite) : null;
  } catch (e) { return null; }
}

export function saveLeagues(store, ids) {
  try { store.setItem(STORE_KEY, JSON.stringify(ids)); } catch (e) { /* storage unavailable: not remembered */ }
}

// `available`: league ids with candidates, in the API's order (England's first). `stored`: the
// remembered ids or null. Leagues with no candidates are skipped; if none remain, the default.
// A league named in the URL is always shown and active.
export function pickLeagues(available, stored, urlLeague, defaults) {
  const has = new Set(available);
  let chosen = new Set((stored || []).filter(id => has.has(id)));
  if (!chosen.size) chosen = new Set(defaults.filter(id => has.has(id)));
  if (!chosen.size && available.length) chosen = new Set([available[0]]);
  const url = Number(urlLeague);
  if (urlLeague && has.has(url)) chosen.add(url);
  const tabs = available.filter(id => chosen.has(id));
  return {tabs, active: urlLeague && has.has(url) ? url : (tabs.length ? tabs[0] : null)};
}

export const pickerText = (ids, names) => `${ids.length} selected: ${ids.map(id => names[id]).join(', ')}`;
