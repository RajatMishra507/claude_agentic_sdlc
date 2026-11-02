"""Read-only views: status, describe, doctor."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from . import audit, auth, evidence
from . import common as c
from . import config as cfg
from . import runner, state as st

NEXT_ACTION = {
    "pending": "python3 orchestrator.py run --phase {p}",
    "in_progress": "python3 orchestrator.py run --phase {p} --retry   (blocked: see failures above)",
    "submitted": "HUMAN: review {artifact}, then python3 orchestrator.py approve|reject {p} --approver ID",
    "rejected": "python3 orchestrator.py run --phase {p}   (resubmits with the rejection reason)",
}


def status_report(as_json: bool = False) -> str:
    data = cfg.load_phases()
    state = st.load() or st.new_state()
    if as_json:
        return json.dumps(state, indent=2)
    lines = ["SDLC pipeline  run=%s%s" % (state["run_id"], "" if st.load() else "  (not initialized)"),
             "%-2s %-15s %-15s %-12s %s" % ("#", "PHASE", "AGENT", "STATUS", "ATTEMPT")]
    for i, pid in enumerate(c.PHASE_ORDER, 1):
        ps = state["phases"][pid]
        lines.append("%-2d %-15s %-15s %-12s %d" % (i, pid, cfg.phase_def(data, pid)["agent"], ps["status"], ps["attempt"]))
    target = st.next_phase(state)
    if target is None:
        lines.append("\nPipeline complete: all 8 phases approved.")
    else:
        ps = state["phases"][target]
        lines.append("\nCurrent phase: %s (%s)" % (target, ps["status"]))
        if ps.get("artifact"):
            lines.append("Artifact: %s  sha256=%s" % (ps["artifact"], ps["artifact_sha256"][:12]))
        if ps.get("rejection"):
            lines.append("Rejected by %s: %s" % (ps["rejection"]["by"], ps["rejection"]["reason"]))
        for err in ps.get("last_validation_errors", []):
            lines.append("Blocked: %s" % err)
        lines.append("Next: " + NEXT_ACTION[ps["status"]].format(p=target, artifact=ps.get("artifact")))
    auth_rec = state.get("pr_authorization")
    if auth_rec:
        lines.append("PR authorization: %s %s -> %s [%s]" % (auth_rec["repo"], auth_rec["head"], auth_rec["base"], auth_rec["status"]))
    return "\n".join(lines)


def describe(phase_id: str, as_json: bool = False) -> str:
    data, config = cfg.load_phases(), cfg.load_config()
    ph = cfg.phase_def(data, phase_id)
    state = st.load() or st.new_state()
    idx = c.PHASE_ORDER.index(phase_id)
    info = {
        "phase": phase_id, "number": "%d/8" % (idx + 1), "agent": ph["agent"], "status": state["phases"][phase_id]["status"],
        "attempt": state["phases"][phase_id]["attempt"], "responsibility": ph["responsibility"],
        "predecessors": {p: state["phases"][p]["status"] for p in c.PHASE_ORDER[:idx]},
        "required_headings": ph["required_headings"], "allowed_tools": data["common_tools"] + ph.get("tools", []),
        "write_paths": ph.get("write_paths", []), "validation_checks": ph.get("checks", []),
        "approval_required": ph["approval_required"], "draft": "artifacts/%s/draft.json" % phase_id,
        "artifact_after_submission": "artifacts/%s.md" % c.AGENTS[phase_id],
        "output_schema": runner.OUTPUT_SCHEMA,
    }
    if phase_id == "requirements":
        info["sources"] = config.get("requirements_sources", [])
    if as_json:
        return json.dumps(info, indent=2)
    lines = ["Phase %s: %s  (agent: %s)" % (info["number"], phase_id, ph["agent"]),
             "Status: %s (attempt %d)" % (info["status"], info["attempt"]),
             "Responsibility: %s" % info["responsibility"],
             "Predecessors: %s" % (", ".join("%s=%s" % kv for kv in info["predecessors"].items()) or "none"),
             "Required headings: %s" % ", ".join(info["required_headings"]),
             "Allowed tools: %s" % ", ".join(info["allowed_tools"]),
             "Write paths: %s" % (", ".join(info["write_paths"]) or "none"),
             "Validation checks: %s" % (", ".join(info["validation_checks"]) or "structure only"),
             "Artifact (engine-written on submission): %s" % info["artifact_after_submission"],
             "Draft file: %s (JSON per schema; see --json)" % info["draft"],
             "Approval: required. A registered human runs: python3 orchestrator.py approve %s --approver ID" % phase_id]
    return "\n".join(lines)


def doctor() -> list:
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    claude = os.environ.get("SDLC_CLAUDE_BIN") or shutil.which("claude") or shutil.which("codemie-claude")
    check("claude binary", claude, claude or "not on PATH (tried claude, codemie-claude); set SDLC_CLAUDE_BIN")
    try:
        cfg.load_phases()
        check("phases.json", True)
        config = cfg.load_config()
        check("config: requirements_sources", config.get("requirements_sources"), "needed for phase 1")
        check("config: github_repo", config.get("github_repo"), "needed for phase 8")
    except c.SdlcError as exc:
        check("phases/config", False, str(exc))
    try:
        servers = json.loads(c.path(".mcp.json").read_text(encoding="utf-8")).get("mcpServers", {})
        check("mcp servers (atlassian, github)", {"atlassian", "github"} <= set(servers))
    except (OSError, ValueError) as exc:
        check(".mcp.json", False, str(exc))
    try:
        wired = "guard.py" in c.path(".claude", "settings.json").read_text(encoding="utf-8")
    except OSError:
        wired = False
    check("guard hooks wired in .claude/settings.json", wired, "" if wired else "hooks are NOT enforcing")
    check("evidence signing key", evidence.key_path(c.ROOT).is_file(), "run init")
    check("registered human approvers", auth.registry(), "run: python3 orchestrator.py init --approver YOUR_ID")
    check("GITHUB_PERSONAL_ACCESS_TOKEN set", os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"), "needed for GitHub MCP")
    try:
        check("audit chain", True, "%d entries" % audit.verify())
        st.load()
        check("state integrity", True)
    except c.SdlcError as exc:
        check("audit/state integrity", False, str(exc))
    return results


REQUIRED_MCP = ("atlassian", "github")
MCP_LINE = re.compile(r"^(?P<name>[\w.-]+):\s+.*?\s-\s+(?P<status>.+)$")


def check_mcp(run=subprocess.run) -> list:
    """Real connection test: ask the Claude Code CLI to health-check the configured MCP servers.

    A server counts as connected only if the CLI itself reports it connected. Pending approval,
    needs-authentication and failed states are all reported as NOT connected.
    """
    binary = os.environ.get("SDLC_CLAUDE_BIN") or shutil.which("claude")
    cmd = [binary, "mcp", "list"] if binary else (["codemie", "mcp", "list"] if shutil.which("codemie") else None)
    if cmd is None:
        return [(name, False, "no claude or codemie CLI found; cannot test") for name in REQUIRED_MCP]
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=180, cwd=str(c.ROOT))
    except (OSError, subprocess.SubprocessError) as exc:
        return [(name, False, "connection test could not run: %s" % exc) for name in REQUIRED_MCP]
    statuses = {}
    for line in (proc.stdout or "").splitlines():
        m = MCP_LINE.match(line.strip())
        if m:
            statuses[m.group("name")] = m.group("status").strip()
    results = []
    for name in REQUIRED_MCP:
        status = statuses.get(name)
        ok = bool(status) and re.search(r"\bconnected\b", status, re.I) and not re.search(
            r"not connected|disconnected|fail|error|needs? auth|pending|disabled", status, re.I)
        results.append((name, bool(ok), status or "not reported by the CLI (not configured?)"))
    return results


def verify_evidence(only=None) -> list:
    """Re-check stored evidence against the signed tool log and the audit record."""
    state, results = st.load(), []
    if state is None:
        return results
    submitted = [e for e in audit.read() if e["action"] == "phase_submitted"]
    for pid in c.PHASE_ORDER:
        ps = state["phases"][pid]
        if (only and pid != only) or not ps.get("evidence_sha256"):
            continue
        problems = []
        fp = c.path(ps["artifact"][:-3] + ".evidence.json")
        if not fp.is_file() or c.sha256_file(fp) != ps["evidence_sha256"]:
            problems.append("evidence file missing or changed")
        record = [e for e in submitted if e["phase"] == pid and e["details"].get("artifact_sha256") == ps["artifact_sha256"]]
        refs = record[-1]["details"].get("mcp_evidence", []) if record else []
        if not record:
            problems.append("no audit record for this artifact")
        entries, log_problems = evidence.read_attempt(c.ROOT, ps["attempt_id"])
        problems += log_problems
        by_mac = {e.get("mac"): e for e in entries}
        for ref in refs:
            entry = by_mac.get(ref.get("log_mac"))
            if not entry or entry.get("failed") or entry.get("tool_name") != ref.get("tool_name"):
                problems.append("audit reference %s has no matching signed tool call" % ref.get("log_mac", "?")[:12])
        results.append((pid, not problems, "; ".join(problems) or "%d evidence reference(s) verified against the signed tool log" % len(refs)))
    return results
