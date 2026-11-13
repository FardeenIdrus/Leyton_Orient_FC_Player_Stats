// Remembered page settings (owner 2026-11-13): the shared helper in static/js/common.js.
// Run on the Mac (node is not in the container):  node --test tests/js/
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {stateToKeep, rememberState, recallState, restoreState, lastKey} from '../../src/lofc/web/static/js/common.js';

const memStore = () => { const m = new Map(); return {m, getItem: k => m.has(k) ? m.get(k) : null, setItem: (k, v) => m.set(k, String(v))}; };
const brokenStore = {getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }};
const fakeHistory = () => ({calls: [], state: null, replaceState(st, t, url) { this.calls.push(url); }});

test('key per page', () => {
  assert.equal(lastKey('players'), 'lofc.players.last');
  assert.equal(lastKey('compare'), 'lofc.compare.last');      // Compare's existing key is kept
});

test('stateToKeep drops back by default, and the named params', () => {
  assert.equal(stateToKeep('?position=Winger&back=%2Fplayers'), '?position=Winger');
  assert.equal(stateToKeep('?open=1-2&status=A', {drop: ['open']}), '?status=A');
  assert.equal(stateToKeep('?back=x'), '');
  assert.equal(stateToKeep(''), '');
});

test('stateToKeep keep-list keeps only those (repeated params too)', () => {
  assert.equal(stateToKeep('?player=1&competition=5&season=318&position=Winger', {keep: ['season', 'position']}),
               '?season=318&position=Winger');
  assert.equal(stateToKeep('?leagues=A&leagues=B&x=1', {keep: ['leagues']}), '?leagues=A&leagues=B');
});

test('remember then recall', () => {
  const s = memStore();
  rememberState('players', {search: '?position=Winger&back=y', store: s});
  assert.equal(s.m.get('lofc.players.last'), '?position=Winger');
  assert.equal(recallState('players', {store: s}), '?position=Winger');
  assert.equal(recallState('physical', {store: s}), '');
});

test('defaults are remembered as empty (back to the defaults sticks)', () => {
  const s = memStore();
  rememberState('players', {search: '?position=Winger', store: s});
  rememberState('players', {search: '', store: s});
  assert.equal(recallState('players', {store: s}), '');
});

test('recall ignores junk', () => {
  const s = memStore(); s.setItem('lofc.players.last', 'javascript:alert(1)');
  assert.equal(recallState('players', {store: s}), '');
});

test('storage off or throwing: nothing breaks, nothing restored', () => {
  rememberState('players', {search: '?a=1', store: null});
  rememberState('players', {search: '?a=1', store: brokenStore});
  assert.equal(recallState('players', {store: null}), '');
  assert.equal(recallState('players', {store: brokenStore}), '');
  const h = fakeHistory();
  assert.equal(restoreState('players', {store: brokenStore, loc: {pathname: '/players', search: '', hash: ''}, hist: h}), false);
  assert.equal(h.calls.length, 0);
});

test('a bare URL restores the saved query without a history entry', () => {
  const s = memStore(); s.setItem('lofc.players.last', '?position=Winger');
  const h = fakeHistory();
  assert.equal(restoreState('players', {store: s, loc: {pathname: '/players', search: '', hash: ''}, hist: h}), true);
  assert.deepEqual(h.calls, ['/players?position=Winger']);
});

test('a URL with a query wins: nothing restored', () => {
  const s = memStore(); s.setItem('lofc.players.last', '?position=Winger');
  const h = fakeHistory();
  assert.equal(restoreState('players', {store: s, loc: {pathname: '/players', search: '?position=Full+Back', hash: ''}, hist: h}), false);
  assert.equal(h.calls.length, 0);
});

test('nothing saved: a bare URL stays bare', () => {
  const h = fakeHistory();
  assert.equal(restoreState('players', {store: memStore(), loc: {pathname: '/players', search: '', hash: ''}, hist: h}), false);
  assert.equal(h.calls.length, 0);
});
