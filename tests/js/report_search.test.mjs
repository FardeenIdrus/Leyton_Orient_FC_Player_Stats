// Report: the season's player list, filtered in the browser (owner 2026-11-13).
// Run on the Mac:  node --test tests/js/
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {foldQuery, filterRows, rowText, PAGE} from '../../src/lofc/web/static/js/report_search.js';

// [player_id, competition_id, name, position, club, league, key] -- key = the server's fold
const ROWS = [
  [2, 4, 'Aaron Ball', 'Centre Back', 'Club A', 'League One', 'aaronballclubacentrebackleagueone'],
  [1, 4, 'Nathaniel Méndez-Laing', 'Winger', 'Club M', 'League One', 'nathanielmendezlaingclubmwingerleagueone'],
  [3, 5, "Sean O'Connor", 'Winger', 'Club Z', null, 'seanoconnorclubzwinger'],
];

test('the query folds like the server (accents, case, punctuation)', () => {
  assert.equal(foldQuery("  Méndez-LAING "), 'mendezlaing');
  assert.equal(foldQuery("O'Connor"), 'oconnor');
  assert.equal(foldQuery(''), '');
});

test('empty query: every row, in the given A-Z order', () => {
  assert.deepEqual(filterRows(ROWS, '').map(r => r[0]), [2, 1, 3]);
});

test('typing filters the same list', () => {
  assert.deepEqual(filterRows(ROWS, 'mendez').map(r => r[0]), [1]);
  assert.deepEqual(filterRows(ROWS, 'Winger').map(r => r[0]), [1, 3]);
  assert.deepEqual(filterRows(ROWS, "oconnor").map(r => r[0]), [3]);
  assert.deepEqual(filterRows(ROWS, 'zzz'), []);
});

test('a row reads name · position · club · league', () => {
  assert.equal(rowText(ROWS[0]), 'Aaron Ball · Centre Back · Club A · League One');
  assert.equal(rowText(ROWS[2]), "Sean O'Connor · Winger · Club Z · —");
});

test('rows are drawn a page at a time', () => { assert.ok(PAGE >= 100 && PAGE <= 300); });
