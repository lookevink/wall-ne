import * as THREE from 'three';
import {random} from './almond-geometry.js';
function texture(canvas) {
  const t = new THREE.CanvasTexture(canvas);
  t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  return t;
}
export function barkTexture(seed = 12) {
  const c = document.createElement('canvas'); c.width = c.height = 256;
  const ctx = c.getContext('2d'), rng = random(seed);
  ctx.fillStyle = '#8b8171'; ctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 650; i++) {
    ctx.strokeStyle = i % 3 ? '#625b50' : '#b5aa91'; ctx.globalAlpha = .25 + rng() * .45;
    ctx.lineWidth = .5 + rng() * 2.5; ctx.beginPath();
    const x = rng() * 256, y = rng() * 256;
    ctx.moveTo(x, y); ctx.lineTo(x + rng() * 6 - 3, y + 6 + rng() * 48); ctx.stroke();
  }
  const t = texture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(2, 2); return t;
}
export function leafTexture() {
  const c = document.createElement('canvas'); c.width = 64; c.height = 128;
  const ctx = c.getContext('2d'), g = ctx.createLinearGradient(0, 0, 64, 0);
  g.addColorStop(0, '#6b833c'); g.addColorStop(.48, '#b8c57a'); g.addColorStop(.52, '#80954d'); g.addColorStop(1, '#536d32');
  ctx.fillStyle = g; ctx.fillRect(0, 0, 64, 128); ctx.strokeStyle = '#dae1a4'; ctx.globalAlpha = .4;
  ctx.beginPath(); ctx.moveTo(32, 0); ctx.lineTo(32, 128); ctx.stroke();
  for (let y = 14; y < 125; y += 14) { ctx.beginPath(); ctx.moveTo(4, y - 14); ctx.lineTo(32, y); ctx.lineTo(60, y - 14); ctx.stroke(); }
  return texture(c);
}
export function leafGeometry() {
  // Folded lanceolate leaf, with a raised midrib and curved tip.
  const g = new THREE.BufferGeometry(), vertices = [], uvs = [], indices = [];
  for (let i = 0; i < 5; i++) {
    const t = i / 4, width = Math.sin(t * Math.PI) * .062;
    for (const side of [-1, 0, 1]) { vertices.push(side * width, t * .38 - .19, Math.sin(t * Math.PI) * (side === 0 ? .024 : 0) + t * t * .035); uvs.push((side + 1) / 2, t); }
  }
  for (let i = 0; i < 4; i++) for (let s = 0; s < 2; s++) { const a = i * 3 + s; indices.push(a, a + 3, a + 1, a + 1, a + 3, a + 4); }
  g.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2)); g.setIndex(indices); g.computeVertexNormals(); return g;
}
export function hullTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const ctx = c.getContext('2d'), rng = random(149);
  ctx.fillStyle = '#bdc18b'; ctx.fillRect(0, 0, 64, 64);
  for (let i = 0; i < 900; i++) { ctx.fillStyle = i % 2 ? '#d8d5a4' : '#8d9b64'; ctx.globalAlpha = .4; ctx.fillRect(rng() * 64, rng() * 64, 1, 1); }
  ctx.strokeStyle = '#788952'; ctx.beginPath(); ctx.moveTo(32, 0); ctx.bezierCurveTo(36, 20, 28, 44, 32, 64); ctx.stroke(); return texture(c);
}
