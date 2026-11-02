---
name: implementation-playbook
description: Playbook for the Implementation phase. Use when carrying out an approved plan with edits limited to the permitted write paths.
user-invocable: false
---

# Implementation playbook

## Procedure
1. Read the approved plan and the current contents of every file a task names.
2. Implement tasks in the planned order, one at a time, with the smallest change that satisfies the acceptance check.
3. Stay inside the permitted write paths (default `docs/`). A needed change outside them is an Open Question, not an edit.
4. After each task, re-read the changed file to confirm the result.
5. Collect the exact list of files you changed for `files_changed`.

## Artifact skeleton
```
## Changes       per file: what changed
## Rationale     why, tied to REQ ids
## Task Mapping  T1 -> files, T2 -> files, ...
```

## Quality bar
- `files_changed` matches the real changes exactly; the orchestrator compares it with the workspace.
- No unplanned scope, no git operations, no branch or PR actions.
- Documentation content states only facts supported by the approved requirements.
