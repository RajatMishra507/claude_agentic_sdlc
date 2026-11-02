"""Pipeline state, bound to the audit log so out-of-band edits are detected."""
from __future__ import annotations

import contextlib
import fcntl
import json
import uuid
from typing import Optional

from . import audit
from . import common as c

VERSION = 2


@contextlib.contextmanager
def exclusive_lock():
    lock_path = c.path("sdlc", ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise c.SdlcError("another orchestrator operation is in progress")
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def fresh_phase() -> dict:
    return {"status": "pending", "attempt": 0, "history": []}


def new_state() -> dict:
    return {
        "version": VERSION,
        "run_id": uuid.uuid4().hex[:12],
        "created_at": c.utcnow(),
        "phases": {pid: fresh_phase() for pid in c.PHASE_ORDER},
        "pr_authorization": None,
    }


def digest(state: dict) -> str:
    return c.sha256_text(c.canonical({k: v for k, v in state.items() if k != "audit_head"}))


def load() -> Optional[dict]:
    fp = c.path("sdlc", "state.json")
    raw = fp.read_text(encoding="utf-8").strip() if fp.is_file() else ""
    entries = audit.read()
    if not raw:
        if entries:
            raise c.SdlcError("state.json is missing/empty but the audit log exists; refusing to continue")
        return None
    try:
        state = json.loads(raw)
    except ValueError as exc:
        raise c.SdlcError("state.json is not valid JSON: %s" % exc)
    if state.get("version") != VERSION:
        raise c.SdlcError("unsupported state version %r (expected %d)" % (state.get("version"), VERSION))
    if not entries:
        raise c.SdlcError("state.json has content but the audit log is empty; refusing to continue")
    audit.verify()
    last = entries[-1]
    if state.get("audit_head") != {"seq": last["seq"], "hash": last["hash"]} or last["state_sha256"] != digest(state):
        raise c.SdlcError("state.json does not match the audit log (modified outside the orchestrator, "
                          "or the audit log was truncated)")
    return state


def save(state: dict, action: str, *, phase: Optional[str] = None, agent: Optional[str] = None,
         actor: str = "orchestrator", **details) -> None:
    entry = audit.append(action, digest(state), phase=phase, agent=agent, actor=actor, **details)
    state["audit_head"] = {"seq": entry["seq"], "hash": entry["hash"]}
    c.atomic_write(c.path("sdlc", "state.json"), json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def init() -> dict:
    state = new_state()
    save(state, "pipeline_initialized")
    return state


def load_or_init() -> dict:
    return load() or init()


def next_phase(state: dict) -> Optional[str]:
    return next((p for p in c.PHASE_ORDER if state["phases"][p]["status"] != "approved"), None)


def unapproved_predecessor(state: dict, phase_id: str) -> Optional[str]:
    for pid in c.PHASE_ORDER[:c.PHASE_ORDER.index(phase_id)]:
        if state["phases"][pid]["status"] != "approved":
            return pid
    return None


def verify_approved_integrity(state: dict) -> None:
    for pid in c.PHASE_ORDER:
        ps = state["phases"][pid]
        if ps["status"] != "approved":
            continue
        fp = c.path(ps["artifact"])
        if not fp.is_file() or c.sha256_file(fp) != ps["approval"]["artifact_sha256"]:
            raise c.SdlcError("approved artifact for %s was modified after approval; pipeline halted" % pid)


def approvals_digest(state: dict) -> Optional[str]:
    pairs = []
    for pid in c.PRE_PR_PHASES:
        ps = state["phases"][pid]
        if ps["status"] != "approved":
            return None
        pairs.append([pid, ps["approval"]["artifact_sha256"]])
    return c.sha256_text(c.canonical(pairs))


def pr_authorization_valid(state: dict) -> bool:
    auth = state.get("pr_authorization")
    return bool(auth and auth.get("status") == "authorized"
                and auth.get("approvals_digest") == approvals_digest(state))
