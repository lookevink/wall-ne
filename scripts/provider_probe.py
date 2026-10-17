"""One small real image/tool request per selected provider, with sanitized evidence."""
import argparse
import base64
import json
import pathlib
import urllib.request
from simulator.common import load_env,uid
from simulator.inference import Adapter,InferenceError

def main():
    p=argparse.ArgumentParser();p.add_argument('engine',choices=['crusoe','gemini','nemotron','gemma']);args=p.parse_args();load_env()
    with urllib.request.urlopen('http://127.0.0.1:8765/api/treatment/state') as r:state=json.load(r)
    frame=state['frames'][0]
    with urllib.request.urlopen(f'http://127.0.0.1:8765/api/sessions/{state["id"]}/artifacts/{frame["artifact_id"]}') as r:image='data:image/png;base64,'+base64.b64encode(r.read()).decode()
    try:
        result=Adapter(args.engine).call({'mission':'Compatibility probe only; inspect this simulated orchard image, then call choose_action with action capture_image, arguments {}, and one-sentence rationale. No robot actions will be executed.'},image)
        result['status']='compatible'
    except InferenceError as e: result=dict(status='unavailable',engine=args.engine,error=str(e))
    path=pathlib.Path('docs/evaluations')/f'provider-{args.engine}-{uid()}.json';path.write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
