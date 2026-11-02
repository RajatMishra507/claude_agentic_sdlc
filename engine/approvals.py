"""Human-only operations: init, approve, reject, reopen, authorize-pr.

Every function here needs a `console` for a human at a terminal and a registered
approver who proves a passphrase. None of them can be completed by an agent.
"""
from __future__ import annotations

import fnmatch
import re
import shutil
import uuid
from typing import Optional

from . import auth, evidence
from . import common as c
from . import config as cfg
from . import prcontent, state as st, validators, workflow

MIN_REASON = 5
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _need_state() -> dict:
    state = st.load()
    if state is None:
        raise c.SdlcError("pipeline is not initialized; run 'python3 orchestrator.py init --approver YOUR_ID'")
    return state


def _authenticate(console, state: dict, approver: str, action: str, phase: Optional[str]) -> str:
    try:
        return auth.require_approver(console, approver)
    except c.SdlcError as exc:
        st.save(state, "authentication_failed", phase=phase, actor="human:%s" % approver, attempted=action, reason=str(exc))
        raise


def _confirm(console, state: dict, expected: str, action: str, phase: Optional[str], approver: str) -> None:
    if console.ask("Type exactly '%s' to confirm (anything else cancels): " % expected) != expected:
        st.save(state, "%s_cancelled" % action, phase=phase, actor="human:%s" % approver)
        raise c.SdlcError("%s cancelled; nothing changed" % action)


def _reason(reason: Optional[str]) -> str:
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON:
        raise c.SdlcError("a reason of at least %d characters is required (--reason)" % MIN_REASON)
    return reason


def init_pipeline(approvers: list, console) -> dict:
    """Create state and signing key; register human approvers with passphrases."""
    with st.exclusive_lock():
        evidence.ensure_key(c.ROOT)
        state = st.load_or_init()
        registered = []
        for approver in approvers:
            auth.validate_id(approver)
            if approver in auth.registry():
                raise c.SdlcError("approver %r is already registered" % approver)
            actor = "bootstrap"
            if auth.registry():
                existing = console.ask("An existing approver must authorize this. Existing approver id: ")
                actor = "human:%s" % _authenticate(console, state, existing, "register_approver", None)
            secret = console.secret("New passphrase for %s (min %d chars): " % (approver, auth.MIN_SECRET))
            if secret != console.secret("Repeat passphrase: "):
                raise c.SdlcError("passphrases do not match")
            auth.register(approver, secret)
            st.save(state, "approver_registered", actor=actor, approver=approver)
            registered.append(approver)
        return {"run_id": state["run_id"], "registered": registered, "approvers": sorted(auth.registry())}


def _check_actionable(state: dict, ph: dict, phase_id: str, approver: str) -> dict:
    ps = state["phases"][phase_id]
    blocker = st.unapproved_predecessor(state, phase_id)
    if blocker:
        raise c.SdlcError("cannot act on %s: predecessor %s is not approved" % (phase_id, blocker))
    if ps["status"] == "approved":
        raise c.SdlcError("%s is already approved (duplicate approval refused)" % phase_id)
    if ps["status"] != "submitted":
        raise c.SdlcError("%s is %s; only a submitted phase can be approved or rejected" % (phase_id, ps["status"]))
    if ps.get("submitted_by") == "human:%s" % approver:
        raise c.SdlcError("%s cannot approve or reject their own submission" % approver)
    return ps


def approve_phase(phase_id: str, approver: str, console) -> dict:
    with st.exclusive_lock():
        data, state = cfg.load_phases(), _need_state()
        ph = cfg.phase_def(data, phase_id)
        auth.validate_id(approver)
        ps = _check_actionable(state, ph, phase_id, approver)
        fp = c.path(ps["artifact"])
        if not fp.is_file() or c.sha256_file(fp) != ps["artifact_sha256"]:
            raise c.SdlcError("artifact for %s changed after validation; rerun the phase" % phase_id)
        problems = validators.validate_markdown(ph, fp.read_text(encoding="utf-8"))
        if problems or not ps.get("validation", {}).get("passed"):
            raise c.SdlcError("artifact for %s does not pass validation: %s" % (phase_id, problems or ps.get("validation")))
        if "verify_verdict" in ph.get("checks", []) and ps.get("verdict") != "PASS":
            raise c.SdlcError("the verification verdict is %s, so it cannot be approved; reject it with the reason, "
                              "or reopen implementation to fix the failures" % ps.get("verdict"))
        ev = c.path(ps["artifact"][:-3] + ".evidence.json")
        if ps.get("evidence_sha256") and (not ev.is_file() or c.sha256_file(ev) != ps["evidence_sha256"]):
            raise c.SdlcError("evidence file for %s changed after validation" % phase_id)
        console.show("\n=== %s artifact (%s), submitted by %s ===\n%s" % (phase_id, ps["artifact"], ps["submitted_by"], fp.read_text(encoding="utf-8")))
        console.show("=== validation: %s ===" % ps["validation"])
        _authenticate(console, state, approver, "approve", phase_id)
        _confirm(console, state, "approve %s %s" % (phase_id, ps["artifact_sha256"][:8]), "approval", phase_id, approver)
        ps["approval"] = {"by": approver, "at": c.utcnow(), "artifact_sha256": ps["artifact_sha256"], "channel": "tty+passphrase"}
        ps["status"] = "approved"
        st.save(state, "phase_approved", phase=phase_id, agent=ps.get("agent"), actor="human:%s" % approver,
                artifact=ps["artifact"], artifact_sha256=ps["artifact_sha256"], validation=ps["validation"])
        return {"phase": phase_id, "next": st.next_phase(state)}


def reject_phase(phase_id: str, approver: str, reason: Optional[str], console) -> dict:
    with st.exclusive_lock():
        data, state = cfg.load_phases(), _need_state()
        ph = cfg.phase_def(data, phase_id)
        auth.validate_id(approver)
        reason = _reason(reason)
        ps = _check_actionable(state, ph, phase_id, approver)
        console.show("\n=== %s artifact (%s) ===\n%s" % (phase_id, ps["artifact"], c.path(ps["artifact"]).read_text(encoding="utf-8")))
        _authenticate(console, state, approver, "reject", phase_id)
        _confirm(console, state, "reject %s" % phase_id, "rejection", phase_id, approver)
        ps["rejection"] = {"by": approver, "at": c.utcnow(), "reason": reason, "artifact_sha256": ps["artifact_sha256"]}
        ps["status"] = "rejected"
        st.save(state, "phase_rejected", phase=phase_id, agent=ps.get("agent"), actor="human:%s" % approver,
                artifact=ps["artifact"], reason=reason)
        return {"phase": phase_id}


def reopen_phase(phase_id: str, approver: str, reason: Optional[str], console) -> dict:
    with st.exclusive_lock():
        data, state = cfg.load_phases(), _need_state()
        cfg.phase_def(data, phase_id)
        auth.validate_id(approver)
        reason = _reason(reason)
        if state["phases"][phase_id]["status"] == "pending":
            raise c.SdlcError("%s is pending; there is nothing to reopen" % phase_id)
        affected = [p for p in c.PHASE_ORDER[c.PHASE_ORDER.index(phase_id):]
                    if state["phases"][p]["status"] != "pending"]
        console.show("Reopening %s will reset: %s\nApprovals for these phases and any PR authorization become invalid; "
                     "their artifacts are archived, not deleted." % (phase_id, ", ".join(affected)))
        _authenticate(console, state, approver, "reopen", phase_id)
        _confirm(console, state, "reopen %s" % phase_id, "reopen", phase_id, approver)

        archive = "artifacts/_archive/%s-%s-%s" % (c.utcnow().replace(":", ""), phase_id, c.slug(reason))
        invalidated = []
        for pid in affected:
            ps = state["phases"][pid]
            if ps["status"] == "approved":
                invalidated.append({"phase": pid, "approval": ps["approval"]})
            canonical = workflow.artifact_path(pid)
            for src in (c.path("artifacts", pid), c.path(canonical), c.path(canonical[:-3] + ".evidence.json")):
                if src.exists():
                    c.path(archive, pid).mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(c.path(archive, pid, "attempts" if src.is_dir() else src.name)))
            record = {"reopened_at": c.utcnow(), "by": approver, "reason": reason, "previous_status": ps["status"],
                      "artifact": ps.get("artifact"), "approval": ps.get("approval"), "archived_to": archive}
            state["phases"][pid] = {"status": "pending", "attempt": ps["attempt"], "history": ps["history"] + [record]}
        pr_auth = state["pr_authorization"]
        state["pr_authorization"] = None
        st.save(state, "phase_reopened", phase=phase_id, actor="human:%s" % approver, reason=reason,
                reset_phases=affected, archived_to=archive, invalidated_approvals=invalidated,
                pr_authorization_invalidated=pr_auth)
        return {"phase": phase_id, "reset": affected, "archived_to": archive}


def authorize_pr(repo: str, head: str, base: str, approver: str, console, title: Optional[str] = None) -> dict:
    with st.exclusive_lock():
        config, state = cfg.load_config(), _need_state()
        auth.validate_id(approver)
        missing = [p for p in c.PRE_PR_PHASES if state["phases"][p]["status"] != "approved"]
        if missing:
            raise c.SdlcError("cannot authorize a PR: these phases are not approved: %s" % ", ".join(missing))
        if workflow.verification_error(state):
            raise c.SdlcError("cannot authorize a PR: " + workflow.verification_error(state))
        if state["phases"]["pr"]["status"] in ("submitted", "approved"):
            raise c.SdlcError("the pr phase is already %s; reopen it first" % state["phases"]["pr"]["status"])
        if not re.match(r"^[\w.-]+/[\w.-]+$", repo or ""):
            raise c.SdlcError("--repo must look like OWNER/REPOSITORY")
        if repo.lower() != str(config.get("github_repo", "")).lower():
            raise c.SdlcError("repo %s is not the configured repository (%s)" % (repo, config.get("github_repo") or "unset"))
        if not BRANCH_RE.match(head or "") or ".." in head:
            raise c.SdlcError("--head %r is not a valid branch name" % head)
        if not head.startswith(config["branch_prefix"]):
            raise c.SdlcError("--head must start with %r" % config["branch_prefix"])
        if any(fnmatch.fnmatchcase(head, pat) for pat in config["protected_branches"]) or head == base:
            raise c.SdlcError("--head %r is a protected branch or equals the base branch" % head)
        if base != config["base_branch"]:
            raise c.SdlcError("--base must be the configured base branch %r" % config["base_branch"])
        content = prcontent.build(state, repo, head, base, title)
        console.show("Authorize ONE pull request: %s  %s -> %s\nTitle: %s\nFiles:\n%s\n--- body ---\n%s\n--- content digest %s ---"
                     % (repo, head, base, content["title"],
                        "\n".join("  %s  sha256=%s" % kv for kv in sorted(content["files"].items())),
                        content["body"], content["content_digest"]))
        _authenticate(console, state, approver, "authorize_pr", "pr")
        _confirm(console, state, "authorize-pr %s %s %s" % (repo, head, content["content_digest"][:8]),
                 "pr_authorization", "pr", approver)
        previous = state["pr_authorization"]
        state["pr_authorization"] = dict(content, id=uuid.uuid4().hex[:12], approver=approver, at=c.utcnow(),
                                         approvals_digest=st.approvals_digest(state), status="authorized")
        st.save(state, "pr_authorized", phase="pr", actor="human:%s" % approver, authorization=state["pr_authorization"],
                replaced=previous)
        return state["pr_authorization"]
