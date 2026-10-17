import {random} from './almond-geometry.js';

// Thirteen planted rows enclose the twelve existing rover aisles.
// Keep planting coordinates separate from the authoritative mission's zones.
export const ORCHARD = Object.freeze({
  rows:13, treesPerRow:13, rowSpacing:3.5, treeSpacing:2.3, back:-15,
  variants:24, seed:982,
});
export const TREE_COUNT = ORCHARD.rows * ORCHARD.treesPerRow;
export const AISLE_COUNT = ORCHARD.rows - 1;
export const rowX = row => (row - (ORCHARD.rows - 1) / 2) * ORCHARD.rowSpacing;
export const aisleX = aisle => rowX(aisle) + ORCHARD.rowSpacing / 2;
export const treeZ = index => ORCHARD.back + index * ORCHARD.treeSpacing;

export function planting(seed=ORCHARD.seed) {
  const rng=random(seed),trees=[];
  for(let row=0;row<ORCHARD.rows;row++)for(let column=0;column<ORCHARD.treesPerRow;column++) {
    // Row structure stays legible; subtle planting drift avoids ruler-straight trunks.
    const vigor=rng(),variant=Math.floor(rng()*ORCHARD.variants);
    trees.push({
      row,column,variant,position:[rowX(row)+(rng()-.5)*.12,0,treeZ(column)+(rng()-.5)*.22],
      rotation:rng()*Math.PI*2,scale:[.82+vigor*.24,1+rng()*.1,.83+rng()*.25],
      hue:.195+rng()*.052,saturation:.27+rng()*.15,lightness:.49+rng()*.12,
      leafScale:.86+rng()*.22,barkTone:.78+rng()*.2,
    });
  }
  return trees;
}
