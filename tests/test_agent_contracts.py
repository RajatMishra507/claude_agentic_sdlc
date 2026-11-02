import json
import re
from pathlib import Path

import pytest

from conftest import approve, authorize, complete, reject
from engine import approvals, state as st, workflow
from engine import common as c

SdlcError = c.SdlcError
REPO = Path(__file__).resolve().parents[1]
AGENTS_DIR, SKILLS_DIR, COMMANDS_DIR = (REPO / ".claude" / d for d in ("agents", "skills", "commands"))
SPECIALISTS = ["requirements", "architecture", "design-review", "planning", "implementation", "review", "verify", "pr"]
HUMAN_ONLY = ("approve", "reject", "reopen", "authorize-pr", "init", "submit", "start")
SECTIONS = ("Role", "Permitted tools", "Input", "Output", "Restrictions")


def frontmatter(path):
    text = path.read_text()
    block = text.split("---")[1]
    data, key = {}, None
    for line in block.strip().splitlines():
        if line.startswith("  - ") and key:
            data[key].append(line[4:].strip())
        elif ":" in line:
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            data[key] = [] if value == "" else value
    return data, text


def tool_set(value):
    return {t.strip() for t in value.split(",")} if isinstance(value, str) else set()


# ---- static definitions ------------------------------------------------------------

def test_exactly_nine_agents_matching_phases_json():
    files = sorted(p.stem for p in AGENTS_DIR.glob("*.md"))
    assert files == sorted(["orchestrator"] + SPECIALISTS)
    phases = json.loads((REPO / "sdlc" / "phases.json").read_text())["phases"]
    assert [p["agent"] for p in phases] == SPECIALISTS
    for name in files:
        assert frontmatter(AGENTS_DIR / (name + ".md"))[0]["name"] == name


@pytest.mark.parametrize("name", ["orchestrator"] + SPECIALISTS)
def test_every_agent_documents_role_tools_input_output_restrictions(name):
    _, text = frontmatter(AGENTS_DIR / (name + ".md"))
    for section in SECTIONS:
        assert re.search(r"^## %s\b" % section, text, re.M), "%s lacks '## %s'" % (name, section)


@pytest.mark.parametrize("name", SPECIALISTS)
def test_every_specialist_documents_its_handoff(name):
    _, text = frontmatter(AGENTS_DIR / (name + ".md"))
    handoff = re.search(r"^## Handoff\n(.*?)(?=^## )", text, re.M | re.S)
    assert handoff, "%s lacks '## Handoff'" % name
    for label in ("Receives:", "Produces:", "Next:"):
        assert label in handoff.group(1), "%s handoff lacks '%s'" % (name, label)


@pytest.mark.parametrize("name", SPECIALISTS)
def test_specialist_tools_never_exceed_phases_json(name):
    data = json.loads((REPO / "sdlc" / "phases.json").read_text())
    ph = next(p for p in data["phases"] if p["agent"] == name)
    fm, _ = frontmatter(AGENTS_DIR / (name + ".md"))
    allowed = {re.sub(r"\(.*\)$", "", t) for t in data["common_tools"] + ph["tools"]}
    declared = tool_set(fm.get("tools"))
    assert "Agent" not in declared
    if declared:
        assert declared <= allowed, "%s declares tools beyond its phase: %s" % (name, declared - allowed)


def test_only_implementation_may_write_files():
    for name in ["orchestrator"] + SPECIALISTS:
        fm, _ = frontmatter(AGENTS_DIR / (name + ".md"))
        can_write = bool(tool_set(fm.get("tools")) & {"Edit", "Write"})
        if name == "implementation":
            assert can_write
        else:
            assert not can_write
            if "tools" not in fm:
                assert {"Edit", "Write"} <= tool_set(fm["disallowedTools"])


def test_mcp_servers_are_isolated_to_their_agents():
    for name in ["orchestrator"] + SPECIALISTS:
        disallowed = tool_set(frontmatter(AGENTS_DIR / (name + ".md"))[0].get("disallowedTools"))
        assert ("mcp__atlassian__*" in disallowed) == (name != "requirements")
        assert ("mcp__github__*" in disallowed) == (name != "pr")


def test_orchestrator_is_a_coordinator_that_cannot_write_or_approve():
    fm, text = frontmatter(AGENTS_DIR / "orchestrator.md")
    assert not tool_set(fm["tools"]) & {"Edit", "Write", "Agent"}
    for word in ("approve", "reject", "reopen", "authorize-pr"):
        assert word in text
    assert re.search(r"Never run `init`.*`approve`.*`authorize-pr`", text)


@pytest.mark.parametrize("name", SPECIALISTS)
def test_agents_name_their_artifact_and_forbid_self_approval(name):
    _, text = frontmatter(AGENTS_DIR / (name + ".md"))
    assert "artifacts/%s.md" % name in text
    assert "do not approve anything" in text.lower() or "never approve anything" in text.lower() \
        or "never approves" in text.lower()


@pytest.mark.parametrize("name", SPECIALISTS)
def test_each_specialist_has_its_own_background_skill(name):
    fm, _ = frontmatter(AGENTS_DIR / (name + ".md"))
    assert fm["skills"] == [name + "-playbook"]
    skill, text = frontmatter(SKILLS_DIR / (name + "-playbook") / "SKILL.md")
    assert skill["name"] == name + "-playbook" and skill["user-invocable"] == "false"
    assert not (SKILLS_DIR / name).exists(), "a skill named like the command would shadow /%s" % name
    for heading in ("Procedure", "Artifact skeleton", "Quality bar"):
        assert heading in text


@pytest.mark.parametrize("name", ["orchestrator"] + SPECIALISTS)
def test_commands_delegate_to_the_engine_and_hold_no_human_only_commands(name):
    fm, text = frontmatter(COMMANDS_DIR / (name + ".md"))
    assert fm["disable-model-invocation"] == "true"
    assert len(text.splitlines()) < 30
    for sub in HUMAN_ONLY:
        assert "Bash(python3 orchestrator.py %s" % sub not in fm["allowed-tools"]
    if name != "orchestrator":
        pid = next(p for p in c.PHASE_ORDER if c.AGENTS[p] == name)
        assert "run --phase %s" % pid in fm["allowed-tools"]
        assert "artifacts/%s.md" % name in text


# ---- engine behaviour behind the agent contracts --------------------------------------

def test_every_phase_artifact_is_saved_at_its_canonical_path(project):
    complete("pr")
    for name in SPECIALISTS:
        canonical = c.path("artifacts", name + ".md")
        phase = next(p for p in c.PHASE_ORDER if c.AGENTS[p] == name)
        attempt = c.path("artifacts", phase, "attempt-1.md")
        assert canonical.is_file() and canonical.read_text() == attempt.read_text()
        assert st.load()["phases"][phase]["artifact"] == "artifacts/%s.md" % name
    assert c.path("artifacts", "requirements.evidence.json").is_file()
    assert c.path("artifacts", "pr.evidence.json").is_file()


def test_clarifying_questions_are_returned_to_the_human(project, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "questions")
    result = workflow.run_phase()
    assert result["ok"] and result["questions"] == ["Which SSO provider is in scope?"]
    assert st.load()["phases"]["requirements"]["questions"] == result["questions"]


def test_the_orchestration_prompt_hands_upstream_artifacts_to_the_specialist(project, tmp_path):
    complete("architecture")
    workflow.run_phase()
    prompt = (tmp_path / "prompts" / "design_review.txt").read_text()
    assert "APPROVED INPUT: requirements" in prompt and "APPROVED INPUT: architecture" in prompt
    assert "list each" in prompt and "question" in prompt


@pytest.mark.parametrize("mode, message", [
    ("pass_but_failed", "contradicts the recorded output"),
    ("no_run", "requires a recorded run of 'pytest'"),
    ("ambiguous", "exactly one line"),
])
def test_a_pass_verdict_must_be_backed_by_real_passing_tests(project, monkeypatch, mode, message):
    complete("review")
    monkeypatch.setenv("FAKE_MODE", mode)
    result = workflow.run_phase()
    assert not result["ok"] and any(message in e for e in result["errors"])
    assert st.load()["phases"]["verify"]["status"] == "in_progress"


def test_failures_are_reported_honestly_and_can_never_be_approved(project, monkeypatch):
    complete("review")
    monkeypatch.setenv("FAKE_MODE", "verify_fail")
    assert workflow.run_phase()["ok"]
    assert st.load()["phases"]["verify"]["verdict"] == "FAIL"
    with pytest.raises(SdlcError, match="verdict is FAIL"):
        approve("verify")
    reject("verify", reason="Tests fail; fix implementation")
    monkeypatch.setenv("FAKE_MODE", "ok")
    assert workflow.run_phase()["ok"]
    approve("verify")
    assert st.load()["phases"]["verify"]["verdict"] == "PASS"


def test_pr_requires_passing_verification_evidence(project):
    complete("verify")
    state = st.load()
    state["phases"]["verify"]["verdict"] = "FAIL"
    st.save(state, "test_tamper_setup")
    with pytest.raises(SdlcError, match="verification has not passed"):
        authorize()
    with pytest.raises(SdlcError, match="verification has not passed"):
        workflow.run_phase()


def test_specialists_cannot_be_started_outside_the_engine(project, monkeypatch):
    """Phase mode only exists inside engine runs; elsewhere the MCP tools and state are denied."""
    import subprocess, sys, os
    guard = REPO / "hooks" / "guard.py"
    env = {k: v for k, v in os.environ.items() if not k.startswith("SDLC_ACTIVE") and k != "SDLC_ATTEMPT_ID"}
    env["SDLC_ROOT"] = str(project)
    for tool in ("mcp__atlassian__getConfluencePage", "mcp__github__create_pull_request"):
        r = subprocess.run([sys.executable, str(guard), "pre"], input=json.dumps({"tool_name": tool, "tool_input": {}}),
                           text=True, capture_output=True, env=env)
        assert r.returncode == 2
