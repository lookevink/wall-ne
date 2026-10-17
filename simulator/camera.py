"""Calibrated pinhole rays, using full camera up including wrist roll."""
import math
from .common import finite

def add(a,b): return [x+y for x,y in zip(a,b)]
def sub(a,b): return [x-y for x,y in zip(a,b)]
def scale(a,s): return [x*s for x in a]
def dot(a,b): return sum(x*y for x,y in zip(a,b))
def cross(a,b): return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def norm(a): return math.sqrt(dot(a,a))
def unit(a): return scale(a,1/norm(a))
def matvec(m,v): return [dot(r,v) for r in m]
def transpose(m): return list(map(list,zip(*m)))
def multiply(a,b): return [[dot(r,c) for c in zip(*b)] for r in a]
def rotation(euler):
    x,y,z=map(math.radians,euler); cx,sx,cy,sy,cz,sz=math.cos(x),math.sin(x),math.cos(y),math.sin(y),math.cos(z),math.sin(z)
    return [[cy*cz,-cy*sz,sy],[cx*sz+sx*sy*cz,cx*cz-sx*sy*sz,-sx*cy],[sx*sz-cx*sy*cz,sx*cz+cx*sy*sz,cx*cy]]
def euler(m):
    y=math.asin(max(-1,min(1,m[0][2])))
    if abs(math.cos(y))>1e-7: x,z=math.atan2(-m[1][2],m[2][2]),math.atan2(-m[0][1],m[0][0])
    else: x,z=math.atan2(m[2][1],m[1][1]),0
    return list(map(math.degrees,(x,y,z)))
def ray(camera,u,v):
    finite(u,0,1); finite(v,0,1)
    f=unit(camera['direction']); r=unit(cross(f,camera['up'])); up=cross(r,f)
    t=math.tan(math.radians(camera['fov'])/2)
    return unit(add(f,add(scale(r,(u*2-1)*t*640/360),scale(up,(1-v*2)*t))))
def project_ground(camera,u,v,y=.08):
    d=ray(camera,u,v); p=camera['position']
    if abs(d[1])<1e-9 or (y-p[1])/d[1]<=0: raise ValueError('ray misses ground')
    return add(p,scale(d,(y-p[1])/d[1]))
def project_pixel(camera,point):
    f=unit(camera['direction']); r=unit(cross(f,camera['up'])); up=cross(r,f); delta=sub(point,camera['position']); depth=dot(delta,f)
    if depth<=0: raise ValueError('point behind camera')
    t=math.tan(math.radians(camera['fov'])/2)
    return [.5+dot(delta,r)/(2*depth*t*640/360),.5-dot(delta,up)/(2*depth*t)]
