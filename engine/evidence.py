"""Signed tool-call evidence log, shared by the PostToolUse hook and the engine.

Only stdlib is used so hooks/guard.py can import it. Each entry carries an HMAC
(keyed by sdlc/.evidence_key, which agents may not read) chained to the previous
entry, so agents cannot fabricate or splice MCP evidence without detection.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path

LOG_REL = "sdlc/tool_log.jsonl"


def secret_dir() -> Path:
    """Per-user directory outside the project for the signing key and approver credentials."""
    return Path(os.environ.get("SDLC_KEY_DIR") or (Path.home() / ".config" / "sdlc-engine"))


def _tag(root: Path) -> str:
    return hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:16]


def key_path(root: Path) -> Path:
    return secret_dir() / (_tag(root) + ".key")


def approvers_path(root: Path) -> Path:
    return secret_dir() / (_tag(root) + ".approvers.json")


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _key(root: Path):
    try:
        return bytes.fromhex(key_path(root).read_text().strip())
    except (OSError, ValueError):
        return None


def ensure_key(root: Path) -> None:
    fp = key_path(root)
    if fp.is_file():
        return
    fp.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(fp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(os.urandom(32).hex())


def _mac(key: bytes, entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "mac"}
    return hmac.new(key, _canonical(body).encode("utf-8"), hashlib.sha256).hexdigest()


def append(root: Path, entry: dict) -> None:
    key = _key(root)
    if key is None:
        raise RuntimeError("evidence key missing; run 'python3 orchestrator.py init'")
    fp = Path(root) / LOG_REL
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        lines = [line for line in fh.read().splitlines() if line.strip()]
        prev = json.loads(lines[-1]).get("mac", "GENESIS") if lines else "GENESIS"
        entry = dict(entry, prev_mac=prev)
        entry["mac"] = _mac(key, entry)
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_attempt(root: Path, attempt_id: str):
    """Return (entries for attempt_id, problems). Any problem means the log is untrustworthy."""
    fp = Path(root) / LOG_REL
    if not fp.is_file():
        return [], []
    key = _key(root)
    if key is None:
        return [], ["evidence key missing"]
    entries, problems, prev = [], [], "GENESIS"
    for n, line in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            problems.append("tool log line %d is not valid JSON" % n)
            continue
        if entry.get("prev_mac") != prev or not hmac.compare_digest(str(entry.get("mac", "")), _mac(key, entry)):
            problems.append("tool log line %d failed signature/chain verification" % n)
        prev = entry.get("mac", "")
        if entry.get("attempt_id") == attempt_id:
            entries.append(entry)
    return entries, problems
