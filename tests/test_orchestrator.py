import json

import pytest

from conftest import PASS, ScriptedConsole, approve, authorize, complete, reject
from engine import approvals, audit, auth, state as st, workflow
from engine import common as c

SdlcError = c.SdlcError


def status(phase):
    return st.load()["phases"][phase]["status"]


def write_draft(phase, **overrides):
    draft = {"summary": "s", "artifact_markdown": "x"}
    draft.update(overrides)
    p = workflow.draft_path(phase)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(draft))


# ---- phase order ---------------------------------------------------------------

def test_full_pipeline_in_strict_order_with_human_approval_at_every_phase(project):
    seen = []
    for pid in c.PHASE_ORDER:
        if pid == "pr":
            authorize()
        result = workflow.run_phase()
        assert result["ok"] and result["phase"] == pid
        seen.append(pid)
        assert status(pid) == "submitted"
        with pytest.raises(SdlcError, match="awaiting human approval"):
            workflow.run_phase()
        approve(pid)
        assert status(pid) == "approved"
    assert seen == c.PHASE_ORDER
    assert workflow.run_phase()["phase"] is None
    assert audit.verify() > 20


def test_phases_cannot_be_skipped_by_run_start_or_submit(project):
    with pytest.raises(SdlcError, match="the next phase is requirements"):
        workflow.run_phase("architecture")
    with pytest.raises(SdlcError, match="predecessor requirements is not approved"):
        workflow.start_phase("architecture")
    with pytest.raises(SdlcError, match="predecessor requirements is not approved"):
        workflow.submit_phase("architecture", "alice")


def test_next_phase_cannot_start_until_previous_is_approved(project):
    workflow.run_phase()
    assert status("requirements") == "submitted"
    with pytest.raises(SdlcError, match="awaiting human approval"):
        workflow.run_phase()
    with pytest.raises(SdlcError, match="predecessor requirements is not approved"):
        workflow.start_phase("architecture")


def test_unknown_phase_is_rejected(project):
    with pytest.raises(SdlcError, match="unknown phase"):
        workflow.start_phase("deploy")


# ---- artifact validation -------------------------------------------------------

def test_invalid_artifact_cannot_be_submitted_or_approved(project):
    workflow.start_phase("requirements")
    write_draft("requirements")
    result = workflow.submit_phase("requirements", "alice")
    assert not result["ok"]
    assert any("missing required heading" in e for e in result["errors"])
    assert status("requirements") == "in_progress"
    with pytest.raises(SdlcError, match="only a submitted phase"):
        approve("requirements")


def test_submit_requires_in_progress_phase(project):
    with pytest.raises(SdlcError, match="must be in_progress"):
        workflow.submit_phase("requirements", "alice")


def test_fabricated_atlassian_quote_blocks_phase(project, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "bad_quote")
    result = workflow.run_phase()
    assert not result["ok"] and any("no recorded Atlassian response" in e for e in result["errors"])
    assert status("requirements") == "in_progress"
    with pytest.raises(SdlcError, match="blocked"):
        workflow.run_phase()
    monkeypatch.setenv("FAKE_MODE", "ok")
    assert workflow.run_phase(retry=True)["ok"]


def test_manually_forged_tool_log_entries_are_rejected(project, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "forged")
    result = workflow.run_phase()
    assert not result["ok"] and any("signature/chain verification" in e for e in result["errors"])


def test_unauthorized_file_change_blocks_phase(project, monkeypatch):
    complete("requirements")
    monkeypatch.setenv("FAKE_MODE", "rogue")
    result = workflow.run_phase()
    assert not result["ok"] and any("rogue.txt" in e for e in result["errors"])


def test_approval_revalidates_the_stored_artifact(project):
    workflow.run_phase()
    artifact = c.path(st.load()["phases"]["requirements"]["artifact"])
    artifact.write_text(artifact.read_text() + "\nsneaky edit")
    with pytest.raises(SdlcError, match="changed after validation"):
        approve("requirements")


# ---- human approval ------------------------------------------------------------

def test_approval_needs_the_human_passphrase(project):
    workflow.run_phase()
    with pytest.raises(SdlcError, match="authentication failed"):
        approve("requirements", secret="wrong passphrase!")
    assert status("requirements") == "submitted"
    assert audit.read()[-1]["action"] == "authentication_failed"


def test_unregistered_and_agent_like_approvers_are_refused(project):
    workflow.run_phase()
    with pytest.raises(SdlcError, match="not registered"):
        approve("requirements", approver="mallory")
    for name in ("claude", "requirements", "orchestrator", "agent:pr", "bot-ci", "System"):
        with pytest.raises(SdlcError, match="agent identity|invalid"):
            approve("requirements", approver=name)
    assert status("requirements") == "submitted"


def test_approver_id_is_required_and_validated(project):
    workflow.run_phase()
    with pytest.raises(SdlcError, match="invalid"):
        approve("requirements", approver="")


def test_wrong_confirmation_phrase_does_not_approve(project):
    workflow.run_phase()
    with pytest.raises(SdlcError, match="cancelled"):
        approve("requirements", phrase="yes")
    assert status("requirements") == "submitted"
    assert audit.read()[-1]["action"] == "approval_cancelled"


def test_duplicate_and_invalid_approvals_are_refused(project):
    complete("requirements")
    with pytest.raises(SdlcError, match="already approved"):
        approve("requirements")
    with pytest.raises(SdlcError, match="predecessor requirements|not approved|only a submitted"):
        approve("planning")


def test_submitter_cannot_approve_their_own_submission(project):
    workflow.start_phase("requirements")
    write_valid_requirements()
    assert workflow.submit_phase("requirements", "alice")["ok"]
    with pytest.raises(SdlcError, match="own submission"):
        approve("requirements", approver="alice")
    approve("requirements", approver="bob")
    assert status("requirements") == "approved"


def write_valid_requirements():
    from engine import evidence
    attempt = st.load()["phases"]["requirements"]["attempt_id"]
    url = "https://example.atlassian.net/wiki/spaces/X/pages/123"
    evidence.append(c.ROOT, {"attempt_id": attempt, "tool_name": "mcp__atlassian__getConfluencePage", "tool_use_id": "t1",
                             "tool_input": {"url": url}, "text": "Users must log in with SSO before access."})
    md = "".join("## %s\n%s\n" % (h, "Substantive content for this section. " * 4)
                 for h in ["Overview", "Requirements", "Source Register", "Open Questions"]) + "REQ-1 SSO\n"
    write_draft("requirements", artifact_markdown=md, evidence=[
        {"id": "REQ-1", "source_url": url, "source_id": "123", "quote": "Users must log in with SSO"}])


def test_engine_commands_refuse_to_run_inside_an_agent_session(project, monkeypatch):
    for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "SDLC_ACTIVE_PHASE", "SDLC_ACTIVE_AGENT"):
        monkeypatch.setenv(var, "1")
        with pytest.raises(SdlcError, match="reserved for humans"):
            auth.human_console()
        with pytest.raises(SdlcError, match="reserved for humans"):
            auth.forbid_agent_context()
        monkeypatch.delenv(var)


def test_new_approvers_need_an_existing_approver(project):
    console = ScriptedConsole(asks=["alice"], secrets=[PASS, "carol passphrase!", "carol passphrase!"])
    assert approvals.init_pipeline(["carol"], console)["registered"] == ["carol"]
    bad = ScriptedConsole(asks=["alice"], secrets=["wrong one!!!", "dave passphrase!", "dave passphrase!"])
    with pytest.raises(SdlcError, match="authentication failed"):
        approvals.init_pipeline(["dave"], bad)
    assert "dave" not in auth.registry()


# ---- rejection -------------------------------------------------------------------

def test_rejection_blocks_until_corrected_and_resubmitted(project, tmp_path):
    complete("requirements")
    workflow.run_phase()
    reject("architecture", reason="Missing a caching decision")
    ps = st.load()["phases"]["architecture"]
    assert ps["status"] == "rejected" and ps["rejection"]["by"] == "alice"
    with pytest.raises(SdlcError, match="predecessor architecture is not approved"):
        workflow.start_phase("design_review")
    with pytest.raises(SdlcError, match="only a submitted phase"):
        approve("architecture")
    assert workflow.run_phase("architecture")["ok"]
    assert "Missing a caching decision" in (tmp_path / "prompts" / "architecture.txt").read_text()
    assert st.load()["phases"]["architecture"]["attempt"] == 2
    approve("architecture")


def test_rejection_requires_reason_and_human_auth(project):
    workflow.run_phase()
    with pytest.raises(SdlcError, match="reason"):
        reject("requirements", reason="")
    with pytest.raises(SdlcError, match="authentication failed"):
        reject("requirements", secret="not the passphrase")
    with pytest.raises(SdlcError, match="agent identity"):
        reject("requirements", approver="claude")
    assert status("requirements") == "submitted"
