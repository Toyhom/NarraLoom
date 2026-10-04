"""Pinned assets for the optional Avatar creator; imports no inference libraries."""

import fnmatch
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

CATALOG = {
    "vision": {
        "repo": "Qwen/Qwen3-VL-4B-Instruct",
        "revision": "ebb281ec70b05090aa6165b016eac8ec08e71b17",
        "purpose": "Image understanding and character brief", "license": "Apache-2.0",
    },
    "image": {
        "repo": "black-forest-labs/FLUX.2-klein-4B",
        "revision": "e7b7dc27f91deacad38e78976d1f2b499d76a294",
        "purpose": "Portrait and mouth poses", "license": "Apache-2.0",
        "patterns": ["*/*", "*.json", "*.md", "LICENSE*", "*.txt", ".gitattributes"],
    },
    "voice_design": {
        "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "revision": "5ecdb67327fd37bb2e042aab12ff7391903235d3",
        "purpose": "Voice reference assets required by the creation package", "license": "Apache-2.0",
    },
    "face_landmarker": {
        "path": "google/mediapipe/face_landmarker/float16-1/face_landmarker.task",
        "url": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        "sha256": "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
        "bytes": 3758596, "purpose": "CPU face landmarks", "license": "Apache-2.0",
    },
    "segmentation": {
        "path": "rembg/birefnet-general.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-epoch_244.onnx",
        "sha256": "58f621f00f5d756097615970a88a791584600dcf7c45b18a0a6267535a1ebd3c",
        "bytes": 972666916, "purpose": "CPU foreground extraction", "license": "MIT",
    },
}


def selection(name):
    if name == "avatar-2d":
        return CATALOG
    if name not in CATALOG:
        raise ValueError("Unknown model preset or role")
    return {name: CATALOG[name]}


def destination(root, item):
    root = Path(root).expanduser().resolve()
    path = (root / (item["path"] if "path" in item else item["repo"] + "/" + item["revision"])).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Model destination escapes model root")
    return path


def digest(path, algorithm="sha256", *, git_blob=False):
    result = hashlib.new(algorithm)
    if git_blob:
        result.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def check_file(path, item):
    return (path.is_file() and path.stat().st_size == item["bytes"]
            and (digest(path) == item["sha256"] if "sha256" in item
                 else digest(path, "sha1", git_blob=True) == item["sha1"]))


def download_file(item, target, *, client=None, headers=None):
    """Resume fixed, checksummed public resources; publish only a verified file."""
    if check_file(target, item):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    offset = part.stat().st_size if part.exists() else 0
    if offset >= item["bytes"]:
        if check_file(part, item):
            part.replace(target)
            return
        part.unlink()
        offset = 0
    headers = {**(headers or {}), **({"Range": f"bytes={offset}-"} if offset else {})}
    owned = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=60)
    try:
        with client.stream("GET", item["url"], headers=headers) as response:
            response.raise_for_status()
            if response.status_code == 206:
                expected = f"bytes {offset}-{item['bytes'] - 1}/{item['bytes']}"
                if response.headers.get("content-range") != expected:
                    raise ValueError("Download returned an unexpected byte range")
            elif response.status_code == 200:
                offset = 0
            else:
                raise ValueError("Download returned an unexpected status")
            with part.open("ab" if offset else "wb") as stream:
                for block in response.iter_bytes():
                    offset += len(block)
                    if offset > item["bytes"]:
                        raise ValueError("Download exceeds the pinned size")
                    stream.write(block)
        if not check_file(part, item):
            part.unlink()
            raise ValueError("Download checksum mismatch; retry or use a verified resource URL")
        part.replace(target)
    finally:
        if owned:
            client.close()


def hf_download(item, target, endpoint, token):
    try:
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise ValueError("Install the download extra: python -m pip install '.[download]'") from exc
    info = HfApi(endpoint=endpoint, token=token).model_info(
        item["repo"], revision=item["revision"], files_metadata=True)
    if info.sha != item["revision"]:
        raise ValueError("Model revision differs from the pinned commit")
    patterns = item.get("patterns", ["*"])
    files = [f for f in info.siblings if any(fnmatch.fnmatch(f.rfilename, p) for p in patterns)]
    if not files:
        raise ValueError("Model repository has no matching files")
    # Check repository paths before the downloader writes them.
    for entry in files:
        path = (target / entry.rfilename).resolve()
        if not path.is_relative_to(target.resolve()) or path == target.resolve():
            raise ValueError("Model file escapes its destination")
    (target / ".narraloom-download.json").unlink(missing_ok=True)
    verified = []
    for entry in files:
        path = target / entry.rfilename
        if entry.size is None:
            raise ValueError(f"Missing model file size: {entry.rfilename}")
        lfs = entry.lfs
        sha = (lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)) if lfs else None
        expected = sha or entry.blob_id
        if not expected:
            raise ValueError(f"Missing model checksum: {entry.rfilename}")
        resource = {"url": endpoint.rstrip('/') + '/' + item['repo'] + '/resolve/' + item['revision']
                    + '/' + quote(entry.rfilename, safe='/'), "bytes": entry.size,
                    "sha256" if sha else "sha1": expected}
        # Some HF mirrors omit Hub-specific HEAD headers. Resolve the pinned
        # commit directly and verify every streamed file against the API metadata.
        try:
            download_file(resource, path, headers={"Authorization": "Bearer " + token} if token else {})
        except ValueError as exc:
            raise ValueError(f"Model download failed for {entry.rfilename}: {exc}") from exc
        verified.append({"file": entry.rfilename, "bytes": entry.size, "digest": expected})
    (target / ".narraloom-download.json").write_text(json.dumps({
        "repo": item["repo"], "revision": item["revision"], "endpoint": endpoint, "files": verified,
    }, indent=2) + "\n", encoding="utf-8")


def download(name, root, *, endpoint="https://huggingface.co", token=False, dry_run=False, urls=None):
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query:
        raise ValueError("Use an HTTPS model endpoint without credentials or query parameters")
    items = selection(name)
    urls = urls or {}
    if set(urls) - {role for role, item in CATALOG.items() if "url" in item}:
        raise ValueError("Resource URL overrides apply to face_landmarker or segmentation")
    plan = []
    for role, original in items.items():
        item = {**original, **({"url": urls[role]} if role in urls else {})}
        path = destination(root, item)
        plan.append({"role": role, "destination": str(path), **item})
        if not dry_run:
            print(f"Downloading and verifying {role} ...", file=sys.stderr, flush=True)
            if "repo" in item:
                hf_download(item, path, endpoint, token)
            else:
                download_file(item, path)
    return {"preset": name, "endpoint": endpoint, "dry_run": dry_run, "assets": plan}


def configure(root, env_root, project, *, runner="local"):
    if runner not in {"local", "gpuq"}:
        raise ValueError("Avatar runner must be local or gpuq")
    if sys.platform != "linux":
        raise ValueError("Configure the creator on its Linux or WSL2 GPU host")
    root, env_root, project = [Path(p).expanduser().resolve() for p in (root, env_root, project)]
    if not (project / "scripts/avatar_worker.py").is_file():
        raise ValueError("--project must be a NarraLoom source checkout")
    folder = project / "configs"
    model_file, worker_file = folder / "avatar-models.local.json", folder / "avatar.local.json"
    if model_file.exists() or worker_file.exists():
        raise ValueError("Avatar configuration exists; edit it or choose a fresh checkout")
    models = {role: {"path": str(destination(root, item)), **{
        k: item[k] for k in ("repo", "revision") if k in item}} for role, item in CATALOG.items()}
    env = {"AVATAR_MODEL_ROOT": str(root), "AVATAR_MODELS_CONFIG": str(model_file),
           "AVATAR_IMAGE_BACKEND": "flux2"}
    for role, kind in {"VISION": "vision", "FACE": "face", "PORTRAIT": "portrait",
                       "ASSET": "portrait", "QWEN": "qwen"}.items():
        env[f"AVATAR_{role}_PYTHON"] = str(env_root / kind / "bin/python")
    folder.mkdir(parents=True, exist_ok=True)
    with model_file.open("x", encoding="utf-8") as stream:
        json.dump({"models": models}, stream, indent=2)
    with worker_file.open("x", encoding="utf-8") as stream:
        json.dump({"enabled": True, "runner": runner, "python": sys.executable, "env": env}, stream, indent=2)
    return {"models_config": str(model_file), "worker_config": str(worker_file)}


def check(project):
    """Check configured paths without importing GPU libraries or loading weights."""
    project = Path(project).expanduser().resolve()
    config = json.loads((project / "configs/avatar.local.json").read_text())
    env = config.get("env", {})
    models_path = env.get("AVATAR_MODELS_CONFIG")
    models = json.loads(Path(models_path).read_text()).get("models", {}) if models_path else {}
    checks = []
    for role, item in CATALOG.items():
        entry = models.get(role, {})
        override = entry.get("path")
        path = (Path(os.path.expandvars(override)).expanduser() if override
                else destination(env["AVATAR_MODEL_ROOT"], {**item, **entry}))
        if "repo" in item:
            filename = "model_index.json" if role == "image" else "config.json"
            present = (path / filename).is_file() and any(path.rglob("*.safetensors"))
        else:
            present = path.is_file() and path.stat().st_size == item["bytes"]
        checks.append({"role": role, "path": str(path), "present": present})
    for key in ("AVATAR_VISION_PYTHON", "AVATAR_FACE_PYTHON", "AVATAR_PORTRAIT_PYTHON", "AVATAR_QWEN_PYTHON"):
        path = Path(env[key])
        checks.append({"role": key, "path": str(path), "present": path.is_file() and os.access(path, os.X_OK)})
    path = Path(config["python"])
    checks.append({"role": "worker_python", "path": str(path), "present": path.is_file() and os.access(path, os.X_OK)})
    return {"ready": all(c["present"] for c in checks), "checks": checks,
            "scope": "File presence and interpreter paths; download verifies hashes, creation tests GPU inference"}


def add_parser(commands):
    parser = commands.add_parser("models", help="List/download/configure optional Avatar model assets")
    sub = parser.add_subparsers(dest="models_command", required=True)
    sub.add_parser("list", help="Show pinned roles, models and resources")
    doctor = sub.add_parser("check", help="Check configured files and interpreters without loading models")
    doctor.add_argument("--project", type=Path, default=Path.cwd())
    get = sub.add_parser("download", help="Download fixed revisions and verify their checksums")
    get.add_argument("preset", choices=["avatar-2d", *CATALOG])
    get.add_argument("--model-root", type=Path, required=True)
    endpoint = get.add_mutually_exclusive_group()
    endpoint.add_argument("--mirror", action="store_true", help="Use https://hf-mirror.com for HF repositories")
    endpoint.add_argument("--endpoint", default="https://huggingface.co")
    get.add_argument("--token-env", help="Explicit credential variable; default sends no HF credentials")
    get.add_argument("--dry-run", action="store_true", help="Print paths/revisions without network or disk writes")
    get.add_argument("--resource-urls", type=Path, help="JSON mapping of auxiliary resource roles to download URLs")
    config = sub.add_parser("configure", help="Write source creator configuration without replacing existing files")
    config.add_argument("preset", choices=["avatar-2d"])
    config.add_argument("--model-root", type=Path, required=True)
    config.add_argument("--env-root", type=Path, required=True)
    config.add_argument("--project", type=Path, default=Path.cwd())
    config.add_argument("--runner", choices=["local", "gpuq"], default="local")


def run(args):
    if args.models_command == "list":
        result = {"avatar-2d": CATALOG}
    elif args.models_command == "check":
        result = check(args.project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ready"]:
            raise ValueError("Avatar setup is incomplete; install the missing paths shown above")
        return
    elif args.models_command == "download":
        token = os.environ.get(args.token_env) if args.token_env else False
        if args.token_env and not token:
            raise ValueError("The selected token environment variable is empty")
        urls = json.loads(args.resource_urls.read_text()) if args.resource_urls else None
        if urls is not None and (not isinstance(urls, dict) or not all(isinstance(v, str) for v in urls.values())):
            raise ValueError("Resource URLs must be a JSON object of URL strings")
        result = download(args.preset, args.model_root, endpoint="https://hf-mirror.com" if args.mirror else args.endpoint,
                          token=token, dry_run=args.dry_run, urls=urls)
    else:
        result = configure(args.model_root, args.env_root, args.project, runner=args.runner)
    print(json.dumps(result, ensure_ascii=False, indent=2))
