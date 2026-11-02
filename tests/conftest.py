import json
import shutil
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine import approvals, auth, evidence, prcontent, state as st, workflow  # noqa: E402
from engine import common as c  # noqa: E402

SdlcError = c.SdlcError
PASS = "correct horse battery"
HEAD = "sdlc/docs-sync"

# A stand-in for `claude -p --agent <name>`. With FAKE_HOOKS=1 every simulated tool call goes through the real
# hooks/guard.py (PreToolUse, then PostToolUse) exactly as Claude Code would invoke it; otherwise evidence is
# written directly. FAKE_ATTEMPTS lists forbidden actions the "agent" tries first (they must all be denied).
FAKE_CLAUDE = r'''#!__PY__
import json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, "__REPO__")
from engine import evidence

root = Path(os.environ["SDLC_ROOT"])
phase = os.environ["SDLC_ACTIVE_PHASE"]
attempt = os.environ["SDLC_ATTEMPT_ID"]
mode = os.environ.get("FAKE_MODE", "ok")
prompt = sys.stdin.read()
pdir = Path(os.environ["FAKE_PROMPT_DIR"])
pdir.mkdir(exist_ok=True)
(pdir / (phase + ".txt")).write_text(prompt)

data = json.loads((root / "sdlc" / "phases.json").read_text())
ph = next(p for p in data["phases"] if p["id"] == phase)
body = "# " + phase + "\n\n" + "".join(
    "## " + h + "\n" + ("Substantive content for this section. " * 4) + "\n\n" for h in ph["required_headings"])
out = {"summary": "done " + phase}
URL = "https://example.atlassian.net/wiki/spaces/X/pages/123"
PR = "https://github.com/acme/docs/pull/7"
HOOKS = os.environ.get("FAKE_HOOKS") == "1"
attempts = [a for a in os.environ.get("FAKE_ATTEMPTS", "").split(",") if a]
denials, allowed_attempts, counter = [], [], [0]


def log(tool, tool_input, text):
    entry = {"attempt_id": attempt, "tool_name": tool, "tool_use_id": "toolu_" + phase,
             "tool_input": tool_input, "text": text}
    if mode == "forged":
        with open(root / "sdlc" / "tool_log.jsonl", "a") as fh:
            fh.write(json.dumps(entry) + "\n")
    else:
        evidence.append(root, entry)


def hook(kind, event):
    return subprocess.run([sys.executable, "__REPO__/hooks/guard.py", kind], input=json.dumps(event),
                          text=True, capture_output=True)


def call(name, tool_input, text, perform=None, attempt_only=False):
    """One tool call, as Claude Code makes it: PreToolUse hook, the tool itself, PostToolUse hook."""
    if not HOOKS:
        if perform:
            perform()
        if not attempt_only:
            log(name, tool_input, text)
        return True
    counter[0] += 1
    event = {"tool_name": name, "tool_input": tool_input, "tool_use_id": "toolu_%s_%d" % (phase, counter[0])}
    verdict = hook("pre", event)
    if verdict.returncode == 2:
        denials.append({"tool": name, "reason": verdict.stderr.strip()})
        return False
    if attempt_only:
        allowed_attempts.append(name)
    if perform:
        perform()
    event["tool_response"] = {"stdout": text} if name == "Bash" else {"content": [{"type": "text", "text": text}]}
    hook("post", event)
    return True


ident = {"owner": "acme", "repo": "docs"}
TABLE = {
    "force_push": ("Bash", {"command": "git push --force origin main"}),
    "approve_self": ("Bash", {"command": "python3 orchestrator.py approve %s --approver alice" % phase}),
    "write_state": ("Write", {"file_path": str(root / "sdlc" / "state.json"), "content": "{}"}),
    "read_env": ("Read", {"file_path": str(root / ".env")}),
    "early_pr": ("mcp__github__create_pull_request", dict(ident, head="sdlc/x", base="main", title="t", body="b")),
    "merge": ("mcp__github__merge_pull_request", dict(ident, pull_number=7)),
    "push_main": ("mcp__github__push_files", dict(ident, branch="main", files=[{"path": "a", "content": "b"}], message="m")),
    "tampered_pr": ("mcp__github__create_pull_request", dict(ident, head="sdlc/docs-sync", base="main", title="evil", body="x")),
    "delete_branch": ("Bash", {"command": "git branch -D sdlc/docs-sync"}),
}
for key in attempts:
    call(TABLE[key][0], TABLE[key][1], "should never run", attempt_only=True)
call("Read", {"file_path": str(root / "README.md")}, "readme")

if phase == "requirements" and mode == "atlassian_down":
    body += "REQ-1 Users must log in with SSO.\n"
    evidence.append(root, {"attempt_id": attempt, "tool_name": "mcp__atlassian__getConfluencePage", "tool_use_id": "t",
                           "tool_input": {"url": URL}, "failed": True, "text": "401 Unauthorized: authentication required"})
    out["evidence"] = [{"id": "REQ-1", "source_url": URL, "source_id": "123", "quote": "Users must log in with SSO"}]
elif phase == "requirements":
    body += "REQ-1 Users must log in with SSO.\n"
    call("mcp__atlassian__getConfluenceContent", {"cloudId": "c", "pageId": "123", "url": URL},
         "Page 123. " + URL + " Users must log in with SSO before access.")
    quote = "Admins can delete the whole universe" if mode == "bad_quote" else "Users must log in with SSO"
    url = "https://evil.example.com/wiki/spaces/X/pages/123" if mode == "foreign_host" else URL
    out["evidence"] = [{"id": "REQ-1", "source_url": url, "source_id": "123", "quote": quote}]
if phase == "implementation":
    def write_doc():
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / "guide.md").write_text("synced docs")
    call("Write", {"file_path": str(root / "docs" / "guide.md"), "content": "synced docs"}, "written", perform=write_doc)
    out["files_changed"] = ["docs/guide.md"]
if phase == "verify":
    text = {"verify_fail": "1 failed", "pass_but_failed": "2 failed, 1 passed", "no_run": None}.get(mode, "1 passed")
    if text:
        call("Bash", {"command": "pytest -q"}, text)
    else:
        call("Bash", {"command": "git status"}, "clean")
    body += "\nVerdict: " + ("FAIL" if mode == "verify_fail" else "PASS") + ("\nVerdict: FAIL\n" if mode == "ambiguous" else "\n")
if phase == "pr":
    authz = json.loads((root / "sdlc" / "state.json").read_text())["pr_authorization"]
    if mode != "pr_only_tampered":
        call("mcp__github__create_branch", dict(ident, branch=authz["head"], from_branch=authz["base"]), "branch created")
    if mode not in ("pr_missing_push", "pr_only_tampered"):
        files = [{"path": p, "content": (root / p).read_text()} for p in authz["files"]]
        call("mcp__github__push_files", dict(ident, branch=authz["head"], files=files, message="m"), "pushed")
    body_text = "tampered body" if mode in ("pr_wrong_body", "pr_only_tampered") else authz["body"]
    call("mcp__github__create_pull_request", dict(ident, head=authz["head"], base=authz["base"], title=authz["title"],
                                                  body=body_text), "created " + PR)
    out["pr"] = {"url": PR, "branch": "sdlc/other" if mode == "pr_wrong_branch" else authz["head"]}
if mode == "questions":
    out["questions"] = ["Which SSO provider is in scope?"]
if mode == "rogue" and phase == "architecture":
    (root / "rogue.txt").write_text("x")
out["artifact_markdown"] = body
if os.environ.get("FAKE_DENIAL_FILE"):
    Path(os.environ["FAKE_DENIAL_FILE"]).write_text(json.dumps({"denied": denials, "allowed_attempts": allowed_attempts}))
print(json.dumps({"type": "result", "is_error": False, "structured_output": out}))
'''

AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "SDLC_ACTIVE_PHASE", "SDLC_ACTIVE_AGENT", "SDLC_ATTEMPT_ID",
             "FAKE_MODE", "FAKE_HOOKS", "FAKE_ATTEMPTS", "FAKE_DENIAL_FILE")


class ScriptedConsole:
    """Stands in for the human terminal: scripted answers and passphrases."""

    def __init__(self, asks=(), secrets=()):
        self.asks, self.secrets, self.shown = list(asks), list(secrets), []

    def show(self, message):
        self.shown.append(message)

    def ask(self, prompt):
        return self.asks.pop(0)

    def secret(self, prompt):
        return self.secrets.pop(0)


def make_project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / "sdlc").mkdir(parents=True)
    shutil.copy(REPO / "sdlc" / "phases.json", root / "sdlc" / "phases.json")
    (root / "README.md").write_text("project readme")
    (root / "sdlc" / "config.json").write_text(json.dumps({
        "requirements_sources": ["https://example.atlassian.net/wiki/spaces/X/pages/123"],
        "github_repo": "acme/docs", "branch_prefix": "sdlc/", "base_branch": "main",
    }))
    fake = tmp_path / "fake_claude"
    fake.write_text(FAKE_CLAUDE.replace("__PY__", sys.executable).replace("__REPO__", str(REPO)))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SDLC_CLAUDE_BIN", str(fake))
    monkeypatch.setenv("FAKE_PROMPT_DIR", str(tmp_path / "prompts"))
    monkeypatch.setenv("SDLC_KEY_DIR", str(tmp_path / "keys"))
    for key in AGENT_ENV:
        monkeypatch.delenv(key, raising=False)
    c.configure(root)
    return root


@pytest.fixture
def project(tmp_path, monkeypatch):
    """An initialized pipeline with two registered human approvers (alice, bob)."""
    root = make_project(tmp_path, monkeypatch)
    evidence.ensure_key(root)
    st.init()
    auth.register("alice", PASS)
    auth.register("bob", PASS)
    yield root
    c.configure(REPO)


@pytest.fixture
def bare_project(tmp_path, monkeypatch):
    """A configured but uninitialized project, for driving the real CLI end to end."""
    root = make_project(tmp_path, monkeypatch)
    yield root
    c.configure(REPO)


def approve(phase, approver="alice", secret=PASS, phrase=None):
    sha = st.load()["phases"][phase].get("artifact_sha256", "0" * 64)
    return approvals.approve_phase(phase, approver, ScriptedConsole([phrase or "approve %s %s" % (phase, sha[:8])], [secret]))


def reject(phase, reason="Needs more detail", approver="alice", secret=PASS, phrase=None):
    return approvals.reject_phase(phase, approver, reason, ScriptedConsole([phrase or "reject %s" % phase], [secret]))


def reopen(phase, reason="Upstream change", approver="alice", secret=PASS, phrase=None):
    return approvals.reopen_phase(phase, approver, reason, ScriptedConsole([phrase or "reopen %s" % phase], [secret]))


def authorize(repo="acme/docs", head=HEAD, base="main", approver="alice", secret=PASS, phrase=None, title=None):
    if phrase is None:
        try:
            digest = prcontent.build(st.load(), repo, head, base, title)["content_digest"][:8]
        except (SdlcError, KeyError):
            digest = "00000000"
        phrase = "authorize-pr %s %s %s" % (repo, head, digest)
    return approvals.authorize_pr(repo, head, base, approver, ScriptedConsole([phrase], [secret]), title)


def complete(upto):
    """Run and approve phases in order through `upto` (authorizing the PR when needed)."""
    for pid in c.PHASE_ORDER[:c.PHASE_ORDER.index(upto) + 1]:
        if pid == "pr":
            authorize()
        result = workflow.run_phase()
        assert result["ok"], result
        approve(pid)
