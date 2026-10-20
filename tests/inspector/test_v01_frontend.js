'use strict';
// Selected-scene authority and Native numeric edits; no wording assertions.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const HELPER = process.env.FIGPACT_INSPECTOR_JS || path.join(__dirname, '..', '..', 'figpact', '_inspector', 'inspector.js');
const m = require(HELPER);
test('scene mapping preserves ambiguity and rejects unknown or near-match IDs', () => {
  const targets = [{target_id:'a',scene_ids:['n1']},{target_id:'b',scene_ids:['n1','n2']}];
  assert.deepEqual(m.styleExactTargetsForScene(targets,'n1').map(t=>t.target_id),['a','b']);
  assert.deepEqual(m.styleExactTargetsForScene(targets,'n2').map(t=>t.target_id),['b']);
  assert.deepEqual(m.styleExactTargetsForScene(targets,'n'),[]);
  assert.deepEqual(m.styleExactTargetsForScene(targets,'n9'),[]);
});
test('Native edits include only changed authorized finite values within bounds', () => {
  const controls = [{control_id:'width',current:1.5,min:.05,max:20},{control_id:'font',current:8,min:.5,max:100}];
  assert.deepEqual(m.nativeEditsFromInputs(controls,{width:'.8',font:'8',invented:'99'}).edits,[{control_id:'width',value:.8}]);
  assert.deepEqual(m.nativeEditsFromInputs(controls,{width:'.05'}).edits,[{control_id:'width',value:.05}]);
  for (const width of ['NaN','Infinity','.049','20.01']) {
    assert.equal(m.nativeEditsFromInputs(controls,{width}).edits,null);
  }
  assert.equal(m.nativeEditsFromInputs(controls,{width:'1.5',font:'8'}).edits,null);
});
