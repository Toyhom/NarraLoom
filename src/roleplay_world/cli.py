"""Installed backend entry point, without Node, browser assets or repository scripts."""

import argparse
import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path

from . import __version__
from .config import AppConfig


def main(argv=None):
    parser = argparse.ArgumentParser(description="NarraLoom story-game framework backend")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run one backend writer; API only unless --web-dist is supplied")
    serve.add_argument("--workspace", type=Path, help="Base for relative paths (default: current directory)")
    serve.add_argument("--data-root", type=Path)
    serve.add_argument("--output-root", type=Path)
    serve.add_argument("--models-config", type=Path)
    serve.add_argument("--secrets-root", type=Path)
    serve.add_argument("--web-dist", type=Path, help="Serve an already built reference frontend")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=18090)
    evaluate = commands.add_parser("evaluate", help="Evaluate frozen JSONL module tasks (research extra)")
    evaluate.add_argument("--cases", type=Path, required=True)
    evaluate.add_argument("--models-config", type=Path, required=True)
    evaluate.add_argument("--secrets-root", type=Path, default=Path.cwd() / "secrets")
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--repeats", type=int, default=1)
    evaluate.add_argument("--max-repairs", type=int, default=0)
    evaluate.add_argument("--resume", action="store_true")
    compare = commands.add_parser("compare", help="Compare completed evaluations of the same tasks")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command in {"evaluate", "compare"}:
        from . import evaluation
        try:
            if args.command == "evaluate":
                cases = evaluation.load_cases(args.cases)
                try:
                    config = json.loads(args.models_config.read_text())
                    if not isinstance(config, dict):
                        raise TypeError()
                except (OSError, ValueError, TypeError):
                    parser.error("Cannot read model configuration object")
                result = asyncio.run(evaluation.evaluate(
                    cases, config=config, output=args.output, secrets_root=args.secrets_root,
                    repeats=args.repeats, max_repairs=args.max_repairs, resume=args.resume))
                print(json.dumps(result['metrics'], ensure_ascii=False, indent=2))
                stats = result['metrics']['overall']
                parser.exit(1 if stats['schema_valid'] < stats['cases'] or stats['passed'] < stats['scored_cases'] else 0)
            else:
                result = evaluation.compare(json.loads(args.baseline.read_text()), json.loads(args.candidate.read_text()))
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open('x') as handle:
                    handle.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
                print(json.dumps({key: result[key] for key in ('improved', 'regressed')}, indent=2))
                return
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    # CLI flags override RPW settings; an installed command never defaults to
    # writing in site-packages or silently starts the source reference frontend.
    overrides = {name: getattr(args, name) for name in (
        "data_root", "output_root", "models_config", "secrets_root", "web_dist"
    ) if getattr(args, name) is not None}
    # Rebuild unresolved defaults when the workspace changes.
    try:
        workspace = args.workspace if args.workspace is not None else os.environ.get("RPW_WORKSPACE", Path.cwd())
        config = AppConfig.from_env({**os.environ, "RPW_WORKSPACE": str(workspace)})
        config = replace(config, **overrides, headless=args.web_dist is None)
        from .app import create_app
        app = create_app(config=config)
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
