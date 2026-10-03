"""Installed backend entry point, without Node, browser assets or repository scripts."""

import argparse
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
    args = parser.parse_args(argv)
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
