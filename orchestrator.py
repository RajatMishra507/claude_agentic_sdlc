#!/usr/bin/env python3
"""Command-line entry point for the SDLC workflow engine (logic lives in engine/)."""
from __future__ import annotations

import argparse
import getpass
import sys

from engine import approvals, audit, auth, report, workflow
from engine import common as c


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orchestrator.py", description="Authoritative SDLC workflow engine")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    init = sub.add_parser("init", help="HUMAN: create state and register approvers")
    init.add_argument("--approver", action="append", default=[], metavar="USER_ID", help="approver to register (repeatable)")

    status = sub.add_parser("status", help="show pipeline status")
    status.add_argument("--json", action="store_true")

    describe = sub.add_parser("describe", help="show a phase's contract and state")
    describe.add_argument("phase")
    describe.add_argument("--json", action="store_true")

    run = sub.add_parser("run", help="run the next phase with its agent, validate, then stop for approval")
    run.add_argument("--phase", help="assert the expected phase (must be the next one)")
    run.add_argument("--retry", action="store_true", help="rerun a blocked in-progress phase")

    start = sub.add_parser("start", help="HUMAN: mark a phase in_progress without running an agent")
    start.add_argument("phase")
    start.add_argument("--retry", action="store_true")

    submit = sub.add_parser("submit", help="HUMAN: validate artifacts/<phase>/draft.json and submit it")
    submit.add_argument("phase")

    for name, helptext in (("approve", "HUMAN: approve a submitted phase"), ("reject", "HUMAN: reject a submitted phase")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("phase")
        sp.add_argument("--approver", required=True, metavar="USER_ID", help="registered human approver id")
        if name == "reject":
            sp.add_argument("--reason", required=True)

    reopen = sub.add_parser("reopen", help="HUMAN: reopen a phase and reset everything downstream")
    reopen.add_argument("phase")
    reopen.add_argument("--approver", required=True, metavar="USER_ID")
    reopen.add_argument("--reason", required=True)

    pr = sub.add_parser("authorize-pr", help="HUMAN: authorize exactly one pull request")
    pr.add_argument("--repo", required=True, metavar="OWNER/REPOSITORY")
    pr.add_argument("--head", required=True, metavar="FEATURE_BRANCH")
    pr.add_argument("--base", required=True)
    pr.add_argument("--approver", required=True, metavar="USER_ID")
    pr.add_argument("--title", help="pull request title (default derived from the run id)")

    sub.add_parser("verify-audit", help="verify the audit hash chain")
    ve = sub.add_parser("verify-evidence", help="re-verify stored MCP evidence against the signed log and audit record")
    ve.add_argument("phase", nargs="?")
    sub.add_parser("check-mcp", help="real connection test of the Atlassian and GitHub MCP servers")
    sub.add_parser("doctor", help="check environment readiness")
    return p


def dispatch(args) -> int:
    cmd = args.cmd
    if cmd == "status":
        print(report.status_report(args.json))
    elif cmd == "describe":
        print(report.describe(args.phase, args.json))
    elif cmd == "run":
        result = workflow.run_phase(args.phase, args.retry)
        if not result["ok"]:
            print("VALIDATION FAILED for %s; the phase is blocked:" % result["phase"])
            print("\n".join("  - " + e for e in result["errors"]))
            return 1
        print(result["message"])
        for question in result.get("questions") or []:
            print("QUESTION for the human: " + question)
        if result.get("artifact"):
            print("Artifact: %s\nsha256: %s\nHUMAN: review it, then run: python3 orchestrator.py approve %s --approver YOUR_ID"
                  % (result["artifact"], result["sha256"], result["phase"]))
    elif cmd == "init":
        result = approvals.init_pipeline(args.approver, auth.human_console())
        print("Initialized run %s. Registered: %s. Approvers: %s" % (result["run_id"], result["registered"] or "none", result["approvers"]))
    elif cmd == "start":
        auth.forbid_agent_context()
        print(workflow.start_phase(args.phase, args.retry))
    elif cmd == "submit":
        auth.forbid_agent_context()
        result = workflow.submit_phase(args.phase, getpass.getuser())
        if not result["ok"]:
            print("VALIDATION FAILED for %s:" % args.phase)
            print("\n".join("  - " + e for e in result["errors"]))
            return 1
        print(result["message"])
    elif cmd == "approve":
        result = approvals.approve_phase(args.phase, args.approver, auth.human_console())
        print("Approved %s. Next phase: %s" % (result["phase"], result["next"] or "none (pipeline complete)"))
    elif cmd == "reject":
        approvals.reject_phase(args.phase, args.approver, args.reason, auth.human_console())
        print("Rejected %s. It stays blocked until corrected and resubmitted." % args.phase)
    elif cmd == "reopen":
        result = approvals.reopen_phase(args.phase, args.approver, args.reason, auth.human_console())
        print("Reopened %s. Reset: %s. Archived to %s" % (result["phase"], ", ".join(result["reset"]), result["archived_to"]))
    elif cmd == "authorize-pr":
        rec = approvals.authorize_pr(args.repo, args.head, args.base, args.approver, auth.human_console(), args.title)
        print("PR authorized (%s): %s %s -> %s" % (rec["id"], rec["repo"], rec["head"], rec["base"]))
    elif cmd == "verify-audit":
        print("audit chain OK (%d entries)" % audit.verify())
    elif cmd == "verify-evidence":
        results = report.verify_evidence(args.phase)
        for name, ok, detail in results:
            print("%s %-14s %s" % ("ok  " if ok else "FAIL", name, detail))
        return 0 if results and all(ok for _, ok, _ in results) else 1
    elif cmd == "check-mcp":
        results = report.check_mcp()
        for name, ok, detail in results:
            print("%s %-10s %s" % ("CONNECTED    " if ok else "NOT CONNECTED", name, detail))
        return 0 if all(ok for _, ok, _ in results) else 1
    elif cmd == "doctor":
        failed = False
        for name, ok, detail in report.doctor():
            failed |= not ok
            print("%s %-44s %s" % ("ok  " if ok else "FAIL", name, detail if not ok or detail.endswith("entries") else ""))
        return 1 if failed else 0
    return 0


def main(argv=None) -> int:
    c.load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        return dispatch(args)
    except c.SdlcError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
