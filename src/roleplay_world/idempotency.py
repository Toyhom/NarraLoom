"""Durable identities for native creation requests; no process-local response cache."""

from .contracts import DomainError
from .journal import digest


def identity(scope, owner, request_id, payload):
    key = scope + "_" + digest(["client-request-v1", scope, owner, request_id])[:32]
    return key, digest(payload)


def receipt(records, key, owner, fingerprint):
    value = records.get(key)
    if value is None:
        return None
    if value.get("owner") != owner or value.get("request_hash") != fingerprint:
        raise DomainError("request_id_conflict", "同一请求标识不能用于不同的创建内容", 409)
    return value
