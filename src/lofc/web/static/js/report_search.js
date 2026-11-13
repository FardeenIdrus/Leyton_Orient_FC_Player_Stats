// Report: the season's player list (owner 2026-11-13), as pure rules so they can be checked on
// their own. Rows come from /api/report/players, A-Z: [player_id, competition_id, name,
// position, club, league, key]; `key` is the server's fold of the search label.

export const PAGE = 200;            // rows drawn at a time; more as the list scrolls

/** The server's fold (dashboard/search.py::fold): no accents, lower case, letters and digits. */
export const foldQuery = q => String(q || '').normalize('NFKD').replace(/\p{M}/gu, '')
  .toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');

/** Rows whose key holds the folded query; every row for an empty one. Order kept (A-Z). */
export function filterRows(rows, q) {
  const f = foldQuery(q);
  return f ? rows.filter(r => r[6].includes(f)) : rows;
}

export const rowText = r => `${r[2]} · ${r[3]} · ${r[4]} · ${r[5] || '—'}`;
