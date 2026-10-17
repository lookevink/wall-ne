"""Stitch a recorded orchard timelapse reel into an MP4 with ffmpeg."""
import argparse
from simulator import timelapse


def main():
    p=argparse.ArgumentParser();p.add_argument('reel',nargs='?',help='reel id (default: latest)');p.add_argument('--fps',type=int,default=30,choices=(24,30,60));p.add_argument('--list',action='store_true')
    a=p.parse_args();reels=timelapse.reels()
    if a.list:
        for reel in reels:print(reel,sum(1 for _ in timelapse.folder(reel).glob('frame-*.jpg')),'frames')
        return
    if not reels and not a.reel:raise SystemExit('No timelapse reels recorded yet.')
    result=timelapse.render(a.reel or reels[0],a.fps)
    print(f"{result['output']} · {result['frames']} frames · {result['seconds']} s at {result['fps']} fps")


if __name__=='__main__':main()
