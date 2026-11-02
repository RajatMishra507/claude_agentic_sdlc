---
name: architecture-playbook
description: Playbook for the Architecture phase. Use when designing a solution from approved requirements.
user-invocable: false
---

# Architecture playbook

## Procedure
1. Read the approved requirements and inspect the repository to learn what already exists.
2. Identify components and their responsibilities. Prefer extending existing structure over inventing new structure.
3. Describe data flow between components, including failure paths and trust boundaries.
4. Record each significant decision with alternatives considered and the reason for the choice.
5. List risks and assumptions explicitly.

## Artifact skeleton
```
## Context        problem, constraints, existing system facts
## Components     name, responsibility, REQ ids satisfied
## Data Flow      step-by-step flow, including errors
## Decisions      decision, alternatives, rationale, REQ ids
## Risks          risk, impact, mitigation
```

## Quality bar
- Every REQ id maps to at least one component. Nothing is designed that no REQ needs.
- Security and failure behaviour are stated, not implied.
- Do not plan tasks or write code; those belong to later phases.
