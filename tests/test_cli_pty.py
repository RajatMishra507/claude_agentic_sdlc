"""End to end through the real command line, with a pseudo-terminal standing in for the human's terminal.

Human-only commands (init, approve, authorize-pr) read the passphrase and confirmation from the controlling
terminal, so they are driven through a pty. Everything else runs as an ordinary subprocess with no terminal.
"""
import os
import pty
import re
import select
import subprocess
import sys
import time

import pytest

from conftest import AGENT_ENV, HEAD, PASS, REPO
from engine import common as c

ORCH = str(REPO / "orchestrator.py")
CONFIRM = (r"Type exactly '([^']+)'", lambda m: m.group(1))
PASSPHRASE = (r"Passphrase for \w+: ", PASS)


def cli_env(root, **extra):
    env = {k: v for k, v in os.environ.items() if k not in AGENT_ENV}
    env.update(SDLC_ROOT=str(root), **extra)
    return env


def run_plain(args, env):
    return subprocess.run([sys.executable, ORCH] + args, env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, start_new_session=True, timeout=120)


def run_pty(args, env, steps, timeout=90):
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, [sys.executable, ORCH] + args, env)
    transcript, pending, deadline = "", "", time.time() + timeout

    def pump():
        nonlocal transcript, pending
        ready, _, _ = select.select([fd], [], [], 0.5)
        if not ready:
            return True
        try:
            data = os.read(fd, 4096).decode(errors="replace")
        except OSError:
            return False
        if not data:
            return False
        transcript += data
        pending += data
        return True

    for pattern, reply in steps:
        while True:
            match = re.search(pattern, pending)
            if match:
                pending = pending[match.end():]
                os.write(fd, ((reply(match) if callable(reply) else reply) + "\n").encode())
                break
            if time.time() > deadline or not pump():
                os.waitpid(pid, 0)
                raise AssertionError("prompt %r never appeared; saw:\n%s" % (pattern, transcript))
    while pump():
        if time.time() > deadline:
            break
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), transcript


@pytest.fixture
def cli(bare_project):
    env = cli_env(bare_project)
    code, out = run_pty(["init", "--approver", "alice"], env,
                        [(r"New passphrase for alice[^:]*: ", PASS), (r"Repeat passphrase: ", PASS)])
    assert code == 0 and "Registered: ['alice']" in out, out
    return env


def approve_via_terminal(env, phase, approver="alice", steps=None):
    return run_pty(["approve", phase, "--approver", approver], env, [PASSPHRASE, CONFIRM] if steps is None else steps)


def test_complete_pipeline_through_the_real_cli_with_terminal_approvals(cli, bare_project):
    for pid in c.PHASE_ORDER:
        if pid == "pr":
            code, out = run_pty(["authorize-pr", "--repo", "acme/docs", "--head", HEAD, "--base", "main",
                                 "--approver", "alice"], cli, [PASSPHRASE, CONFIRM])
            assert code == 0 and "PR authorized" in out, out
        ran = run_plain(["run", "--phase", pid], cli)
        assert ran.returncode == 0, ran.stdout + ran.stderr
        assert "awaiting human approval" in ran.stdout
        again = run_plain(["run"], cli)
        assert again.returncode == 2 and "awaiting human approval" in again.stderr
        code, out = approve_via_terminal(cli, pid)
        assert code == 0 and "Approved %s" % pid in out, out
    status = run_plain(["status"], cli).stdout
    assert "Pipeline complete: all 8 phases approved." in status
    assert run_plain(["verify-audit"], cli).returncode == 0
    evidence_check = run_plain(["verify-evidence"], cli)
    assert evidence_check.returncode == 0 and "FAIL" not in evidence_check.stdout
    for name in ("requirements", "architecture", "design-review", "planning", "implementation", "review", "verify", "pr"):
        assert (bare_project / "artifacts" / (name + ".md")).is_file()


def test_approval_without_a_controlling_terminal_is_impossible(cli):
    assert run_plain(["run", "--phase", "requirements"], cli).returncode == 0
    attempt = run_plain(["approve", "requirements", "--approver", "alice"], cli)
    assert attempt.returncode == 2 and "no controlling terminal" in attempt.stderr
    assert "submitted" in run_plain(["status"], cli).stdout


def test_approval_is_refused_inside_an_agent_session_even_with_a_terminal(cli):
    run_plain(["run", "--phase", "requirements"], cli)
    code, out = run_pty(["approve", "requirements", "--approver", "alice"], dict(cli, CLAUDECODE="1"), [])
    assert code == 2 and "reserved for humans" in out
    assert "submitted" in run_plain(["status"], cli).stdout


def test_wrong_passphrase_at_the_terminal_does_not_approve(cli):
    run_plain(["run", "--phase", "requirements"], cli)
    code, out = approve_via_terminal(cli, "requirements", steps=[(r"Passphrase for \w+: ", "not the passphrase")])
    assert code == 2 and "authentication failed" in out
    assert "submitted" in run_plain(["status"], cli).stdout


def test_agent_like_and_unregistered_approvers_are_refused_at_the_cli(cli):
    run_plain(["run", "--phase", "requirements"], cli)
    for name, message in (("claude", "agent identity"), ("requirements", "agent identity"), ("mallory", "not registered")):
        code, out = approve_via_terminal(cli, "requirements", approver=name, steps=[])
        assert code == 2 and message in out, (name, out)
    assert "submitted" in run_plain(["status"], cli).stdout


def test_skipping_and_early_actions_are_refused_at_the_cli(cli):
    skipped = run_plain(["run", "--phase", "architecture"], cli)
    assert skipped.returncode == 2 and "the next phase is requirements" in skipped.stderr
    code, out = approve_via_terminal(cli, "requirements", steps=[])
    assert code == 2 and "only a submitted phase" in out
    code, out = run_pty(["authorize-pr", "--repo", "acme/docs", "--head", HEAD, "--base", "main", "--approver", "alice"], cli, [])
    assert code == 2 and "not approved" in out


def test_a_second_human_cannot_be_registered_without_an_existing_approver(cli):
    code, out = run_pty(["init", "--approver", "carol"], cli,
                        [(r"Existing approver id: ", "alice"), (r"Passphrase for alice: ", "wrong wrong wrong")])
    assert code == 2 and "authentication failed" in out
