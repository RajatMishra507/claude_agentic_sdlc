---
description: Run SDLC phase 5/8 (Implementation) with the implementation agent via the orchestrator, then stop for human approval
argument-hint: "[--retry]"
disable-model-invocation: true
allowed-tools: Bash(python3 orchestrator.py status), Bash(python3 orchestrator.py describe implementation), Bash(python3 orchestrator.py run --phase implementation), Bash(python3 orchestrator.py run --phase implementation --retry)
---

Run the Implementation phase. The `implementation` agent does the work; the Python engine delegates to it, validates the result and submits it. Do not do the phase's work yourself.

1. Run `python3 orchestrator.py status`. If `implementation` is not the current phase, or it is `submitted`, report that and stop.
2. Run `python3 orchestrator.py describe implementation` and show the contract.
3. Run `python3 orchestrator.py run --phase implementation`. Append `--retry` only if the user's argument is exactly `--retry`.
4. Report the output verbatim: artifact path (`artifacts/implementation.md`), sha256, any validation failures and any `QUESTION for the human` lines. Do not retry on your own.
5. Stop. The human reviews the artifact and runs `approve implementation` or `reject implementation` with their own approver id in their own terminal. You cannot approve, reject, reopen, authorize a PR, or start the next phase.
