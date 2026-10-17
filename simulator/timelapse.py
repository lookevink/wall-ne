"""Operator timelapse reels: browser-rendered overview frames kept locally and stitched with ffmpeg."""
import base64
import json
import pathlib
import re
import shutil
import subprocess
from .common import utc

ROOT=pathlib.Path(__file__).resolve().parent.parent/'.runtime'/'timelapse'
REEL=re.compile(r'^\d{8}-\d{6}$')


def folder(reel):
    if not isinstance(reel,str) or not REEL.match(reel):raise ValueError('invalid timelapse reel')
    return ROOT/reel


def save_frame(reel,index,data_url,meta=None):
    if type(index)!=int or not 0<=index<1_000_000:raise ValueError('invalid frame index')
    prefix='data:image/jpeg;base64,'
    if not isinstance(data_url,str) or not data_url.startswith(prefix):raise ValueError('JPEG frame required')
    raw=base64.b64decode(data_url[len(prefix):],validate=True)
    if raw[:3]!=b'\xff\xd8\xff':raise ValueError('JPEG frame required')
    path=folder(reel);path.mkdir(parents=True,exist_ok=True)
    (path/f'frame-{index:06d}.jpg').write_bytes(raw)
    meta=meta if isinstance(meta,dict) else {}
    with (path/'frames.jsonl').open('a') as log:
        log.write(json.dumps(dict(index=index,wall_utc=utc(),**{k:meta.get(k) for k in ('day','clock','session_id')}))+'\n')
    return dict(reel=reel,frames=sum(1 for _ in path.glob('frame-*.jpg')))


def write_manifest(reel,manifest):
    path=folder(reel);path.mkdir(parents=True,exist_ok=True)
    (path/'manifest.json').write_text(json.dumps(dict(manifest,created_utc=utc()),indent=2))


def reels():
    return sorted((p.name for p in ROOT.glob('*') if p.is_dir() and REEL.match(p.name)),reverse=True) if ROOT.is_dir() else []


def render(reel,fps=30):
    """Encode every saved frame in index order; a dropped upload simply shortens the reel."""
    if fps not in (24,30,60):raise ValueError('fps must be 24/30/60')
    path=folder(reel);frames=sorted(path.glob('frame-*.jpg'))
    if len(frames)<2:raise ValueError('record at least two frames first')
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise ValueError('ffmpeg is not installed; frames remain in '+str(path))
    listing=path/'frames.txt';listing.write_text(''.join(f"file '{f.name}'\nduration {1/fps:.6f}\n" for f in frames))
    output=path.with_suffix('.mp4')
    try:
        subprocess.run([ffmpeg,'-y','-loglevel','error','-f','concat','-i',str(listing),'-vf','scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p',
                        '-c:v','libx264','-crf','21','-preset','medium','-movflags','+faststart','-r',str(fps),str(output)],check=True,timeout=900,capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise ValueError('ffmpeg failed: '+exc.stderr.decode(errors='replace')[-300:]) from None
    return dict(reel=reel,frames=len(frames),fps=fps,seconds=round(len(frames)/fps,1),output=str(output))
