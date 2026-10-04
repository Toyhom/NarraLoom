#!/usr/bin/env bash
set -euo pipefail
rpw_project="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$rpw_project/scripts/avatar_worker.py" "$@"
