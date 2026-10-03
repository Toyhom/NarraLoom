"""Single-host, checksummed append journal. Durable facts never depend on a cache."""

import hashlib
import json
import os
import socket
import threading
import time
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def node_identity():
    p = Path("/etc/unified-users/instance")
    return p.read_text().strip() if p.exists() else socket.gethostname()


class Journal:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "journal.jsonl"
        self.mutex = threading.RLock()
        self.poisoned = False
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            # Linux abstract sockets give same-host exclusion without relying on FUSE file locks.
            self.socket.bind("\0rpw-" + hashlib.sha256(str(self.root).encode()).hexdigest()[:48])
            owner_path = self.root / "writer-node.json"
            if owner_path.exists():
                if json.loads(owner_path.read_text())["node"] != node_identity():
                    raise RuntimeError("This store belongs to another host; automatic failover is disabled")
            else:
                with owner_path.open("x") as f:
                    json.dump({"node": node_identity()}, f)
                    f.flush()
                    os.fsync(f.fileno())
            self.records = self._recover()
            self.previous = self.records[-1]["checksum"] if self.records else "0" * 64
            existed = self.path.exists()
            self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            if not existed:
                self._sync_dir()
        except BaseException:
            self.socket.close()
            raise

    def _sync_dir(self):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _recover(self):
        if not self.path.exists():
            return []
        result, previous, offset = [], "0" * 64, 0
        with self.path.open("rb") as f:
            while True:
                raw = f.readline(8 * 1024 * 1024 + 1)
                if not raw:
                    break
                if len(raw) > 8 * 1024 * 1024:
                    raise RuntimeError("Journal frame exceeds its limit; store left untouched")
                if not raw.endswith(b"\n"):
                    recovery = self.root / (f"recovery-tail-{time.time_ns()}.bin")
                    with recovery.open("xb") as target:
                        target.write(raw)
                        target.flush()
                        os.fsync(target.fileno())
                    with self.path.open("r+b") as target:
                        target.truncate(offset)
                        target.flush()
                        os.fsync(target.fileno())
                    break
                try:
                    frame = json.loads(raw)
                    body = frame["body"]
                    if frame["previous"] != previous or digest([previous, body]) != frame["checksum"]:
                        raise ValueError("hash chain")
                except (ValueError, KeyError, TypeError) as e:
                    raise RuntimeError(f"Corrupt journal frame at byte {offset}; store left untouched") from e
                result.append(frame)
                previous = frame["checksum"]
                offset += len(raw)
        return result

    def append(self, body):
        with self.mutex:
            if self.poisoned:
                raise RuntimeError("Journal requires recovery after a write failure")
            frame = {"previous": self.previous, "body": body, "checksum": digest([self.previous, body])}
            raw = canonical(frame) + b"\n"
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("Journal frame too large")
            try:
                offset = 0
                while offset < len(raw):
                    count = os.write(self.fd, raw[offset:])
                    if count <= 0:
                        raise OSError("Short journal write")
                    offset += count
                os.fsync(self.fd)
            except BaseException:
                self.poisoned = True
                raise
            self.previous = frame["checksum"]
            self.records.append(frame)
            return frame

    def close(self):
        if getattr(self, "fd", None) is not None:
            os.close(self.fd)
            self.fd = None
        self.socket.close()
