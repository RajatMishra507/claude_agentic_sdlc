import json

import pytest

from conftest import HEAD, approve, authorize, complete, reopen
from engine import audit, state as st, workflow
from engine import common as c

SdlcError = c.SdlcError


def phases():
    return st.load()["phases"]


# ---- reopening -------------------------------------------------------------------

def test_reopen_resets_downstream_archives_and_invalidates(project):
    complete("verify")
    authorize()
    assert st.pr_authorization_valid(st.load())
    arch_attempt = phases()["architecture"]["attempt"]

    result = reopen("architecture", reason="Requirement REQ-1 changed")

    assert result["reset"] == c.PHASE_ORDER[1:7]
    state = st.load()
    assert state["phases"]["requirements"]["status"] == "approved"
    for pid in c.PHASE_ORDER[1:7]:
        ps = state["phases"][pid]
        assert ps["status"] == "pending" and "approval" not in ps and "artifact" not in ps
        assert ps["history"][-1]["reason"] == "Requirement REQ-1 changed"
    assert state["phases"]["pr"]["status"] == "pending" and state["phases"]["pr"]["history"] == []
    assert state["phases"]["architecture"]["attempt"] == arch_attempt
    assert state["pr_authorization"] is None
    archive = c.path(result["archived_to"])
    assert (archive / "architecture" / "attempts" / "attempt-1.md").is_file()
    assert (archive / "architecture" / "architecture.md").is_file()
    assert (archive / "implementation").is_dir()
    assert not c.path("artifacts", "architecture").exists() and not c.path("artifacts", "architecture.md").exists()
    assert c.path("artifacts", "requirements.md").is_file()
    entry = audit.read()[-1]
    assert entry["action"] == "phase_reopened" and entry["actor"] == "human:alice"
    assert len(entry["details"]["invalidated_approvals"]) == 6
    assert entry["details"]["pr_authorization_invalidated"]["head"] == HEAD
    with pytest.raises(SdlcError, match="predecessor architecture is not approved"):
        workflow.start_phase("design_review")


def test_reopen_requires_reason_auth_and_something_to_reopen(project):
    complete("requirements")
    with pytest.raises(SdlcError, match="reason"):
        reopen("requirements", reason=" ")
    with pytest.raises(SdlcError, match="authentication failed"):
        reopen("requirements", secret="nope nope nope")
    with pytest.raises(SdlcError, match="agent identity"):
        reopen("requirements", approver="claude")
    with pytest.raises(SdlcError, match="nothing to reopen"):
        reopen("architecture")
    assert phases()["requirements"]["status"] == "approved"


def test_reopened_phase_gets_fresh_evidence_and_old_approvals_cannot_be_replayed(project):
    complete("architecture")
    old_attempt_id = phases()["requirements"]["attempt_id"]
    reopen("requirements")
    assert workflow.run_phase()["ok"]
    assert phases()["requirements"]["attempt_id"] != old_attempt_id
    with pytest.raises(SdlcError, match="predecessor requirements is not approved"):
        workflow.start_phase("architecture")


# ---- PR authorization ------------------------------------------------------------

def test_pr_cannot_be_authorized_before_all_prior_phases_are_approved(project):
    complete("review")
    with pytest.raises(SdlcError, match="not approved: verify"):
        authorize()


@pytest.mark.parametrize("kwargs, message", [
    ({"repo": "evil/repo"}, "not the configured repository"),
    ({"repo": "nonsense"}, "OWNER/REPOSITORY"),
    ({"head": "main"}, "must start with"),
    ({"head": "sdlc/../main"}, "not a valid branch"),
    ({"head": "release/1.0"}, "must start with"),
    ({"base": "develop"}, "configured base branch"),
    ({"approver": "claude"}, "agent identity"),
    ({"approver": "mallory"}, "not registered"),
    ({"secret": "wrong passphrase"}, "authentication failed"),
])
def test_pr_authorization_rejects_unsafe_requests(project, kwargs, message):
    complete("verify")
    with pytest.raises(SdlcError, match=message):
        authorize(**kwargs)
    assert st.load()["pr_authorization"] is None


def test_protected_head_branch_is_refused(project, monkeypatch):
    complete("verify")
    cfg = c.path("sdlc", "config.json")
    data = json.loads(cfg.read_text())
    data["branch_prefix"] = ""
    cfg.write_text(json.dumps(data))
    with pytest.raises(SdlcError, match="protected branch"):
        authorize(head="main")
    with pytest.raises(SdlcError, match="protected branch"):
        authorize(head="release/2.0")


def test_pr_phase_refuses_to_run_without_human_authorization(project):
    complete("verify")
    with pytest.raises(SdlcError, match="PR is not authorized"):
        workflow.run_phase()
    with pytest.raises(SdlcError, match="PR is not authorized"):
        workflow.start_phase("pr")


def test_pr_authorization_is_recorded_and_used_exactly_once(project):
    complete("verify")
    rec = authorize()
    assert rec["status"] == "authorized" and rec["approver"] == "alice"
    entry = audit.read()[-1]
    assert entry["action"] == "pr_authorized" and entry["details"]["authorization"]["head"] == HEAD

    result = workflow.run_phase()
    assert result["ok"]
    state = st.load()
    assert state["pr_authorization"]["status"] == "consumed"
    assert state["pr_authorization"]["pr_url"] == "https://github.com/acme/docs/pull/7"
    submitted = [e for e in audit.read() if e["action"] == "phase_submitted"][-1]
    assert submitted["details"]["pr_creation"]["pr_url"].endswith("/pull/7")
    assert submitted["details"]["mcp_evidence"][0]["tool_name"] == "mcp__github__create_pull_request"
    assert not st.pr_authorization_valid(state)
    with pytest.raises(SdlcError, match="already submitted|already"):
        authorize(head="sdlc/second")


def test_pr_evidence_must_match_the_authorized_branch(project, monkeypatch):
    complete("verify")
    authorize()
    monkeypatch.setenv("FAKE_MODE", "pr_wrong_branch")
    result = workflow.run_phase()
    assert not result["ok"] and any("authorized head" in e for e in result["errors"])


def test_authorization_is_invalidated_when_an_approved_phase_changes(project):
    complete("verify")
    authorize()
    reopen("verify")
    complete_verify_again()
    assert st.load()["pr_authorization"] is None
    with pytest.raises(SdlcError, match="PR is not authorized"):
        workflow.run_phase()


def complete_verify_again():
    assert workflow.run_phase()["ok"]
    approve("verify")


# ---- audit and tamper evidence ---------------------------------------------------

def test_audit_entries_carry_the_required_fields(project):
    complete("requirements")
    submitted = next(e for e in audit.read() if e["action"] == "phase_submitted")
    for key in ("ts", "phase", "agent", "action", "actor", "details", "seq", "hash", "prev_hash", "state_sha256"):
        assert key in submitted
    assert submitted["phase"] == "requirements" and submitted["agent"] == "requirements"
    assert submitted["actor"] == "agent:requirements"
    assert submitted["details"]["artifact"] == "artifacts/requirements.md"
    assert submitted["details"]["validation"]["passed"] is True
    assert submitted["details"]["mcp_evidence"][0]["id"] == "REQ-1"
    approved = next(e for e in audit.read() if e["action"] == "phase_approved")
    assert approved["actor"] == "human:alice" and approved["details"]["artifact_sha256"]


def test_audit_chain_detects_edits(project):
    complete("requirements")
    fp = c.path("sdlc", "audit.jsonl")
    fp.write_text(fp.read_text().replace("phase_started", "phase_approved", 1))
    with pytest.raises(SdlcError, match="audit log broken"):
        audit.verify()


def test_state_edits_outside_the_engine_are_detected(project):
    workflow.run_phase()
    fp = c.path("sdlc", "state.json")
    state = json.loads(fp.read_text())
    state["phases"]["requirements"]["status"] = "approved"
    fp.write_text(json.dumps(state))
    with pytest.raises(SdlcError, match="does not match the audit log"):
        st.load()


def test_truncating_the_audit_log_is_detected(project):
    workflow.run_phase()
    fp = c.path("sdlc", "audit.jsonl")
    lines = fp.read_text().splitlines()
    fp.write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(SdlcError, match="does not match the audit log"):
        st.load()


def test_approved_artifact_tampering_halts_the_pipeline(project):
    complete("requirements")
    c.path(st.load()["phases"]["requirements"]["artifact"]).write_text("rewritten history")
    with pytest.raises(SdlcError, match="modified after approval"):
        workflow.run_phase()
