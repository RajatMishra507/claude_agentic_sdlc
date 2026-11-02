"""Phase lifecycle: start -> (agent works) -> submit -> [human approves] ."""
from __future__ import annotations

import json
import re
from typing import Optional

from . import common as c
from . import config as cfg
from . import evidence, runner, state as st, validators


def draft_path(phase_id: str):
    return c.path("artifacts", phase_id, "draft.json")


def artifact_path(phase_id: str) -> str:
    """Canonical, engine-written artifact for a phase, e.g. artifacts/design-review.md."""
    return "artifacts/%s.md" % c.AGENTS[phase_id]


def verification_error(state: dict) -> Optional[str]:
    ps = state["phases"]["verify"]
    if ps["status"] != "approved" or ps.get("verdict") != "PASS":
        return "verification has not passed: the verify phase must be approved with a PASS verdict"
    return None


def _baseline_path(attempt_id: str):
    return c.path("sdlc", "runs", attempt_id.replace(":", "_") + ".baseline.json")


def _require_state() -> dict:
    state = st.load()
    if state is None:
        raise c.SdlcError("pipeline is not initialized; run 'python3 orchestrator.py init --approver YOUR_ID'")
    return state


def _preflight(phase_id: str, state: dict, config: dict) -> None:
    if phase_id == "requirements" and not config.get("requirements_sources"):
        raise c.SdlcError("sdlc/config.json: requirements_sources is empty; list the Confluence/Jira URLs to read")
    if phase_id == "pr" and verification_error(state):
        raise c.SdlcError("cannot start pr: " + verification_error(state))
    if phase_id == "pr" and not st.pr_authorization_valid(state):
        raise c.SdlcError("the PR is not authorized (or the authorization is outdated); "
                          "a human must run 'python3 orchestrator.py authorize-pr --repo ... --head ... --base ... --approver ID'")


def _begin(state: dict, data: dict, config: dict, phase_id: str, retry: bool):
    """Move a phase to in_progress. Returns (phase def, feedback, baseline snapshot)."""
    ph, ps = cfg.phase_def(data, phase_id), state["phases"][phase_id]
    blocker = st.unapproved_predecessor(state, phase_id)
    if blocker:
        raise c.SdlcError("cannot start %s: predecessor %s is not approved (phases cannot be skipped)" % (phase_id, blocker))
    if ps["status"] == "approved":
        raise c.SdlcError("%s is already approved; use 'reopen' to change it" % phase_id)
    if ps["status"] == "submitted":
        raise c.SdlcError("%s is awaiting human approval; approve or reject it first" % phase_id)
    if ps["status"] == "in_progress" and not retry:
        errors = ps.get("last_validation_errors") or ["a previous run did not finish"]
        raise c.SdlcError("%s is in progress and blocked; review the problem, then rerun with --retry\n  %s"
                          % (phase_id, "\n  ".join(errors)))
    st.verify_approved_integrity(state)
    _preflight(phase_id, state, config)

    feedback = None
    if ps["status"] == "rejected":
        feedback = "Rejected by a human reviewer: %s" % ps["rejection"]["reason"]
        ps["history"].append({"rejection": ps.pop("rejection"), "attempt": ps["attempt"]})
    elif ps.get("last_validation_errors"):
        feedback = "Automated validation failed:\n- " + "\n- ".join(ps["last_validation_errors"])
        ps["history"].append({"validation_errors": ps["last_validation_errors"], "attempt": ps["attempt"]})
    for key in ("artifact", "artifact_sha256", "evidence_sha256", "summary", "validation", "submitted_by",
                "submitted_at", "last_validation_errors", "approval", "verdict", "files", "questions"):
        ps.pop(key, None)

    ps.update({"status": "in_progress", "attempt": ps["attempt"] + 1, "agent": ph["agent"], "started_at": c.utcnow()})
    ps["attempt_id"] = "%s:%s:%d" % (state["run_id"], phase_id, ps["attempt"])
    draft_path(phase_id).parent.mkdir(parents=True, exist_ok=True)
    baseline = runner.snapshot()
    c.atomic_write(_baseline_path(ps["attempt_id"]), json.dumps(baseline))
    st.save(state, "phase_started", phase=phase_id, agent=ph["agent"], actor="orchestrator",
            attempt=ps["attempt"], attempt_id=ps["attempt_id"])
    return ph, feedback, baseline


def start_phase(phase_id: str, retry: bool = False) -> dict:
    with st.exclusive_lock():
        data, config, state = cfg.load_phases(), cfg.load_config(), _require_state()
        cfg.phase_def(data, phase_id)
        _begin(state, data, config, phase_id, retry)
        return {"phase": phase_id, "status": "in_progress", "draft": str(draft_path(phase_id).relative_to(c.ROOT))}


def _submit(state: dict, data: dict, config: dict, phase_id: str, submitted_by: str,
            changed: Optional[list] = None) -> dict:
    ph, ps = cfg.phase_def(data, phase_id), state["phases"][phase_id]
    blocker = st.unapproved_predecessor(state, phase_id)
    if blocker:
        raise c.SdlcError("cannot submit %s: predecessor %s is not approved" % (phase_id, blocker))
    if ps["status"] != "in_progress":
        raise c.SdlcError("cannot submit %s while it is %s; it must be in_progress (start it first)" % (phase_id, ps["status"]))
    try:
        draft = json.loads(draft_path(phase_id).read_text(encoding="utf-8"))
        if not isinstance(draft, dict):
            raise ValueError("draft must be a JSON object")
    except (OSError, ValueError) as exc:
        raise c.SdlcError("no valid draft at %s: %s" % (draft_path(phase_id).relative_to(c.ROOT), exc))
    if changed is None:
        baseline = json.loads(_baseline_path(ps["attempt_id"]).read_text(encoding="utf-8"))
        changed = runner.changed_files(baseline, runner.snapshot())

    entries, problems = evidence.read_attempt(c.ROOT, ps["attempt_id"])
    auth = state["pr_authorization"] if phase_id == "pr" else None
    errors, resolved = validators.validate_draft(ph, draft, entries, problems, config, changed, auth)
    if errors:
        ps["last_validation_errors"] = errors
        ps["validation"] = {"passed": False, "errors": errors}
        st.save(state, "validation_failed", phase=phase_id, agent=ps["agent"], actor=submitted_by, errors=errors)
        return {"ok": False, "phase": phase_id, "errors": errors}

    rel = artifact_path(phase_id)
    markdown = draft["artifact_markdown"].rstrip() + "\n"
    c.atomic_write(c.path(rel), markdown)
    c.atomic_write(c.path("artifacts", phase_id, "attempt-%d.md" % ps["attempt"]), markdown)
    if resolved:
        c.atomic_write(c.path(rel[:-3] + ".evidence.json"), json.dumps(resolved, indent=2))
        ps["evidence_sha256"] = c.sha256_file(c.path(rel[:-3] + ".evidence.json"))
    ps.update({
        "status": "submitted", "artifact": rel, "artifact_sha256": c.sha256_text(markdown),
        "summary": draft["summary"], "submitted_by": submitted_by, "submitted_at": c.utcnow(),
        "validation": {"passed": True, "checks": ph.get("checks", []), "files_changed": changed},
        "questions": [str(q) for q in (draft.get("questions") or [])],
    })
    if "verify_verdict" in ph.get("checks", []):
        ps["verdict"] = validators.extract_verdict(markdown)
    if "files_changed" in ph.get("checks", []):
        ps["files"] = {f: c.sha256_file(c.path(f)) for f in changed if c.path(f).is_file()}
    ps.pop("last_validation_errors", None)
    refs = resolved if isinstance(resolved, list) else ([resolved] if resolved else [])
    mcp_refs = [{k: r[k] for k in ("id", "source_url", "url", "tool_name", "tool_use_id", "log_mac") if r.get(k)}
                for r in refs]
    details = {"artifact": rel, "artifact_sha256": ps["artifact_sha256"], "validation": ps["validation"],
               "mcp_evidence": mcp_refs}
    if phase_id == "pr":
        pr_auth = state["pr_authorization"]
        pr_auth.update({"status": "consumed", "pr_url": draft["pr"]["url"], "consumed_at": c.utcnow()})
        details["pr_creation"] = {"authorization_id": pr_auth["id"], "pr_url": draft["pr"]["url"],
                                  "branch": draft["pr"]["branch"]}
    st.save(state, "phase_submitted", phase=phase_id, agent=ps["agent"], actor=submitted_by, **details)
    return {"ok": True, "phase": phase_id, "artifact": rel, "sha256": ps["artifact_sha256"],
            "questions": ps["questions"], "message": "%s submitted and validated; awaiting human approval" % phase_id}


def submit_phase(phase_id: str, submitter: str) -> dict:
    """Validate the draft already placed at artifacts/<phase>/draft.json. Human-run entry point."""
    with st.exclusive_lock():
        data, config, state = cfg.load_phases(), cfg.load_config(), _require_state()
        cfg.phase_def(data, phase_id)
        return _submit(state, data, config, phase_id, "human:%s" % submitter)


def run_phase(phase_id: Optional[str] = None, retry: bool = False) -> dict:
    """Start the next phase, run its agent, validate and submit, then stop for human approval."""
    with st.exclusive_lock():
        data, config = cfg.load_phases(), cfg.load_config()
        state = st.load_or_init()
        target = st.next_phase(state)
        if target is None:
            return {"ok": True, "phase": None, "message": "pipeline complete; all phases approved"}
        if phase_id and phase_id != target:
            raise c.SdlcError("cannot run %s: the next phase is %s (phases cannot be skipped or reordered)" % (phase_id, target))
        ph, feedback, baseline = _begin(state, data, config, target, retry)
        ps = state["phases"][target]
        try:
            prompt = runner.build_prompt(ph, state, config, feedback, ps["attempt_id"])
            draft = runner.invoke_agent(ph, data["common_tools"], prompt, ps["attempt_id"])
        except c.SdlcError as exc:
            ps["last_validation_errors"] = [str(exc)]
            st.save(state, "agent_failed", phase=target, agent=ph["agent"], error=str(exc))
            return {"ok": False, "phase": target, "errors": [str(exc)]}
        changed = runner.changed_files(baseline, runner.snapshot())
        c.atomic_write(draft_path(target), json.dumps(draft, indent=2))
        return _submit(state, data, config, target, "agent:%s" % ph["agent"], changed)
