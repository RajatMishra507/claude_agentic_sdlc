"""Shared constants and helpers for the SDLC engine."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from pathlib import Path

PHASE_ORDER = [
    "requirements", "architecture", "design_review", "planning",
    "implementation", "review", "verify", "pr",
]
AGENTS = {
    "requirements": "requirements",
    "architecture": "architecture",
    "design_review": "design-review",
    "planning": "planning",
    "implementation": "implementation",
    "review": "review",
    "verify": "verify",
    "pr": "pr",
}
ORCHESTRATOR_AGENT = "orchestrator"
STATUSES = ("pending", "in_progress", "submitted", "approved", "rejected")
PRE_PR_PHASES = PHASE_ORDER[:-1]

ROOT = Path(os.environ.get("SDLC_ROOT") or Path(__file__).resolve().parents[1])


class SdlcError(Exception):
    """A refusal or integrity failure; the requested operation did not happen."""


def configure(root) -> None:
    global ROOT
    ROOT = Path(root).resolve()


def path(*parts: str) -> Path:
    return ROOT.joinpath(*parts)


def utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(fp: Path) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(fp: Path, text: str) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_name(fp.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, fp)


def read_json(rel: str) -> dict:
    try:
        return json.loads(path(*rel.split("/")).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SdlcError("cannot read %s: %s" % (rel, exc))


def slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit] or "none"


def load_dotenv() -> None:
    env_file = path(".env")
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
