"""Six-joint kinematics; explicit geometric checks, not rigid body dynamics."""
import math
from .camera import add,sub,scale,norm,rotation,multiply,matvec,transpose,euler
from .common import finite
LIMITS=[[-180,180],[-175,100],[-165,0],[-180,180],[-90,90],[-180,180]]

def validate(joints):
    if not isinstance(joints,list) or len(joints)!=6: raise ValueError('six joint angles required')
    return [finite(q,*limit) for q,limit in zip(joints,LIMITS)]

def fk(joints,base=(0,.8,3.3)):
    q=validate(joints); yaw,s,e=map(math.radians,q[:3])
    def vector(length,angle): return [math.sin(yaw)*length*math.sin(angle),length*math.cos(angle),math.cos(yaw)*length*math.sin(angle)]
    elbow=add(base,vector(1.45,s)); wrist=add(elbow,vector(1.25,s+e))
    link_rotation=multiply(rotation([0,q[0],0]),rotation([-q[1]-q[2],0,0]))
    rot=multiply(link_rotation,rotation(q[3:]))
    tool=add(wrist,matvec(rot,[0,-.16,0]))
    return dict(points=[list(base),elbow,wrist,tool],position=tool,rotation=rot,euler=euler(rot))

def ik(pose,base=(0,.8,3.3),near=None):
    if len(pose)!=6: raise ValueError('Cartesian pose requires x,y,z,rx,ry,rz')
    pose=[finite(v) for v in pose]; desired=rotation(pose[3:]); wrist=sub(pose[:3],matvec(desired,[0,-.16,0])); x,y,z=sub(wrist,base)
    radius=math.hypot(x,z); cosine=(radius*radius+y*y-1.45**2-1.25**2)/(2*1.45*1.25)
    if abs(cosine)>1+1e-9: raise ValueError('unreachable pose')
    elbow=-math.acos(max(-1,min(1,cosine))); solutions=[]
    for sign in (1,-1):
        yaw=math.atan2(x*sign,z*sign); shoulder=math.atan2(radius*sign,y)-math.atan2(1.25*math.sin(elbow),1.45+1.25*math.cos(elbow))
        first=list(map(math.degrees,(yaw,shoulder,elbow)))
        link=multiply(rotation([0,first[0],0]),rotation([-first[1]-first[2],0,0]))
        angles=first+euler(multiply(transpose(link),desired))
        try: solutions.append(validate(angles))
        except ValueError: pass
    if not solutions: raise ValueError('joint limits exclude pose')
    return min(solutions,key=lambda q:sum((a-b)**2 for a,b in zip(q,near or [0]*6)))

def trajectory(start,end,base=(0,.8,3.3),trunks=((0,0),)):
    start,end=validate(start),validate(end)
    count=max(1,math.ceil(max(abs(a-b) for a,b in zip(start,end))/2))
    samples=[]
    for i in range(count+1):
        q=[a+(b-a)*i/count for a,b in zip(start,end)]; points=fk(q,base)['points']
        for a,b in zip(points,points[1:]):
            for t in range(21):
                p=add(a,scale(sub(b,a),t/20))
                if p[1]<.025: raise ValueError('trajectory intersects ground')
                if p[1]<2.8 and any(math.hypot(p[0]-x,p[2]-z)<.21 for x,z in trunks): raise ValueError('trajectory intersects trunk')
        samples.append(q)
    return samples,max(.4,max(abs(a-b) for a,b in zip(start,end))/45)


def clearances(joints,base,trunks):
    """Ground and per-trunk margins using the trajectory checker geometry."""
    points=fk(joints,base)['points'];samples=[]
    for a,b in zip(points,points[1:]):
        samples.extend(add(a,scale(sub(b,a),t/20)) for t in range(21))
    low=[p for p in samples if p[1]<2.8]
    margins=[min(p[1] for p in samples)-.025]
    bounds=(min(p[0] for p in low),max(p[0] for p in low),min(p[2] for p in low),max(p[2] for p in low)) if low else None
    for x,z in trunks:
        if bounds is None:margins.append(math.inf);continue
        left,right,back,front=bounds
        outside=math.hypot(max(left-x,0,x-right),max(back-z,0,z-front))-.21
        # A conservative positive bound avoids testing distant orchard rows.
        margins.append(outside if outside>=0 else min(math.hypot(p[0]-x,p[2]-z)-.21 for p in low))
    return margins


def base_retreat(joints,base,trunks,delta):
    """Escape a legacy overlap without deepening it or entering another trunk.

    Joints stay fixed. Check the complete chassis translation at 2 cm intervals;
    each initially colliding trunk's penetration must decrease monotonically.
    Once clear, contact with that trunk is forbidden again.
    """
    length=math.hypot(*delta)
    if not .05<=length<=1.3:raise ValueError('recovery translation must be bounded')
    previous=clearances(joints,base,trunks)
    if previous[0]<0:raise ValueError('cannot drive an arm intersecting ground')
    count=math.ceil(length/.02)
    for i in range(1,count+1):
        moved=[base[0]+delta[0]*i/count,base[1],base[2]+delta[1]*i/count]
        if any(math.hypot(moved[0]-x,moved[2]+.5-z)<.85 for x,z in trunks):
            raise ValueError('recovery chassis intersects trunk')
        current=clearances(joints,moved,trunks)
        if any(now<min(0,before)-1e-9 for now,before in zip(current,previous)):
            raise ValueError('recovery deepens contact or creates a new collision')
        previous=current
    if min(previous)<.02:raise ValueError('recovery must finish clear of obstacles')
    return max(.4,length/.4)
