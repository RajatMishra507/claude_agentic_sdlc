"""Loading and validating sdlc/phases.json and sdlc/config.json."""
from __future__ import annotations

from . import common as c

DEFAULT_PROTECTED = ["main", "master", "develop", "release/*"]


def load_phases() -> dict:
    data = c.read_json("sdlc/phases.json")
    phases = data.get("phases", [])
    ids = [p.get("id") for p in phases]
    if ids != c.PHASE_ORDER:
        raise c.SdlcError("phases.json must define exactly %s in order, got %s" % (c.PHASE_ORDER, ids))
    for i, ph in enumerate(phases, 1):
        if ph.get("agent") != c.AGENTS[ph["id"]]:
            raise c.SdlcError("phase %s must use agent %s" % (ph["id"], c.AGENTS[ph["id"]]))
        if ph.get("order") != i:
            raise c.SdlcError("phase %s must have order %d" % (ph["id"], i))
        if ph.get("approval_required") is not True:
            raise c.SdlcError("phase %s must set approval_required: true (no automatic approvals)" % ph["id"])
    return data


def phase_def(data: dict, phase_id: str) -> dict:
    if phase_id not in c.PHASE_ORDER:
        raise c.SdlcError("unknown phase %r; valid phases: %s" % (phase_id, ", ".join(c.PHASE_ORDER)))
    return next(p for p in data["phases"] if p["id"] == phase_id)


def load_config() -> dict:
    config = c.read_json("sdlc/config.json")
    config.setdefault("branch_prefix", "sdlc/")
    config.setdefault("base_branch", "main")
    config.setdefault("protected_branches", list(DEFAULT_PROTECTED))
    return config
