"""Deployment paths for an embedded application or an installed backend.

These are trusted host settings, never fields accepted from a player or a card.
An explicit AppConfig is independent of process-wide RPW environment variables.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def default_workspace() -> Path:
    """Keep source-checkout defaults; a wheel uses its caller's working directory."""
    source = Path(__file__).resolve().parents[2]
    if (source / "pyproject.toml").is_file() and (source / "src/roleplay_world/config.py").resolve() == Path(__file__).resolve():
        return source
    return Path.cwd()


@dataclass(frozen=True)
class AppConfig:
    workspace_root: Path = field(default_factory=Path.cwd)
    data_root: Path | None = None
    output_root: Path | None = None
    models_config: Path | None = None
    secrets_root: Path | None = None
    web_dist: Path | None = None
    headless: bool = True

    def __post_init__(self):
        root = Path(self.workspace_root).expanduser().resolve()
        object.__setattr__(self, "workspace_root", root)
        defaults = {"data_root": "data", "output_root": "outputs", "secrets_root": "secrets", "web_dist": "web/dist"}
        for name, fallback in defaults.items():
            value = getattr(self, name)
            object.__setattr__(self, name, (root / Path(value if value is not None else fallback).expanduser()).resolve())
        if self.models_config is not None:
            object.__setattr__(self, "models_config", (root / Path(self.models_config).expanduser()).resolve())

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        root = Path(env.get("RPW_WORKSPACE", default_workspace())).expanduser().resolve()
        # Existing source deployments keep the reference UI; installed packages
        # have no UI dependency. Explicit AppConfig always defaults to headless.
        source_mode = (root / "src/roleplay_world/config.py").resolve() == Path(__file__).resolve()
        headless = env.get("RPW_HEADLESS", "0" if source_mode else "1")
        if headless not in {"0", "1"}:
            raise ValueError("RPW_HEADLESS must be 0 or 1")
        return cls(workspace_root=root, headless=headless == "1", **{
            name: env.get(key) for name, key in {
                "data_root": "RPW_DATA_ROOT", "output_root": "RPW_OUTPUT_ROOT",
                "models_config": "RPW_MODELS_CONFIG", "secrets_root": "RPW_SECRETS_ROOT",
                "web_dist": "RPW_WEB_DIST",
            }.items()
        })

    def load_models(self) -> dict:
        path = self.models_config or self.workspace_root / "configs/models.local.json"
        if not path.exists() and self.models_config is None:
            return {}
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            # Never echo a malformed config: it may contain a credential.
            raise ValueError(f"Cannot read model configuration: {path}") from exc
        if not isinstance(value, dict):
            raise TypeError("Model configuration must be a JSON object")
        return value
