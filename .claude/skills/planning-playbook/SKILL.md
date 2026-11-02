---
name: planning-playbook
description: Playbook for the Planning phase. Use when turning an approved design into ordered, testable implementation tasks.
user-invocable: false
---

# Planning playbook

## Procedure
1. Take the approved architecture and design review conditions as the scope. Add nothing beyond them.
2. Split the work into small tasks, each independently checkable.
3. For each task record: id, goal, files it may touch (inside the permitted write paths), REQ ids, and an acceptance check.
4. Order tasks by dependency and call out anything that can run in parallel.
5. Define how the result will be verified and how to roll back.

## Artifact skeleton
```
## Tasks           T1..Tn: goal, files, REQ ids, acceptance check
## Sequencing      dependency order and parallel groups
## Test Strategy   what is checked, with which commands, expected outcomes
## Rollback        how to undo the change safely
```

## Quality bar
- Every REQ id is covered by at least one task, and every task cites at least one REQ id.
- Each acceptance check can be run by the verify phase with allowlisted commands.
- No task touches a path outside the implementation write paths.
