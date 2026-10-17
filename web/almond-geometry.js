// Pure, seeded geometry: the same botanical skeleton drives every view.
export function random(seed) {
  let state = seed >>> 0;
  return () => { state = (Math.imul(1664525, state) + 1013904223) >>> 0; return state / 4294967296; };
}
const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);

export function skeleton(seed) {
  const rng=random(seed),branches=[],spurs=[],leaves=[];
  // Distinct growth habits change the architecture, not just the finished scale.
  const habit=['upright','spreading','asymmetric'][seed%3];
  const vigor=.8+rng()*.35,phase=rng()*Math.PI*2,limbs=3+Math.floor(rng()*2);
  const reach=(habit==='spreading'?1.35:habit==='upright'?.95:1.16)*vigor;
  const height=(habit==='upright'?2.45:habit==='spreading'?1.55:1.95)*(.83+rng()*.35);
  const lean=[Math.cos(phase)*.22*rng(),0,Math.sin(phase)*.22*rng()];
  for(let i=0;i<limbs;i++) {
    const angle=phase+i/limbs*Math.PI*2+(rng()-.5)*.5;
    const length=reach*(.75+rng()*.45)*(habit==='asymmetric'&&i===0?1.3:1);
    const rise=height*(.8+rng()*.35);
    const base=[0,1.82,0];
    const elbow=[Math.cos(angle)*length*.48,2.35+rng()*.28,Math.sin(angle)*length*.48];
    const shoulder=[Math.cos(angle+.13)*length*.85+lean[0],1.82+rise*.78,Math.sin(angle+.13)*length*.85+lean[2]];
    const tip=[Math.cos(angle-.12)*length+lean[0],1.82+rise,Math.sin(angle-.12)*length+lean[2]];
    branches.push([base,elbow,.11*vigor,.072*vigor],[elbow,shoulder,.072*vigor,.038],[shoulder,tip,.038,.012]);
    const laterals=6+Math.floor(rng()*3);
    for(let j=0;j<laterals;j++) {
      const t=.10+j/(laterals-1)*.85;
      const start=t<.65?mix(elbow,shoulder,t/.65):mix(shoulder,tip,(t-.65)/.35);
      const side=angle+(j%2?1:-1)*(.6+rng()*1.1);
      const extension=(.4+rng()*.48)*(1-t*.2);
      const end=[start[0]+Math.cos(side)*extension,start[1]+.15+rng()*.5,start[2]+Math.sin(side)*extension];
      branches.push([start,end,.025*(1-t*.6),.005]);
      for(let k=0;k<3;k++) {
        const node=mix(start,end,.24+k*.32),a=side+(k%2?-1:1)*(.6+rng()*.6);
        const twig=[node[0]+Math.cos(a)*(.22+rng()*.16),node[1]+.12+rng()*.28,node[2]+Math.sin(a)*(.22+rng()*.16)];
        branches.push([node,twig,.006,.0015]);spurs.push(mix(node,twig,.8));
        const count=7+Math.floor(rng()*6);
        for(let n=0;n<count;n++) {
          const u=(n+.5)/count,p=mix(node,twig,u),turn=a+n*2.39996;
          p[0]+=Math.cos(turn)*.11;p[2]+=Math.sin(turn)*.11;
          leaves.push({position:p,rotation:[.4+rng()*1.8,turn,(rng()-.5)*1.4],scale:.78+rng()*.65,tint:rng()});
        }
      }
    }
  }
  const count=45+Math.floor(rng()*16);
  const hulls=Array.from({length:count},(_,i)=>{
    const spur=Math.floor(i*spurs.length/count);
    return {position:spurs[spur].slice(),spur,rotation:rng()*Math.PI};
  });
  return {branches,spurs,leaves,hulls,habit,lowClearance:{height:1.75,radius:.35}};
}
