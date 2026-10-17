import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {ORCHARD,TREE_COUNT,AISLE_COUNT,planting,rowX,aisleX} from '../web/orchard-layout.js';
import {skeleton} from '../web/almond-geometry.js';

test('13 by 13 planting is reproducible and has individual variation',()=>{
  const trees=planting();
  assert.equal(TREE_COUNT,169);assert.equal(trees.length,TREE_COUNT);
  assert.equal(new Set(trees.map(t=>`${t.row}:${t.column}`)).size,169);
  for(let row=0;row<13;row++)assert.equal(trees.filter(t=>t.row===row).length,13);
  assert.deepEqual(trees,planting());assert.notDeepEqual(trees,planting(983));
  assert.equal(new Set(trees.map(t=>t.variant)).size,24);
  assert.ok(new Set(trees.map(t=>t.hue)).size>150);
  for(const t of trees){assert.ok(Math.abs(t.position[0]-rowX(t.row))<=.06);assert.ok(t.scale[1]>=1);}
});

test('planting surrounds the authoritative mission aisles without moving its zones',()=>{
  const zones=JSON.parse(execFileSync('python3',['-c',
    'import json\nfrom simulator.engine import Mission\nprint(json.dumps(list(Mission().zones.values())))'],{encoding:'utf8'}));
  assert.equal(AISLE_COUNT,12);assert.equal(zones.length,36);
  for(const z of zones){
    assert.equal(z.position[0],aisleX(z.row));
    for(const t of planting())assert.ok(Math.abs(z.position[0]-t.position[0])>=1.69);
  }
});

test('all crown variants keep attached hulls and low rover clearance',()=>{
  const forms=Array.from({length:ORCHARD.variants},(_,i)=>skeleton(71+i*17));
  assert.equal(new Set(forms.map(f=>f.habit)).size,3);
  const heights=forms.map(f=>Math.max(...f.leaves.map(l=>l.position[1])));
  assert.ok(Math.max(...heights)-Math.min(...heights)>1);
  for(const f of forms){
    for(const [a,b] of f.branches)assert.ok(Math.min(a[1],b[1])>=1.75);
    for(const h of f.hulls)assert.deepEqual(h.position,f.spurs[h.spur]);
  }
});
