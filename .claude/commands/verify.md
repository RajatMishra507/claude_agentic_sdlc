---
description: Run SDLC phase 7/8 (Verify) with the verify agent via the orchestrator, then stop for human approval
argument-hint: "[--retry]"
disable-model-invocation: true
allowed-tools: Bash(python3 orchestrator.py status), Bash(python3 orchestrator.py describe verify), Bash(python3 orchestrator.py run --phase verify), Bash(python3 orchestrator.py run --phase verify --retry)
---

Run the Verify phase. The `verify` agent does the work; the Python engine delegates to it, validates the result and submits it. Do not do the phase's work yourself.

1. Run `python3 orchestrator.py status`. If `verify` is not the current phase, or it is `submitted`, report that and stop.
2. Run `python3 orchestrator.py describe verify` and show the contract.
3. Run `python3 orchestrator.py run --phase verify`. Append `--retry` only if the user's argument is exactly `--retry`.
4. Report the output verbatim: artifact path (`artifacts/verify.md`), sha256, any validation failures and any `QUESTION for the human` lines. Do not retry on your own.
5. Stop. The human reviews the artifact and runs `approve verify` or `reject verify` with their own approver id in their own terminal. You cannot approve, reject, reopen, authorize a PR, or start the next phase.
