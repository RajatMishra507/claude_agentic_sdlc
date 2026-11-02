---
name: design-review-playbook
description: Playbook for the Design Review phase. Use when critiquing an approved architecture against approved requirements.
user-invocable: false
---

# Design review playbook

## Procedure
1. Build a coverage table: each REQ id against the components and decisions that satisfy it.
2. Probe for gaps: unmet or partly met requirements, unstated assumptions, single points of failure, security and data-handling issues, operability and testability.
3. Rate each finding (high, medium, low) and name the component or REQ affected.
4. Check the risks the architecture already lists for missing mitigations.
5. Conclude with a verdict and the conditions attached to it.

## Artifact skeleton
```
## Findings              id, severity, location, issue, suggested direction
## Requirement Coverage  table: REQ id -> covered / partial / uncovered
## Risks                 residual risks after the design
## Verdict               approve-as-is | approve-with-conditions | rework-needed, with reasons
```

## Quality bar
- Report problems; do not redesign. Suggestions stay short and directional.
- Every high finding is traceable to a REQ or a concrete failure scenario.
- The verdict is advice. Only a human approves.
