---
description: Coordinate the SDLC pipeline as the orchestrator agent (status, describe, run the next phase, doctor, verify-audit)
argument-hint: "[status|describe <phase>|run|doctor|verify-audit]"
disable-model-invocation: true
allowed-tools: Bash(python3 orchestrator.py status*), Bash(python3 orchestrator.py describe *), Bash(python3 orchestrator.py doctor), Bash(python3 orchestrator.py verify-audit), Bash(python3 orchestrator.py run), Bash(python3 orchestrator.py run --phase *)
---

Act as the `orchestrator` agent (see `.claude/agents/orchestrator.md`) for the requested action: `$ARGUMENTS` (default `status`).

- `status`, `describe <phase>`, `doctor`, `verify-audit`: run `python3 orchestrator.py <action>` and report the output verbatim.
- `run`: run `status`, then `describe` for the current phase, then `python3 orchestrator.py run --phase <current phase>`. Report verbatim, then stop.
- Anything else: ask which action is meant.

After `run`, name the artifact (`artifacts/<agent>.md`) to review and tell the human to run `approve <phase>` or `reject <phase>` with their own approver id in their own terminal. You cannot approve, reject, reopen, authorize a PR, or start another phase, and you continue only after `status` shows the previous phase `approved`.
