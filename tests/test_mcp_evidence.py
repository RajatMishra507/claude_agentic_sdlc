import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import PASS, REPO, ScriptedConsole, approve, authorize, complete
from engine import approvals, audit, evidence, prcontent, report, state as st, validators, workflow
from engine import common as c

SdlcError = c.SdlcError
URL = "https://example.atlassian.net/wiki/spaces/X/pages/123"


# ---- Atlassian: requirements evidence -----------------------------------------------

def test_unavailable_or_unauthenticated_atlassian_stops_the_phase(project, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "atlassian_down")
    result = workflow.run_phase()
    assert not result["ok"]
    assert any("unavailable or authentication failed" in e and "401" in e and "no requirements may be invented" in e
               for e in result["errors"])
    assert st.load()["phases"]["requirements"]["status"] == "in_progress"
    assert not c.path("artifacts", "requirements.md").exists()


def test_no_atlassian_calls_at_all_also_stops_the_phase(project):
    workflow.start_phase("requirements")
    draft = {"summary": "s", "artifact_markdown": "".join("## %s\n%s\n" % (h, "text " * 20) for h in
             ["Overview", "Requirements", "Source Register", "Open Questions"]) + "REQ-1 SSO\n",
             "evidence": [{"id": "REQ-1", "source_url": URL, "source_id": "1", "quote": "Users must log in with SSO"}]}
    workflow.draft_path("requirements").write_text(json.dumps(draft))
    result = workflow.submit_phase("requirements", "alice")
    assert not result["ok"] and any("no Atlassian MCP call was made" in e for e in result["errors"])


def test_evidence_must_come_from_a_configured_confluence_or_jira_url(project, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "foreign_host")
    result = workflow.run_phase()
    assert not result["ok"] and any("configured host" in e for e in result["errors"])


def test_typed_evidence_identifiers_are_not_proof_of_a_tool_call(project):
    attempt = workflow.start_phase("requirements") and st.load()["phases"]["requirements"]["attempt_id"]
    evidence.append(c.ROOT, {"attempt_id": attempt, "tool_name": "mcp__atlassian__getConfluenceContent",
                             "tool_use_id": "real", "tool_input": {"pageId": "123"},
                             "text": "Page 123 %s Users must log in with SSO before access." % URL})
    md = "".join("## %s\n%s\n" % (h, "text " * 20) for h in ["Overview", "Requirements", "Source Register", "Open Questions"])
    draft = {"summary": "s", "artifact_markdown": md + "REQ-1 SSO\n", "evidence": [
        {"id": "REQ-1", "source_url": URL, "source_id": "123", "quote": "Users must log in with SSO",
         "tool_use_id": "typed-by-agent", "log_mac": "typed-by-agent"}]}
    workflow.draft_path("requirements").write_text(json.dumps(draft))
    assert workflow.submit_phase("requirements", "alice")["ok"]
    ref = [e for e in audit.read() if e["action"] == "phase_submitted"][-1]["details"]["mcp_evidence"][0]
    assert ref["tool_use_id"] == "real" and ref["log_mac"] != "typed-by-agent"
    assert ref["source_url"] == URL


def test_verify_evidence_cross_checks_artifact_audit_and_signed_log(project):
    complete("requirements")
    assert report.verify_evidence("requirements")[0][1] is True
    log = c.path("sdlc", "tool_log.jsonl")
    log.write_text(log.read_text().replace("Users must log in", "Users may skip login"))
    ok, detail = report.verify_evidence("requirements")[0][1:]
    assert not ok and "signature" in detail


def test_verify_evidence_detects_a_changed_evidence_file(project):
    complete("requirements")
    c.path("artifacts", "requirements.evidence.json").write_text("[]")
    assert not report.verify_evidence("requirements")[0][1]


# ---- Verify: Verdict: PASS ----------------------------------------------------------

def test_only_a_literal_verdict_line_counts():
    assert validators.extract_verdict("## Verdict\nVerdict: PASS\n") == "PASS"
    assert validators.extract_verdict("**Verdict: FAIL**") == "FAIL"
    assert validators.extract_verdict("## Verdict\nPASS\n") is None
    assert validators.extract_verdict("The tests will probably PASS") is None
    assert validators.extract_verdict("Verdict: PASS\nVerdict: FAIL") is None
    assert validators.extract_verdict("Verdict: pass") is None


# ---- GitHub: authorization bound to the PR content -------------------------------------

def test_authorization_binds_title_body_and_file_hashes(project):
    complete("verify")
    rec = authorize(title="docs: sync Confluence story")
    assert rec["title"] == "docs: sync Confluence story"
    assert rec["files"] == st.load()["phases"]["implementation"]["files"] and rec["files"]
    assert "REQ-1" in rec["body"] and "Verdict: PASS" in rec["body"] and "docs/guide.md" in rec["body"]
    assert rec["body_sha256"] and rec["content_digest"]
    assert audit.read()[-1]["details"]["authorization"]["content_digest"] == rec["content_digest"]


def test_the_human_must_confirm_the_exact_content_digest(project):
    complete("verify")
    with pytest.raises(SdlcError, match="cancelled"):
        authorize(phrase="authorize-pr acme/docs sdlc/docs-sync 00000000")
    assert st.load()["pr_authorization"] is None


def test_authorization_is_refused_if_files_changed_after_implementation_was_approved(project):
    complete("verify")
    (c.ROOT / "docs" / "guide.md").write_text("edited after approval")
    with pytest.raises(SdlcError, match="differs from the approved implementation"):
        authorize()


def test_pr_content_changes_when_any_authorized_input_changes(project):
    complete("verify")
    state = st.load()
    base = prcontent.build(state, "acme/docs", "sdlc/a", "main", "t")["content_digest"]
    assert base != prcontent.build(state, "acme/docs", "sdlc/b", "main", "t")["content_digest"]
    assert base != prcontent.build(state, "acme/docs", "sdlc/a", "main", "other")["content_digest"]
    assert base == prcontent.build(state, "acme/docs", "sdlc/a", "main", "t")["content_digest"]


def test_pr_evidence_must_match_authorized_content(project, monkeypatch):
    complete("verify")
    authorize()
    for mode, message in (("pr_wrong_body", "body does not match"), ("pr_missing_push", "was not pushed"),
                          ("pr_wrong_branch", "authorized head")):
        monkeypatch.setenv("FAKE_MODE", mode)
        result = workflow.run_phase(retry=st.load()["phases"]["pr"]["status"] == "in_progress")
        assert not result["ok"] and any(message in e for e in result["errors"]), (mode, result)
    monkeypatch.setenv("FAKE_MODE", "ok")
    assert workflow.run_phase(retry=True)["ok"]


def test_pr_creation_is_audited_with_signed_evidence_and_verifiable(project):
    complete("verify")
    authorize()
    assert workflow.run_phase()["ok"]
    entry = [e for e in audit.read() if e["action"] == "phase_submitted"][-1]
    creation = entry["details"]["pr_creation"]
    assert creation["pr_url"] == "https://github.com/acme/docs/pull/7" and creation["authorization_id"]
    assert entry["details"]["mcp_evidence"][0]["log_mac"]
    assert report.verify_evidence("pr")[0][1] is True
    approve("pr")
    assert audit.verify() > 0


# ---- connection test ----------------------------------------------------------------------

def fake_run(stdout):
    return lambda *a, **k: SimpleNamespace(stdout=stdout, stderr="", returncode=0)


@pytest.mark.parametrize("line, expected", [
    ("✔ Connected", True), ("! Needs authentication", False), ("✘ Failed to connect", False),
    ("⏸ Pending approval (run `claude` to approve)", False), ("⊘ Disabled for this project", False),
])
def test_check_mcp_reports_connected_only_when_the_cli_says_so(monkeypatch, line, expected):
    monkeypatch.setenv("SDLC_CLAUDE_BIN", "/bin/echo")
    out = "Checking MCP server health…\n\natlassian: https://x/mcp (HTTP) - %s\ngithub: https://y/mcp/ (HTTP) - ✔ Connected\n" % line
    results = dict((n, ok) for n, ok, _ in report.check_mcp(fake_run(out)))
    assert results == {"atlassian": expected, "github": True}


def test_check_mcp_never_assumes_connection(monkeypatch):
    monkeypatch.setenv("SDLC_CLAUDE_BIN", "/bin/echo")
    assert not any(ok for _, ok, _ in report.check_mcp(fake_run("")))
    monkeypatch.setenv("SDLC_CLAUDE_BIN", "/nonexistent/claude")

    def boom(*a, **k):
        raise OSError("no such file")
    assert not any(ok for _, ok, _ in report.check_mcp(boom))


# ---- configuration hygiene ----------------------------------------------------------------

def test_mcp_config_has_no_hardcoded_secrets():
    text = (REPO / ".mcp.json").read_text()
    config = json.loads(text)
    assert set(config["mcpServers"]) == {"atlassian", "github"}
    for server in config["mcpServers"].values():
        assert server["type"] == "http"
        for value in [server["url"], *server.get("headers", {}).values()]:
            for secret_like in re.findall(r"(ghp_|github_pat_|xox|Bearer\s+[A-Za-z0-9_\-]{20,}|Basic\s+[A-Za-z0-9+/=]{16,})", value):
                pytest.fail("hardcoded credential in .mcp.json: %s" % secret_like)
    assert "${GITHUB_PERSONAL_ACCESS_TOKEN}" in text


def test_secret_files_are_gitignored():
    ignored = (REPO / ".gitignore").read_text()
    for pattern in (".env", ".env.*", "sdlc/tool_log.jsonl", "sdlc/runs/"):
        assert pattern in ignored


def test_settings_wire_every_guard_hook_when_present():
    text = (REPO / ".claude" / "settings.json").read_text().strip()
    if not text:
        pytest.skip(".claude/settings.json is empty: the guard hooks are NOT active (see README setup)")
    settings = json.loads(text)
    for event, mode in (("PreToolUse", "pre"), ("PostToolUse", "post"), ("PostToolUseFailure", "post-failure")):
        commands = [h["command"] for g in settings["hooks"][event] for h in g["hooks"]]
        assert any('guard.py" %s' % mode in cmd and cmd.split('guard.py" ')[1].split()[0] == mode for cmd in commands), event
    assert any("exit 2" in h["command"] for g in settings["hooks"]["PreToolUse"] for h in g["hooks"])
    deny = settings["permissions"]["deny"]
    assert any("approve" in rule for rule in deny) and any(".env" in rule for rule in deny)
