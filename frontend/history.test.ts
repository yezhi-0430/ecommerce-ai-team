import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { chooseInitialRun } from './src/history.ts';

test('prefers a complete discussion over a newer visual-only sample', () => {
  assert.equal(chooseInitialRun([{id:'sample', status:'visual_test', visual_test:true}, {id:'complete', status:'review'}]), 'complete');
});
test('prioritizes an active workflow and falls back to the available sample', () => {
  assert.equal(chooseInitialRun([{id:'complete', status:'review'}, {id:'active', status:'running'}]), 'active');
  assert.equal(chooseInitialRun([{id:'sample', status:'visual_test', visual_test:true}]), 'sample');
  assert.equal(chooseInitialRun([]), undefined);
});
