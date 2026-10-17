"""Small deterministic contracts shared by the authoritative simulators."""
import copy
import hashlib
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

VERSION = 'wall-ne/1'

def utc():
    return datetime.now(timezone.utc).isoformat()

def uid():
    return str(uuid.uuid4())

def canonical(value):
    # JSONB normalizes signed zero and integral numbers. Hash semantic numeric values.
    def normalize(item):
        if isinstance(item,float) and math.isfinite(item) and item.is_integer(): return int(item)
        if isinstance(item,dict): return {k:normalize(v) for k,v in item.items()}
        if isinstance(item,(list,tuple)): return [normalize(v) for v in item]
        return item
    return json.dumps(normalize(value), sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def implementation_hash():
    root=Path(__file__).resolve().parent.parent
    return digest({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('simulator','web') for p in sorted((root/folder).glob('*')) if p.suffix in ('.py','.js','.html','.css')})

def treatment_implementation_hash():
    # Pin the complete backend and the treatment sensor's local dependency graph.
    import re
    root=Path(__file__).resolve().parent.parent
    paths=set((root/'simulator').glob('*.py'))|{root/'package-lock.json',root/'web/treatment.html'}
    pending=[root/'web/treatment.js']
    while pending:
        path=pending.pop().resolve()
        if path in paths: continue
        paths.add(path)
        for relative in re.findall(r'''(?:from\s*|import\s*)['"](\./[^'"]+)['"]''',path.read_text()):
            dependency=(path.parent/relative).resolve()
            if root/'web' not in dependency.parents: raise ValueError('sensor dependency outside web root')
            pending.append(dependency)
    return digest({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)})

def finite(value, low=-math.inf, high=math.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('number outside permitted range')
    return float(value)

def load_env(path='.env'):
    if not Path(path).is_file():
        return
    for line in Path(path).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('\"\''))

def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

class RecordedWorld:
    def event(self, kind, robot=None, **payload):
        self.seq += 1
        self.events.append(dict(sequence=self.seq, revision=self.revision, sim_time=self.time,
                                wall_utc=utc(), type=kind, robot_id=robot, payload=payload))

    def checkpoint(self):
        return copy.deepcopy(self.__dict__)

    @classmethod
    def restore(cls, state):
        obj = cls.__new__(cls)
        obj.__dict__ = copy.deepcopy(state)
        return obj

    def snapshot(self):
        return self.checkpoint()
