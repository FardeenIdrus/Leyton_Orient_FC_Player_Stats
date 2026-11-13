// Report page: the writer's draft, kept in this browser per player-season (owner 2026-11-13).
// Pure rules, no DOM: the storage is passed in, so the page works without it (private window,
// blocked storage) and the rules can be checked on their own. Never sent to the server.

export const DRAFT_PREFIX = 'lofc.report.draft.';
export const PHOTO_DROPPED = 'Photo not kept — too large to save';

export const draftKey = ids => `${DRAFT_PREFIX}${ids.player}-${ids.competition}-${ids.season}`;

/** True when the draft holds any of the writer's work. */
export function hasWork(d) {
  if (!d || typeof d !== 'object') return false;
  const some = o => !!o && Object.values(o).some(v => v != null && String(v).trim() !== '');
  return some(d.text) || some(d.psych) || some(d.med) || (d.mband != null && d.mband !== '')
    || (Array.isArray(d.avail) && d.avail.length > 0) || !!d.photo;
}

/** The stored draft for this player-season, or null (none, unreadable or no storage). */
export function readDraft(store, ids) {
  try {
    const d = JSON.parse(store.getItem(draftKey(ids)));
    return d && typeof d === 'object' && !Array.isArray(d) ? d : null;
  } catch (e) {
    return null;
  }
}

/** Save it; an empty draft is removed. Returns '' when saved, PHOTO_DROPPED when it was saved
 *  without the photo (over the browser's storage quota), 'unsaved' when nothing could be kept. */
export function writeDraft(store, ids, d) {
  const key = draftKey(ids);
  try {
    if (!hasWork(d)) { store.removeItem(key); return ''; }
    try {
      store.setItem(key, JSON.stringify(d));
      return '';
    } catch (e) {
      if (!d.photo) throw e;
      const rest = {...d, photo: null};
      if (!hasWork(rest)) { store.removeItem(key); return PHOTO_DROPPED; }
      store.setItem(key, JSON.stringify(rest));
      return PHOTO_DROPPED;
    }
  } catch (e) {
    return 'unsaved';
  }
}

export function clearDraft(store, ids) {
  try { store.removeItem(draftKey(ids)); } catch (e) { /* no storage: nothing kept */ }
}
