"""Isolated browser/pixel regression fixture. No persistence, inference, or live sessions.
Run python3 scripts/specimen_check.py, then open http://127.0.0.1:8793.
"""
import json
import mimetypes
import pathlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simulator.care import PlantCare
from simulator.png import decode_url, components

OUT = ROOT / '.runtime' / 'specimen-check'
OUT.mkdir(parents=True, exist_ok=True)
worlds = {}
results = {}
def reset_worlds():
    worlds.clear()
    results.clear()
    for seed in [0, 7, 8, 11, 21]:
        for phase in ['weeds', 'pests']:
            w = PlantCare(seed)
            w.robot['position'] = [0, 3.8]
            w.phase = phase
            w.status = 'running'
            w.tool = 'gripper' if phase == 'weeds' else 'vacuum'
            if phase == 'pests':
                for weed in w.weeds:
                    weed['removed'] = True
            worlds[f'{seed}-{phase}'] = w

reset_worlds()

HTML = '''<!doctype html><meta charset="utf-8"><title>Isolated specimen regression</title>
<style>body{background:#eee;font:14px monospace}#scene{width:640px;height:360px}img{width:320px}pre{white-space:pre-wrap}</style>
<script type="importmap">{"imports":{"three":"/vendor/three.module.js"}}</script>
<h1>Isolated specimen regression</h1><p>No live session, persistence or inference calls.</p>
<div id="scene"></div><canvas id="capture" width="640" height="360" hidden></canvas><pre id="results">Rendering…</pre>
<script type="module">
import {TreatmentScene} from '/treatment-scene.js';
const scene=new TreatmentScene(document.querySelector('#scene')),canvas=document.querySelector('#capture'),report=[];
for(const id of await (await fetch('/cases')).json()) {
  let done=false;
  for(let round=0;round<9&&!done;round++) {
    const state=await (await fetch('/case?id='+id)).json();scene.update(state);
    const png=scene.capture(state.camera,canvas);
    const result=await (await fetch('/evaluate?id='+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({png,round})})).json();
    if(round===0){const img=document.createElement('img');img.src=png;img.alt=id;document.body.append(img);}
    done=result.done;if(done){report.push({id,...result});document.querySelector('#results').textContent=JSON.stringify(report,null,2);}
  }
}
document.title='COMPLETE — isolated specimen regression';
</script>'''

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, content_type='application/json'):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        from urllib.parse import urlsplit, parse_qs
        parsed = urlsplit(self.path)
        if parsed.path == '/':
            return self.send(HTML.encode(), 'text/html')
        if parsed.path == '/cases':
            reset_worlds()
            return self.send(list(worlds))
        if parsed.path == '/case':
            return self.send(worlds[parse_qs(parsed.query)['id'][0]].snapshot())
        if parsed.path.startswith('/vendor/'):
            allowed_root = ROOT / 'node_modules/three/build'
            file = allowed_root / parsed.path.rsplit('/', 1)[-1]
        else:
            allowed_root = ROOT / 'web'
            file = allowed_root / parsed.path.lstrip('/')
        if not file.is_file() or not file.resolve().is_relative_to(allowed_root):
            self.send_error(404)
            return
        return self.send(file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'text/plain')

    def do_POST(self):
        from urllib.parse import urlsplit, parse_qs
        key = parse_qs(urlsplit(self.path).query)['id'][0]
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        w = worlds[key]
        raw, pixels = decode_url(data['png'])
        (OUT / f'{key}-{data["round"]}.png').write_bytes(raw)
        phase = w.phase
        found = components(pixels, 'weed' if phase == 'weeds' else 'pest')
        targets = w.weeds if phase == 'weeds' else w.pests
        before = sum(not t['removed'] for t in targets)
        if not found:
            result = dict(done=True, passed=before == 0, remaining=before, components=0, rounds=data['round']+1)
        else:
            req = w.request_frame()
            w.accept_frame(req['id'], dict(id='isolated-fixture', ready=True, sha256='fixture'))
            point = found[0]
            receipt = w.command(f'fixture-{data["round"]}', 'T1', 'remove_weed' if phase == 'weeds' else 'remove_pest', u=point['u'], v=point['v'], frame_id=w.frame['id'])
            after = sum(not t['removed'] for t in targets)
            success = receipt['accepted'] and after < before and not w.damage
            result = dict(done=not success, passed=False, remaining=after, components=len(found), feedback=w.feedback, damage=w.damage, rounds=data['round']+1)
        results[key] = result
        (OUT / 'results.json').write_text(json.dumps(results, indent=2))
        self.send(result)

if __name__ == '__main__':
    print('Isolated specimen check: http://127.0.0.1:8793', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8793), Handler).serve_forever()
