#!/usr/bin/env python3
"""Claude Code hook: tool-level enforcement for the SDLC pipeline.

  guard.py pre   PreToolUse: deny (exit 2) anything outside the contract. Any
                 internal error also denies (fail closed).
  guard.py post  PostToolUse: append a signed tool-call record used as evidence.
  guard.py post-failure  PostToolUseFailure: record failed calls (e.g. MCP unavailable, auth errors).

Phase mode is entered only when the orchestrator launches an agent
(SDLC_ACTIVE_PHASE set). Other sessions get a restricted interactive mode.
The guard is one layer: approvals are independently protected inside the engine
(registered approver + passphrase on a human terminal).
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("SDLC_ROOT") or REPO).resolve()
sys.path.insert(0, str(REPO))

PHASE = os.environ.get("SDLC_ACTIVE_PHASE", "")
AGENT = os.environ.get("SDLC_ACTIVE_AGENT", "")
ATTEMPT = os.environ.get("SDLC_ATTEMPT_ID", "")

RUNTIME_PROTECTED = ["sdlc/state.json", "sdlc/audit.jsonl", "sdlc/tool_log.jsonl", "sdlc/.lock", "sdlc/runs", "artifacts"]
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
PHASE_ORDER = ["requirements", "architecture", "design_review", "planning",
               "implementation", "review", "verify", "pr"]
AGENT_SAFE_COMMANDS = {"status", "describe", "run", "doctor", "verify-audit", "verify-evidence", "check-mcp"}
DEFAULT_PROTECTED_BRANCHES = ["main", "master", "develop", "release/*"]

SHELL_META = re.compile(r"[;&|`<>\n\r]|\$\(")
GITHUB_FORBIDDEN = re.compile(r"merge|delete|fork|transfer|archive|protection|force", re.I)
GITHUB_WRITE = re.compile(r"^(create|push|update|add|edit|write|assign|request)", re.I)
ATLASSIAN_WRITE = re.compile(r"^(create|edit|update|delete|add|transition|assign|link|remove)", re.I)
APPROVAL_WORDS = re.compile(r"orchestrator.*\b(approve|reject|reopen|authorize-pr)\b", re.I)
ENGINE_INTERNALS = re.compile(r"\bengine\b.*\b(approvals|state|evidence|auth)\b|approve_phase|reject_phase|reopen_phase"
                              r"|authorize_pr|init_pipeline|submit_phase|evidence\.append", re.I)
RUNTIME_MENTION = re.compile(r"(sdlc/(state\.json|audit\.jsonl|tool_log\.jsonl|runs)|(^|[\s/])artifacts(/|\s|$))")
MUTATING_CMD = re.compile(r">|\b(rm|mv|cp|tee|truncate|dd|ln|chmod|python3?|perl|ruby|node|sed\s+-i)\b")
ENV_FILE = re.compile(r"(^|[\s/='\"])\.env(?!\.example)(\.[\w-]+)?($|[\s'\";|&])")
SEPARATORS = {";", "&&", "||", "|", "&", "\n"}
DANGEROUS_SHELL = [
    (re.compile(r"(^|[\s;&|])sudo\b"), "sudo is forbidden"),
    (re.compile(r"\brm\s+(-\w+\s+)*-\w*[rR]\w*\s+(-\w+\s+)*(/|~|\$HOME|\.\.?|\*)(\s|$)"), "recursive removal of broad paths is forbidden"),
    (re.compile(r"\b(curl|wget)\b[^|;&]*\|\s*(ba|z|da)?sh\b"), "piping downloads into a shell is forbidden"),
    (re.compile(r"\b(mkfs|fdisk|shutdown|reboot|halt)\b"), "system-level commands are forbidden"),
    (re.compile(r"\bdd\b[^|;&]*\bof=/dev/"), "writing to devices is forbidden"),
    (re.compile(r"\bchmod\s+(-\w+\s+)*[0-7]*7[0-7]{0,2}\s+/"), "recursive/permissive chmod on system paths is forbidden"),
    (re.compile(r":\(\)\s*\{"), "fork bombs are forbidden"),
    (re.compile(r"\b(eval|exec)\s+.*\$\(?(curl|wget)"), "executing downloaded code is forbidden"),
]
GITHUB_WRITES = {"create_branch", "create_or_update_file", "push_files", "create_pull_request"}
GITHUB_READ = re.compile(r"^(get_|list_)|_read$", re.I)


def deny(message: str) -> None:
    sys.stderr.write("SDLC guard: %s\n" % message)
    sys.exit(2)


def load_json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def rel_path(raw: str):
    if not raw:
        return None
    full = os.path.realpath(raw if os.path.isabs(raw) else str(ROOT / raw))
    try:
        return Path(full).relative_to(ROOT).as_posix()
    except ValueError:
        return None


def under(rel: str, prefix: str) -> bool:
    prefix = prefix.rstrip("/")
    return rel == prefix or rel.startswith(prefix + "/")


def secret_dir() -> str:
    from engine import evidence
    return os.path.realpath(str(evidence.secret_dir()))


def protected_branches() -> list:
    try:
        return load_json("sdlc/config.json").get("protected_branches") or DEFAULT_PROTECTED_BRANCHES
    except (OSError, ValueError):
        return DEFAULT_PROTECTED_BRANCHES


def is_protected(branch: str) -> bool:
    name = re.sub(r"^(refs/heads/|origin/)", "", str(branch))
    return any(fnmatch.fnmatchcase(name, pat) for pat in protected_branches())


def rule_matches(rule: str, tool: str, tool_input: dict) -> bool:
    m = re.match(r"^([^()]+)(?:\((.*)\))?$", rule)
    if not m:
        return False
    name, spec = m.group(1), m.group(2)
    if name.startswith("mcp__"):
        return spec is None and fnmatch.fnmatchcase(tool, name)
    if tool != name:
        return False
    if spec is None:
        return True
    return tool == "Bash" and fnmatch.fnmatchcase(str(tool_input.get("command", "")).strip(), spec)


def tokenize(cmd: str) -> list:
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return cmd.split()


def current_branch() -> str:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def git_invocations(tokens: list):
    """Yield (subcommand, args) for each git command in a tokenized shell line."""
    i = 0
    while i < len(tokens):
        if os.path.basename(tokens[i]) == "git":
            j = i + 1
            while j < len(tokens) and tokens[j].startswith("-"):
                j += 2 if tokens[j] in ("-C", "-c") else 1
            sub = tokens[j] if j < len(tokens) else ""
            k = j + 1
            args = []
            while k < len(tokens) and tokens[k] not in SEPARATORS:
                args.append(tokens[k])
                k += 1
            yield sub, args
            i = k
        else:
            i += 1


def check_git(sub: str, args: list) -> None:
    flags = {a for a in args if a.startswith("-")}
    if sub == "push":
        if flags & {"-f", "--force", "--mirror", "--delete", "-d", "--prune", "--all", "--tags"} or any(
                a.startswith("--force") for a in args) or any(a.startswith("+") for a in args if not a.startswith("-")):
            deny("force pushes and destructive pushes are forbidden")
        positional = [a for a in args if not a.startswith("-")]
        refspecs = positional[1:]
        if any(r.startswith(":") for r in refspecs):
            deny("deleting remote refs is forbidden")
        targets = [r.split(":")[-1] for r in refspecs] or ["HEAD"]
        for target in targets:
            branch = current_branch() if target == "HEAD" else target
            if not branch or is_protected(branch):
                deny("pushing to a protected (or unverifiable) branch is forbidden: %r" % (branch or "unknown"))
    elif sub == "reset" and "--hard" in flags:
        deny("git reset --hard is forbidden")
    elif sub == "clean" and any(f.startswith("-") and not f.startswith("--") and "f" in f for f in flags) or (
            sub == "clean" and "--force" in flags):
        deny("git clean -f is forbidden")
    elif sub in ("checkout", "switch") and (flags & {"-f", "--force", "--discard-changes"} or "--" in args or "." in args):
        deny("discarding working-tree changes with git %s is forbidden" % sub)
    elif sub in ("restore", "rebase", "filter-branch", "filter-repo", "replace"):
        deny("git %s is forbidden" % sub)
    elif sub == "branch" and flags & {"-D", "-d", "--delete", "-f", "--force", "-M"}:
        deny("deleting or force-moving branches is forbidden")
    elif sub == "tag" and flags & {"-d", "--delete", "-f", "--force"}:
        deny("deleting or moving tags is forbidden")
    elif sub == "update-ref" and "-d" in flags:
        deny("deleting refs is forbidden")
    elif sub == "reflog" and ({"expire", "delete"} & set(args)):
        deny("rewriting the reflog is forbidden")
    elif sub == "gc" and any(a.startswith("--prune") for a in args):
        deny("git gc --prune is forbidden")
    elif sub == "stash" and ({"drop", "clear"} & set(args)):
        deny("dropping stashes is forbidden")
    elif PHASE and sub in ("commit", "merge", "cherry-pick", "revert", "am", "apply") and is_protected(current_branch() or "main"):
        deny("agents may not write to a protected branch (current branch is protected or unknown)")


def check_bash(cmd: str) -> None:
    for pattern, message in DANGEROUS_SHELL:
        if pattern.search(cmd):
            deny(message)
    if ENV_FILE.search(cmd):
        deny("access to .env files is not allowed")
    sd = secret_dir()
    if sd in cmd or "sdlc-engine" in cmd or "SDLC_KEY_DIR" in cmd:
        deny("the approver/evidence secret store is off limits")
    tokens = tokenize(cmd)
    for i, tok in enumerate(tokens):
        if os.path.basename(tok) in ("orchestrator.py", "orchestrator"):
            sub = next((t for t in tokens[i + 1:] if not t.startswith("-")), "")
            if sub not in AGENT_SAFE_COMMANDS:
                deny("orchestrator.py %s is reserved for humans in their own terminal" % (sub or "<none>"))
    if APPROVAL_WORDS.search(cmd):
        deny("approving, rejecting, reopening, authorizing or submitting is reserved for humans")
    if ENGINE_INTERNALS.search(cmd) and MUTATING_CMD.search(cmd):
        deny("shell commands may not call the engine internals")
    if RUNTIME_MENTION.search(cmd) and MUTATING_CMD.search(cmd):
        deny("shell commands may not modify orchestrator runtime state")
    for sub, args in git_invocations(tokens):
        check_git(sub, args)


def check_common(tool: str, tool_input: dict) -> None:
    sd = secret_dir()
    for key in ("file_path", "path", "notebook_path"):
        raw = str(tool_input.get(key, "") or "")
        if raw and os.path.basename(raw).lower().startswith(".env") and not raw.lower().endswith(".example"):
            deny("access to .env files is not allowed")
        if raw:
            full = os.path.realpath(raw if os.path.isabs(raw) else str(ROOT / raw))
            if full == sd or full.startswith(sd + os.sep):
                deny("the approver/evidence secret store is off limits")
    if tool in WRITE_TOOLS:
        rel = rel_path(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""))
        if rel is not None and any(under(rel, p) for p in RUNTIME_PROTECTED):
            deny("%s is orchestrator-owned runtime state" % rel)
    if tool == "Bash":
        check_bash(str(tool_input.get("command", "")))


def check_interactive(tool: str) -> None:
    if tool.startswith("mcp__atlassian__") or tool.startswith("mcp__github__"):
        deny("Atlassian/GitHub MCP tools may only run inside an orchestrated phase (python3 orchestrator.py run)")


def sha(text) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def check_github(tool: str, tool_input: dict, state: dict, phase: str) -> None:
    """GitHub MCP is usable only for the human-authorized PR: exact repo, branches, files, title and body."""
    from engine import state as st
    name = tool.split("__", 2)[2] if tool.count("__") >= 2 else tool
    if GITHUB_FORBIDDEN.search(name):
        deny("GitHub tool %s is forbidden" % name)
    for key in ("branch", "head", "ref", "target_branch"):
        if key in tool_input and is_protected(tool_input[key]):
            deny("%s %r is a protected branch" % (key, tool_input[key]))
    if phase != "pr":
        deny("GitHub tools are only allowed in the pr phase")
    if not st.pr_authorization_valid(state):
        deny("no valid human PR authorization (a human must run 'orchestrator.py authorize-pr'), or it was already used")
    authz = state["pr_authorization"]
    if name != "get_me":
        if ("%s/%s" % (tool_input.get("owner"), tool_input.get("repo"))).lower() != authz["repo"].lower():
            deny("owner/repo must be given and equal the authorized repository %s" % authz["repo"])
    if name not in GITHUB_WRITES:
        if not GITHUB_READ.search(name):
            deny("GitHub tool %s is not permitted (only reads and create_branch/create_or_update_file/push_files/"
                 "create_pull_request are)" % name)
        return
    files = authz["files"]
    if name == "create_branch":
        if tool_input.get("branch") != authz["head"] or tool_input.get("from_branch") != authz["base"]:
            deny("create_branch must create the authorized head %r from the authorized base %r" % (authz["head"], authz["base"]))
    elif name == "create_or_update_file":
        path = tool_input.get("path")
        if tool_input.get("branch") != authz["head"] or path not in files or sha(tool_input.get("content", "")) != files[path]:
            deny("file write does not match the authorized branch, path and content")
    elif name == "push_files":
        pushed = tool_input.get("files") or []
        if tool_input.get("branch") != authz["head"] or not pushed or any(
                f.get("path") not in files or sha(f.get("content", "")) != files[f.get("path")] for f in pushed):
            deny("push does not match the authorized branch, paths and content")
    elif name == "create_pull_request":
        if (tool_input.get("head"), tool_input.get("base"), tool_input.get("title"), tool_input.get("body")) != \
                (authz["head"], authz["base"], authz["title"], authz["body"]):
            deny("pull request head, base, title and body must match the human authorization exactly")


def check_phase(tool: str, tool_input: dict) -> None:
    data = load_json("sdlc/phases.json")
    phases = {p["id"]: p for p in data["phases"]}
    if PHASE not in phases:
        deny("unknown active phase %r" % PHASE)
    ph = phases[PHASE]
    if AGENT != ph["agent"]:
        deny("agent %r is not the owner of phase %s" % (AGENT, PHASE))
    state = load_json("sdlc/state.json")
    idx = PHASE_ORDER.index(PHASE)
    if state["phases"][PHASE]["status"] != "in_progress" or \
            any(state["phases"][p]["status"] != "approved" for p in PHASE_ORDER[:idx]):
        deny("phase %s is not in a runnable state" % PHASE)
    if state["phases"][PHASE].get("attempt_id") != ATTEMPT:
        deny("attempt id does not match the phase's current attempt")

    rules = list(data["common_tools"]) + list(ph.get("tools", []))
    if not any(rule_matches(r, tool, tool_input) for r in rules):
        deny("tool %s is not permitted for phase %s" % (tool, PHASE))
    if tool == "Bash" and SHELL_META.search(str(tool_input.get("command", ""))):
        deny("shell metacharacters are not allowed in phase commands")
    if tool in WRITE_TOOLS:
        rel = rel_path(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""))
        if rel is None or not any(under(rel, p) for p in ph.get("write_paths", [])):
            deny("writes are limited to %s" % (ph.get("write_paths") or "nothing in this phase"))
    if tool.startswith("mcp__github__"):
        check_github(tool, tool_input, state, PHASE)
    elif tool.startswith("mcp__atlassian__"):
        if PHASE != "requirements":
            deny("Atlassian MCP is reserved for the requirements phase")
        if ATLASSIAN_WRITE.search(tool.split("__", 2)[2]):
            deny("Atlassian MCP is read-only")
    elif tool.startswith("mcp__"):
        deny("MCP server not part of the pipeline: %s" % tool)


def pre(event: dict) -> None:
    tool = str(event.get("tool_name", ""))
    tool_input = event.get("tool_input") or {}
    check_common(tool, tool_input)
    if PHASE:
        check_phase(tool, tool_input)
    else:
        check_interactive(tool)


def string_leaves(obj, out: list) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            string_leaves(value, out)
    elif isinstance(obj, list):
        for value in obj:
            string_leaves(value, out)


def response_text(resp) -> str:
    leaves = []
    if isinstance(resp, dict) and isinstance(resp.get("content"), list):
        string_leaves([c.get("text", "") for c in resp["content"] if isinstance(c, dict)], leaves)
    elif isinstance(resp, dict) and ("stdout" in resp or "stderr" in resp):
        leaves = [str(resp.get("stdout", "")), str(resp.get("stderr", ""))]
    else:
        string_leaves(resp, leaves)
    text = "\n".join(leaves)
    if text.strip()[:1] in ("{", "["):
        try:
            inner = []
            string_leaves(json.loads(text.strip()), inner)
            text = "\n".join(inner)
        except ValueError:
            pass
    return text


def post(event: dict, failed: bool = False) -> None:
    if not PHASE:
        return
    from engine import evidence
    if failed:
        text = str(event.get("error") or event.get("tool_response") or "tool call failed")[:4000]
    else:
        text = response_text(event.get("tool_response"))[:200000]
    evidence.append(ROOT, {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "attempt_id": ATTEMPT, "phase": PHASE, "agent": AGENT,
        "tool_name": event.get("tool_name"), "tool_use_id": event.get("tool_use_id"),
        "tool_input": event.get("tool_input"), "failed": failed, "text": text,
    })


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        event = json.load(sys.stdin)
        if mode == "pre":
            pre(event)
        elif mode == "post":
            post(event)
        elif mode == "post-failure":
            post(event, failed=True)
        else:
            raise ValueError("usage: guard.py pre|post")
    except SystemExit:
        raise
    except Exception as exc:  # fail closed for pre; a post failure leaves no evidence, so validation fails
        sys.stderr.write("SDLC guard error: %s\n" % exc)
        sys.exit(2 if mode == "pre" else 0)


if __name__ == "__main__":
    main()
