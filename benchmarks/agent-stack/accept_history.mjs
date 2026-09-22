import test from 'node:test';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const { GestureHistory: H } = await import(pathToFileURL(process.env.CANDIDATE + '/history.mjs'));
const move = (h, value) => { h.begin(1); h.update(1, value); h.commit(1); };
test('pointer ownership and nested begin', () => {
  const h = new H({x: 0}); assert.equal(h.begin(1), true); assert.equal(h.begin(2), false);
  assert.equal(h.update(2, {x: 9}), false); assert.equal(h.commit(2), false); assert.equal(h.cancel(2), false);
  h.update(1, {x: 2}); assert.equal(h.commit(1), true); assert.deepEqual(h.state, {x: 2});
});
test('one undo step per gesture; previews and cancel', () => {
  const h = new H({x: 0}); h.begin(2); h.update(2, {x: 1}); h.update(2, {x: 2});
  assert.deepEqual(h.state, {x: 2}); h.commit(2); h.undo(); assert.deepEqual(h.state, {x: 0}); assert.equal(h.undo(), false);
  h.redo(); h.begin(3); h.update(3, {x: 9}); h.cancel(3); assert.deepEqual(h.state, {x: 2});
});
test('cancel and no-op preserve redo including key order', () => {
  const h = new H({x: 0, y: [1, 2]}); move(h, {x: 1}); h.undo();
  h.begin(1); h.update(1, {x: 9}); h.cancel(1); h.begin(2); h.update(2, {y: [1, 2], x: 0});
  assert.equal(h.commit(2), true); assert.equal(h.redo(), true); assert.deepEqual(h.state, {x: 1});
  h.undo(); assert.deepEqual(h.state, {x: 0, y: [1, 2]}); assert.equal(h.undo(), false);
});
test('changed commit invalidates redo', () => {
  const h = new H({x: 0}); move(h, {x: 1}); h.undo(); move(h, {x: 2});
  assert.equal(h.redo(), false); h.undo(); assert.deepEqual(h.state, {x: 0});
});
test('undo and redo cannot interrupt drag', () => {
  const h = new H({x: 0}); move(h, {x: 1}); move(h, {x: 2}); h.undo();
  h.begin(5); h.update(5, {x: 99}); assert.equal(h.undo(), false); assert.equal(h.redo(), false);
  assert.deepEqual(h.state, {x: 99}); h.cancel(5); assert.deepEqual(h.state, {x: 1});
  assert.equal(h.redo(), true); assert.deepEqual(h.state, {x: 2});
});
test('deep isolation at all document boundaries', () => {
  const original = {nested: [{x: 0}]}; const h = new H(original); original.nested[0].x = 50;
  assert.deepEqual(h.state, {nested: [{x: 0}]}); h.state.nested[0].x = 40;
  const next = {nested: [{x: 1}]}; h.begin(1); h.update(1, next); next.nested[0].x = 80; h.commit(1);
  assert.deepEqual(h.state, {nested: [{x: 1}]}); h.undo(); h.state.nested[0].x = 60; h.redo();
  assert.deepEqual(h.state, {nested: [{x: 1}]}); h.undo(); assert.deepEqual(h.state, {nested: [{x: 0}]});
});
test('arrays ordered and absent distinct from null', () => {
  const h = new H({a: [1, 2]}); move(h, {a: [2, 1]}); h.undo(); assert.deepEqual(h.state, {a: [1, 2]});
  move(h, {a: [1, 2], b: null}); h.undo(); assert.deepEqual(h.state, {a: [1, 2]});
});
test('idle operations are harmless and false', () => {
  const h = new H({x: 1}); for (const op of ['update', 'commit', 'cancel']) assert.equal(h[op](7, {x: 9}), false);
  assert.equal(h.undo(), false); assert.equal(h.redo(), false); assert.deepEqual(h.state, {x: 1});
});
