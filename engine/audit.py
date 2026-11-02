"""Append-only, hash-chained audit log.

Each entry records timestamp, phase, agent, action, actor and free-form details
(approval/rejection, artifact path, validation, MCP evidence refs, PR evidence).
Entries chain by hash and carry the digest of the state they produced.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from . import common as c


def _file():
    return c.path("sdlc", "audit.jsonl")


def read() -> list:
    fp = _file()
    if not fp.is_file():
        return []
    return [json.loads(line) for line in fp.read_text(encoding="utf-8").splitlines() if line.strip()]


def head() -> Optional[dict]:
    entries = read()
    return entries[-1] if entries else None


def append(action: str, state_digest: str, *, phase: Optional[str] = None, agent: Optional[str] = None,
           actor: str = "orchestrator", **details) -> dict:
    entries = read()
    entry = {
        "seq": len(entries) + 1,
        "ts": c.utcnow(),
        "phase": phase,
        "agent": agent,
        "action": action,
        "actor": actor,
        "details": details,
        "state_sha256": state_digest,
        "prev_hash": entries[-1]["hash"] if entries else "GENESIS",
    }
    entry["hash"] = c.sha256_text(c.canonical(entry))
    fp = _file()
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return entry


def verify() -> int:
    prev = "GENESIS"
    entries = read()
    for i, entry in enumerate(entries, 1):
        body = {k: v for k, v in entry.items() if k != "hash"}
        if entry.get("seq") != i or entry.get("prev_hash") != prev or c.sha256_text(c.canonical(body)) != entry.get("hash"):
            raise c.SdlcError("audit log broken at entry %d" % i)
        prev = entry["hash"]
    return len(entries)
