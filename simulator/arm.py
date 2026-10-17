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
