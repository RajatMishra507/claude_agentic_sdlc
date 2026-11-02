---
name: review-playbook
description: Playbook for the Review phase. Use when reviewing an implementation against the approved plan and requirements, read-only.
user-invocable: false
---

# Review playbook

## Procedure
1. Run `git status` and `git diff` (one command at a time) to see exactly what changed.
2. Walk the plan task by task and mark each compliant, partial, or missing, citing files.
3. Check correctness, consistency with the requirements, unplanned changes, and quality of the content written.
4. Rate findings by severity and name the file and task affected.
5. Conclude with a verdict.

## Artifact skeleton
```
## Findings          id, severity, file, issue
## Task Compliance   T1..Tn: compliant | partial | missing, with evidence
## Verdict           ready-to-verify | changes-needed, with reasons
```

## Quality bar
- Every statement is grounded in the diff or a file you read.
- No fixes are made; findings only.
- Anything outside the planned scope is reported as a finding.
