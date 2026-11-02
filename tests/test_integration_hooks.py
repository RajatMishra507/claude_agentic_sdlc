"""Integration: engine + specialist subprocess + the real guard hooks (PreToolUse/PostToolUse) working together.

The specialist is a stand-in for `claude -p`, but every tool call it makes goes through hooks/guard.py as a
subprocess, exactly as Claude Code invokes it. No MCP server is contacted.
"""
import json

import pytest

from conftest import approve, authorize, complete
from engine import audit, evidence, report, state as st, workflow
from engine import common as c

SdlcError = c.SdlcError
ALL_ATTEMPTS = "force_push,approve_self,write_state,read_env,early_pr,merge,push_main,tampered_pr,delete_branch"


@pytest.fixture
def hooked(monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_HOOKS", "1")
    path = tmp_path / "denials.json"
    monkeypatch.setenv("FAKE_DENIAL_FILE", str(path))
    return path


def report_of(path):
    return json.loads(path.read_text())


def all_logged_calls():
    out = []
    for pid in c.PHASE_ORDER:
        attempt = st.load()["phases"][pid].get("attempt_id")
        if attempt:
            entries, problems = evidence.read_attempt(c.ROOT, attempt)
            assert not problems, (pid, problems)
            out += entries
    return out


def test_full_pipeline_runs_through_the_real_hooks(project, hooked):
    complete("pr")
    state = st.load()
    assert all(state["phases"][p]["status"] == "approved" for p in c.PHASE_ORDER)
    assert state["pr_authorization"]["status"] == "consumed"
    names = {e["tool_name"] for e in all_logged_calls()}
    assert {"mcp__atlassian__getConfluenceContent", "Write", "Bash", "mcp__github__create_branch",
            "mcp__github__push_files", "mcp__github__create_pull_request"} <= names
    assert {e["phase"] for e in all_logged_calls()} == set(c.PHASE_ORDER)
    assert all(ok for _, ok, _ in report.verify_evidence())
    assert audit.verify() > 20


def test_every_forbidden_action_is_denied_in_every_phase_and_leaves_no_trace(project, hooked, monkeypatch):
    monkeypatch.setenv("FAKE_ATTEMPTS", ALL_ATTEMPTS)
    for pid in c.PHASE_ORDER:
        if pid == "pr":
            authorize()
        result = workflow.run_phase()
        assert result["ok"], (pid, result)
        outcome = report_of(hooked)
        assert outcome["allowed_attempts"] == [], "%s: a forbidden action was allowed: %s" % (pid, outcome)
        assert len(outcome["denied"]) == len(ALL_ATTEMPTS.split(",")), (pid, outcome["denied"])
        approve(pid)
    assert all("should never run" not in e["text"] for e in all_logged_calls())
    assert st.load()["pr_authorization"]["status"] == "consumed"
    assert audit.verify() > 0


def test_a_blocked_unauthorized_pr_cannot_be_passed_off_with_a_typed_url(project, hooked, monkeypatch):
    complete("verify")
    authorize()
    monkeypatch.setenv("FAKE_MODE", "pr_only_tampered")
    result = workflow.run_phase()
    outcome = report_of(hooked)
    assert any(d["tool"] == "mcp__github__create_pull_request" for d in outcome["denied"])
    assert not result["ok"]
    assert any("no recorded GitHub MCP pull-request call returned this URL" in e for e in result["errors"])
    assert st.load()["pr_authorization"]["status"] == "authorized"
    assert st.load()["phases"]["pr"]["status"] == "in_progress"


def test_failed_verification_blocks_pr_creation_end_to_end(project, hooked, monkeypatch):
    complete("review")
    monkeypatch.setenv("FAKE_MODE", "verify_fail")
    assert workflow.run_phase()["ok"]
    with pytest.raises(SdlcError, match="verdict is FAIL"):
        approve("verify")
    with pytest.raises(SdlcError, match="not approved: verify"):
        authorize()
    with pytest.raises(SdlcError, match="predecessor verify is not approved"):
        workflow.start_phase("pr")
    assert st.load()["pr_authorization"] is None


def test_reopening_an_early_phase_invalidates_everything_downstream_end_to_end(project, hooked):
    from conftest import reopen
    complete("verify")
    authorize()
    reopen("design_review", reason="Security finding changes the design")
    state = st.load()
    assert [state["phases"][p]["status"] for p in c.PHASE_ORDER] == ["approved", "approved"] + ["pending"] * 6
    assert state["pr_authorization"] is None
    with pytest.raises(SdlcError, match="predecessor design_review is not approved"):
        workflow.start_phase("planning")
    with pytest.raises(SdlcError, match="not approved: design_review"):
        authorize()


def test_each_phase_is_delegated_to_its_own_agent_with_all_approved_upstream_artifacts(project, tmp_path):
    complete("pr")
    for idx, pid in enumerate(c.PHASE_ORDER):
        prompt = (tmp_path / "prompts" / (pid + ".txt")).read_text()
        assert prompt.startswith("You are %s, executing SDLC phase %d of 8" % (c.AGENTS[pid], idx + 1))
        for earlier in c.PHASE_ORDER[:idx]:
            digest = st.load()["phases"][earlier]["approval"]["artifact_sha256"]
            assert "APPROVED INPUT: %s (sha256 %s)" % (earlier, digest) in prompt
        for later in c.PHASE_ORDER[idx:]:
            assert "APPROVED INPUT: %s" % later not in prompt
    pr_prompt = (tmp_path / "prompts" / "pr.txt").read_text()
    authz = st.load()["pr_authorization"]
    assert authz["title"] in pr_prompt and authz["body_sha256"] and "docs/guide.md" in pr_prompt


def test_artifacts_are_created_validated_and_hash_bound_at_each_handoff(project):
    for pid in c.PHASE_ORDER:
        if pid == "pr":
            authorize()
        assert workflow.run_phase()["ok"]
        ps = st.load()["phases"][pid]
        artifact = c.path(ps["artifact"])
        assert ps["status"] == "submitted" and artifact.is_file() and ps["validation"]["passed"]
        assert ps["artifact_sha256"] == c.sha256_file(artifact)
        approve(pid)
