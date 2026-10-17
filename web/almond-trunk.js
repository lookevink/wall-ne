import * as THREE from 'three';

export function almondTrunkGeometry() {
  const sides = 9, height = 1.83;
  // Shared rings keep the root flare attached as the trunk bends and tapers.
  // CylinderGeometry orders rings from the crown down to the ground.
  const rings = [
    {x:0,y:height,z:0,radius:.105},
    {x:.025,y:.55,z:-.02,radius:.145},
    {x:0,y:0,z:0,radius:.19},
  ];
  const geometry = new THREE.CylinderGeometry(1,1,1,sides,rings.length-1);
  const position = geometry.getAttribute('position'), uv = geometry.getAttribute('uv');
  const sideVertices = rings.length*(sides+1);
  for (let i=0;i<position.count;i++) {
    const ring = rings[Math.round((.5-position.getY(i))*(rings.length-1))];
    position.setXYZ(i,ring.x+position.getX(i)*ring.radius,ring.y,ring.z+position.getZ(i)*ring.radius);
    if (i<sideVertices) uv.setY(i,ring.y/height);
  }
  geometry.computeVertexNormals();
  const normals = geometry.getAttribute('normal');
  // The duplicated UV-wrap vertices must also share their shading normal.
  for (let ring=0;ring<rings.length;ring++) {
    const first = ring*(sides+1), last = first+sides;
    const normal = new THREE.Vector3().fromBufferAttribute(normals,first)
      .add(new THREE.Vector3().fromBufferAttribute(normals,last)).normalize();
    normals.setXYZ(first,normal.x,normal.y,normal.z);
    normals.setXYZ(last,normal.x,normal.y,normal.z);
  }
  return geometry;
}
