"""Run with python3 -m scripts.distill; all paid work requires --execute."""
import argparse
import json
from pathlib import Path
from simulator.common import load_env
from simulator.inference import Adapter
from simulator.persistence import Repository
from training.pipeline import Pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='.runtime/distillation/pipeline.sqlite3')
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export', help='Read committed Supabase policy inputs and linked children')
    export.add_argument('--session', action='append', required=True)
    export.add_argument('--include-telemetry', action='store_true', help='Download verified high-frequency movement chunks into the evidence archive')
    label = commands.add_parser('label', help='Queue teacher calls; defaults to a preview')
    label.add_argument('--teacher', required=True)
    label.add_argument('--modality', choices=('text', 'multimodal'), default='text')
    label.add_argument('--execute', action='store_true')
    label.add_argument('--max-calls', type=int, default=10)
    label.add_argument('--cost-cap', type=float, default=1.0)
    imported = commands.add_parser('import-labels', help='Import offline teacher results with input hashes')
    imported.add_argument('--file', type=Path, required=True)
    imported.add_argument('--teacher', required=True)
    build = commands.add_parser('build')
    build.add_argument('--teacher', required=True)
    build.add_argument('--output', required=True)
    build.add_argument('--validation-percent', type=int, default=20)
    commands.add_parser('status')
    args = parser.parse_args()
    pipeline = Pipeline(args.db)
    try:
        if args.command == 'export':
            load_env()
            result = pipeline.export_sessions(Repository(), args.session, args.include_telemetry)
        elif args.command == 'label':
            pipeline.enqueue(args.teacher, args.modality)
            if args.execute:
                load_env()
                adapter = Adapter('crusoe', 'reviewer')
                adapter.model = args.teacher  # Explicit model ID; never substitute silently.
                if not adapter.key:
                    raise ValueError('CRUSOE_API_KEY is required for teacher calls')
                result = pipeline.label(adapter, args.max_calls, args.cost_cap, args.modality)
            else:
                result = dict(execute=False, teacher=args.teacher, max_calls=args.max_calls,
                              cost_cap=args.cost_cap, note='Queue prepared. No inference called.')
        elif args.command == 'import-labels':
            count = 0
            for line in args.file.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    pipeline.complete(row['input_id'], args.teacher, row['result'])
                    count += 1
            result = dict(imported=count)
        elif args.command == 'build':
            result = pipeline.build(args.output, args.teacher, args.validation_percent)
        else:
            result = dict(inputs=pipeline.db.execute('SELECT count(*) FROM inputs').fetchone()[0],
                          labels=[dict(r) for r in pipeline.db.execute(
                              'SELECT teacher,status,count(*) AS count FROM labels GROUP BY teacher,status')])
        print(json.dumps(result, indent=2))
    finally:
        pipeline.close()


if __name__ == '__main__':
    main()
