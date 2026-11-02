---
description: Run SDLC phase 6/8 (Review) with the review agent via the orchestrator, then stop for human approval
argument-hint: "[--retry]"
disable-model-invocation: true
allowed-tools: Bash(python3 orchestrator.py status), Bash(python3 orchestrator.py describe review), Bash(python3 orchestrator.py run --phase review), Bash(python3 orchestrator.py run --phase review --retry)
---

Run the Review phase. The `review` agent does the work; the Python engine delegates to it, validates the result and submits it. Do not do the phase's work yourself.

1. Run `python3 orchestrator.py status`. If `review` is not the current phase, or it is `submitted`, report that and stop.
2. Run `python3 orchestrator.py describe review` and show the contract.
3. Run `python3 orchestrator.py run --phase review`. Append `--retry` only if the user's argument is exactly `--retry`.
4. Report the output verbatim: artifact path (`artifacts/review.md`), sha256, any validation failures and any `QUESTION for the human` lines. Do not retry on your own.
5. Stop. The human reviews the artifact and runs `approve review` or `reject review` with their own approver id in their own terminal. You cannot approve, reject, reopen, authorize a PR, or start the next phase.
