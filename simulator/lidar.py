"""Camera-aligned 13x13 scans, validated atomically before they enter observations."""
from .common import finite,uid
from .camera import ray,sub,dot,norm,scale

def request(frame,u,v,span=.24):
    u,v,span=finite(u,0,1),finite(v,0,1),finite(span,.04,.5)
    bounds=[max(0,u-span/2),max(0,v-span/2),min(1,u+span/2),min(1,v+span/2)]
    x0,y0,x1,y1=bounds
    rays=[[x0+(x1-x0)*x/12,y0+(y1-y0)*y/12] for y in range(13) for x in range(13)]
    return dict(id=uid(),frame_id=frame['id'],revision=frame['revision'],camera=frame['camera'],bounds=bounds,rays=rays)

def validate(req,request_id,frame_id,revision,points):
    if request_id!=req['id'] or frame_id!=req['frame_id'] or revision!=req['revision']: raise ValueError('stale scan identity')
    if not isinstance(points,list) or len(points)!=len(req['rays']): raise ValueError('scan count mismatch')
    accepted=[]
    for uv,point in zip(req['rays'],points):
        if point is None: accepted.append(None); continue
        if not isinstance(point,list) or len(point)!=5: raise ValueError('scan row must be u,v,x,y,z')
        point=[finite(x) for x in point]
        if any(abs(a-b)>1e-7 for a,b in zip(uv,point[:2])): raise ValueError('scan ray order mismatch')
        delta=sub(point[2:],req['camera']['position']); direction=ray(req['camera'],*uv); depth=dot(delta,direction)
        if not .05<=norm(delta)<=6 or depth<=0 or norm(sub(delta,scale(direction,depth)))>.005: raise ValueError('scan geometry mismatch')
        accepted.append(point)
    return accepted
