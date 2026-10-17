// Pure, seeded geometry: the same botanical skeleton drives every view.
export function random(seed) {
  let state = seed >>> 0;
  return () => { state = (Math.imul(1664525, state) + 1013904223) >>> 0; return state / 4294967296; };
}
const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);

export function skeleton(seed) {
  const rng = random(seed), branches = [], spurs = [], leaves = [];
  const limbs = 3 + Math.floor(rng() * 2), phase = rng() * Math.PI * 2;
  for (let i = 0; i < limbs; i++) {
    const angle = phase + i / limbs * Math.PI * 2 + (rng() - .5) * .35;
    const reach = 1.05 + rng() * .38;
    const base = [0, 1.82, 0];
    const elbow = [Math.cos(angle) * reach * .6, 2.55 + rng() * .28, Math.sin(angle) * reach * .6];
    const tip = [Math.cos(angle) * reach, 3.55 + rng() * .55, Math.sin(angle) * reach];
    branches.push([base, elbow, .115, .075], [elbow, tip, .075, .018]);
    for (let j = 0; j < 7; j++) {
      const t = .12 + j * .125, start = mix(elbow, tip, t);
      const side = angle + (j % 2 ? 1 : -1) * (.55 + rng() * .8);
      const length = .48 + rng() * .45;
      const end = [start[0] + Math.cos(side) * length, start[1] + .18 + rng() * .4, start[2] + Math.sin(side) * length];
      branches.push([start, end, .027 * (1 - t * .6), .006]);
      for (let k = 0; k < 3; k++) {
        const node = mix(start, end, .3 + k * .3), a = side + (k % 2 ? -1 : 1) * .9;
        const twig = [node[0] + Math.cos(a) * .28, node[1] + .18 + rng() * .24, node[2] + Math.sin(a) * .28];
        branches.push([node, twig, .007, .002]);
        spurs.push(mix(node, twig, .8));
        for (let n = 0; n < 10; n++) {
          const u = (n + .5) / 10, p = mix(node, twig, u), turn = a + n * 2.39996;
          // Leaves emerge along a shoot; their bases stay near the wood.
          p[0] += Math.cos(turn) * .11; p[2] += Math.sin(turn) * .11;
          leaves.push({position:p, rotation:[.45 + rng() * 1.8, turn, (rng() - .5) * 1.2], scale:.85 + rng() * .65, tint:rng()});
        }
      }
    }
  }
  const count = 45 + Math.floor(rng() * 16);
  const hulls = Array.from({length:count}, (_, i) => {
    const spur = Math.floor(i * spurs.length / count);
    return {position:spurs[spur].slice(), spur, rotation:rng() * Math.PI};
  });
  return {branches, spurs, leaves, hulls, lowClearance:{height:1.75, radius:.35}};
}
