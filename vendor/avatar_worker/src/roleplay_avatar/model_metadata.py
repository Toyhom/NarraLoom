"""Checkpoint attribution for generated packages, including user-selected models."""

import json
import os
from pathlib import Path

from .model_catalog import catalog
from .models import DEFAULTS, ROOT, agent_config, model_options, model_path


def model_metadata(role, path=None):
    options = model_options(role)
    if options.get("adapter") == "api":
        agent = agent_config(role)
        return {"model": agent["model"], "license": "provider terms", "provider": agent.get("provider", "")}
    path = Path(path).resolve() if path is not None else model_path(role)
    receipt = {}
    for name in (".avatar-download.json", ".snapshot-integrity.json"):
        record = path / name
        if record.is_file():
            receipt = json.loads(record.read_text())
            break
    repo, revision = DEFAULTS.get(role, ("", ""))
    default_path = (Path(os.environ.get("AVATAR_MODEL_ROOT", ROOT / "models")) / repo / revision).resolve()
    model = receipt.get("repo") or options.get("repo") or (repo if path == default_path else path.name)
    revision = receipt.get("revision") or options.get("revision") or (revision if path == default_path else "")
    entry = next((value for value in catalog().values() if value["repo"] == model), {})
    result = {"model": model, "revision": revision,
              "license": options.get("license") or entry.get("license", "unspecified")}
    return result


def source_record(component, metadata):
    """Use stage records so repackaging preserves the model that did the work."""
    model = metadata["model"]
    entry = next((value for value in catalog().values() if value["repo"] == model), {})
    result = {"component": component, "source": model,
              "license": metadata.get("license") or entry.get("license", "unspecified")}
    revision = metadata.get("revision", entry.get("revision"))
    if revision:
        result["revision"] = revision
    return result
