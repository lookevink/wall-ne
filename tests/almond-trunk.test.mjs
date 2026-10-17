import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {almondTrunkGeometry} from '../web/almond-trunk.js';

test('root flare and upper trunk form one connected surface', () => {
  const geometry = almondTrunkGeometry();
  const position = geometry.getAttribute('position'), normal = geometry.getAttribute('normal'), neighbors = new Map();
  // Weld coincident positions so UV seams and cap normals do not split a surface.
  const keys = Array.from({length:position.count}, (_,i) =>
    [position.getX(i),position.getY(i),position.getZ(i)].map(v=>v.toFixed(5)).join(','));
  const indices = geometry.index?.array ?? keys.map((_,i)=>i);
  for (let i=0;i<indices.length;i+=3) {
    // Internal end caps can touch at their centers while leaving the bark split.
    if (Array.from(indices.slice(i,i+3)).every(index=>Math.abs(normal.getY(index))>.8)) continue;
    const triangle = Array.from(indices.slice(i,i+3), index=>keys[index]);
    for (const key of triangle) {
      if (!neighbors.has(key)) neighbors.set(key,new Set());
      for (const other of triangle) neighbors.get(key).add(other);
    }
  }
  const unseen = new Set(neighbors.keys());
  let components = 0;
  while (unseen.size) {
    components++;
    const pending = [unseen.values().next().value];
    while (pending.length) {
      const key = pending.pop();
      if (!unseen.delete(key)) continue;
      pending.push(...neighbors.get(key));
    }
  }
  assert.equal(components,1,'root flare and middle trunk must share their join');
  geometry.dispose();
});

test('trunk remains solid from the roots through the crown attachment', () => {
  const mesh = new THREE.Mesh(almondTrunkGeometry(),new THREE.MeshBasicMaterial());
  mesh.updateMatrixWorld(true);
  for (let y=.01;y<1.83;y+=.01) {
    const hits = new THREE.Raycaster(new THREE.Vector3(0,y,1),new THREE.Vector3(0,0,-1)).intersectObject(mesh);
    assert.ok(hits.length,`missing trunk at height ${y}`);
  }
  mesh.geometry.dispose();mesh.material.dispose();
});

test('bark texture has a continuous vertical scale across the root join', () => {
  const geometry = almondTrunkGeometry();
  const position = geometry.getAttribute('position'), normal = geometry.getAttribute('normal'), uv = geometry.getAttribute('uv');
  for (let i=0;i<position.count;i++) {
    if (Math.abs(normal.getY(i))>.8) continue;
    assert.ok(Math.abs(uv.getY(i)-position.getY(i)/1.83)<1e-6,'bark must not restart or change scale at the join');
  }
  geometry.dispose();
});
