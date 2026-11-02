---
name: verify-playbook
description: Playbook for the Verify phase. Use when proving acceptance criteria with real command output.
user-invocable: false
---

# Verify playbook

## Procedure
1. Collect the acceptance checks from the approved plan and the requirement list.
2. Run each check as one allowlisted command at a time (`pytest`, `git diff`, `git status`). No chaining, redirection or pipes. Run tests with `.venv/bin/pytest <path> -q`: the system `python3` has no pytest, so a plan command written as `python3 -m pytest <path>` must be run as `.venv/bin/pytest <path>` instead, and note the substitution under Commands Run. The engine requires every recorded `pytest` command to pass, so never run a command you expect to fail, even if you retry it afterwards. Run the commands the approved plan's Test Strategy names. The whole-repository run (`.venv/bin/pytest -q`) takes about two minutes, which is at the default Bash tool timeout, and a timed-out call records empty output that blocks `PASS`. Always pass the Bash tool's `timeout` parameter as `600000` (10 minutes) on every `pytest` command.
3. Record the exact command and the actual outcome for each.
4. Map every acceptance criterion to a result: pass, fail, or not verifiable (with the reason).
5. Conclude with a verdict. Under `## Verdict`, write exactly one line `Verdict: PASS` or `Verdict: FAIL`, in capitals, and never both. The engine reads that literal line; wording such as "verified" or "all checks passed" is not accepted in its place. Put your reasons on separate lines below it, and do not write the words `Verdict: PASS` or `Verdict: FAIL` anywhere else in the artifact.

Output artifact (engine-written after validation): `artifacts/verify.md`. The engine rejects a `PASS` that the recorded output does not support, and refuses to approve a `FAIL`.

## Artifact skeleton
```
## Commands Run                 exact commands, in order
## Results                      actual output summary per command
## Acceptance Criteria Check    criterion -> pass | fail | not verifiable
## Verdict                      line `Verdict: PASS` or `Verdict: FAIL`, then reasons
```

## Quality bar
- Report only outcomes you observed. A command that was not run is not a result.
- A failing or unrunnable check is reported plainly; the verdict reflects it.
- Do not modify files to make a check pass.
