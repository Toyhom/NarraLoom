"""Run an authored long-game trajectory or the bundled dialogue-memory example."""

import argparse
import asyncio
import json
from pathlib import Path

from roleplay_world.playtesting import load_plan, load_source, playtest

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--turns', type=int, default=100)
    parser.add_argument('--source', type=Path, required=True, help='Native world/story JSON export')
    parser.add_argument('--plan', type=Path, help='Authored trajectory; takes precedence over --turns')
    parser.add_argument('--models-config', type=Path, default=ROOT / 'configs/models.local.json')
    parser.add_argument('--secrets-root', type=Path, default=ROOT / 'secrets')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/validation/longrun-live')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--max-steps', type=int)
    args = parser.parse_args()
    if args.plan:
        plan = load_plan(args.plan)
    else:
        import sys
        sys.path.insert(0, str(ROOT / 'examples'))
        from make_playtest_plan import memory_plan
        plan = memory_plan(load_source(args.source), args.turns)
    result = asyncio.run(playtest(load_source(args.source), plan, config=json.loads(args.models_config.read_text()),
                                  output=args.output, secrets_root=args.secrets_root, resume=args.resume,
                                  retry_failed=args.retry_failed, max_steps=args.max_steps))
    print(json.dumps({'status': result['status'], **result['metrics']}, indent=2))
    raise SystemExit(0 if result['status'] in {'completed', 'checkpointed'} else 1)


if __name__ == '__main__':
    main()
