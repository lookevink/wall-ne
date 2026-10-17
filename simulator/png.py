"""Bounded RGB/RGBA PNG decoder and deliberately stylized pixel components."""
import base64
import struct
import zlib

MAX_BYTES=2*1024*1024

def decode_url(data):
    if not isinstance(data,str) or not data.startswith('data:image/png;base64,') or len(data)>MAX_BYTES*4//3+100: raise ValueError('bounded PNG data URL required')
    try: raw=base64.b64decode(data.split(',',1)[1],validate=True)
    except Exception: raise ValueError('invalid PNG encoding') from None
    width,height,pixels=decode(raw)
    return raw,pixels

def decode(raw):
    if len(raw)>MAX_BYTES or raw[:8]!=b'\x89PNG\r\n\x1a\n': raise ValueError('invalid PNG signature or size')
    pos=8; compressed=bytearray(); header=None; end=False; seen_data=False
    while pos+12<=len(raw):
        n=struct.unpack('>I',raw[pos:pos+4])[0]; kind=raw[pos+4:pos+8]; data=raw[pos+8:pos+8+n]
        if len(data)!=n or pos+12+n>len(raw): raise ValueError('truncated PNG')
        crc=struct.unpack('>I',raw[pos+8+n:pos+12+n])[0]
        if zlib.crc32(kind+data)&0xffffffff!=crc: raise ValueError('PNG CRC mismatch')
        if kind==b'IHDR':
            if header or pos!=8 or n!=13: raise ValueError('invalid PNG header')
            header=struct.unpack('>IIBBBBB',data)
        elif kind==b'IDAT': compressed.extend(data); seen_data=True
        elif kind==b'IEND':
            if n: raise ValueError('invalid PNG end')
            end=True; pos+=12; break
        elif kind[0]&32==0: raise ValueError('unsupported critical PNG chunk')
        pos+=12+n
    if not end or pos!=len(raw) or not header or not seen_data: raise ValueError('incomplete PNG')
    w,h,bits,color,compression,filter_method,interlace=header
    if (w,h)!=(640,360) or bits!=8 or color not in (2,6) or compression or filter_method or interlace: raise ValueError('PNG must be noninterlaced 640x360 RGB(A)8')
    channels=3 if color==2 else 4; stride=w*channels; limit=(stride+1)*h
    obj=zlib.decompressobj()
    try: decoded=obj.decompress(bytes(compressed),limit+1)
    except zlib.error: raise ValueError('invalid PNG compression') from None
    if len(decoded)!=limit or not obj.eof or obj.unconsumed_tail or obj.unused_data: raise ValueError('PNG decompression bounds')
    previous=bytearray(stride); pixels=bytearray(); at=0
    for _ in range(h):
        method=decoded[at]; at+=1
        if method>4: raise ValueError('invalid PNG filter')
        row=bytearray(decoded[at:at+stride]); at+=stride
        for i in range(stride):
            a=row[i-channels] if i>=channels else 0; b=previous[i]; c=previous[i-channels] if i>=channels else 0
            if method==1: predictor=a
            elif method==2: predictor=b
            elif method==3: predictor=(a+b)//2
            elif method==4:
                p=a+b-c; pa,pb,pc=abs(p-a),abs(p-b),abs(p-c); predictor=a if pa<=pb and pa<=pc else b if pb<=pc else c
            else: predictor=0
            row[i]=(row[i]+predictor)&255
        if channels==4: pixels.extend(row)
        else:
            for i in range(0,len(row),3): pixels.extend(row[i:i+3]+b'\xff')
        previous=row
    return w,h,pixels

def components(pixels,kind,include_bounds=False):
    # No target IDs, positions or render segmentation are available to this detector.
    def match(r,g,b):
        if kind=='basin': return b>90 and b>r*1.45 and b>g*1.15
        if kind=='yellow_green': return r>45 and g>r*1.2 and g>b*1.8 and r>b*1.5
        if kind=='vegetation': return g>45 and g>r*1.25 and g>b*1.2
        if kind=='weed': return g>35 and g>r*1.3 and g>b*1.25 and g<125
        if kind=='pest': return r>45 and b>45 and b>g*1.25 and r>g*1.25 and r<180
        return False
    mask=set()
    for y in range(0,360,2):
        for x in range(0,640,2):
            i=(y*640+x)*4
            if match(*pixels[i:i+3]): mask.add((x//2,y//2))
    groups=[]
    while mask:
        start=mask.pop(); stack=[start]; group=[start]
        while stack:
            x,y=stack.pop()
            for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if p in mask: mask.remove(p); stack.append(p); group.append(p)
        if len(group)<4: continue
        # Weed root is approximated at the bottom center of the visible component.
        low=max(y for x,y in group)
        points=[p for p in group if p[1]>=low-2] if kind in ('weed','vegetation','yellow_green') else group
        component=dict(u=sum(x*2+1 for x,y in points)/len(points)/640,v=sum(y*2+1 for x,y in points)/len(points)/360,area=len(group))
        if include_bounds:component['bounds']=[min(x for x,y in group)*2/640,min(y for x,y in group)*2/360,(max(x for x,y in group)*2+2)/640,(low*2+2)/360]
        groups.append(component)
    return sorted(groups,key=lambda g:-g['area'])


def crop_url(raw,bounds):
    """Nearest-neighbor magnification of the measured scan ROI; no invented pixels."""
    import math
    w,h,pixels=decode(raw)
    x0,y0=max(0,math.floor(bounds[0]*w)),max(0,math.floor(bounds[1]*h))
    x1,y1=min(w,math.ceil(bounds[2]*w)),min(h,math.ceil(bounds[3]*h))
    if x1<=x0 or y1<=y0:raise ValueError('empty RGB crop')
    rows=bytearray()
    for y in range(h):
        source_y=y0+min(y1-y0-1,y*(y1-y0)//h);rows.append(0)
        for x in range(w):
            source_x=x0+min(x1-x0-1,x*(x1-x0)//w);i=(source_y*w+source_x)*4
            rows.extend(pixels[i:i+4])
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    result=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
    return result,dict(source_pixel_bounds=[x0,y0,x1,y1],source_uv_bounds=[x0/w,y0/h,x1/w,y1/h],output_size=[w,h],mapping='crop u,v map linearly into source_uv_bounds; scan point u,v always refer to FULL source image',resampling='nearest-neighbor')
