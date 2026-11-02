---
name: pr-playbook
description: Playbook for the PR phase. Use when publishing approved work as a branch and pull request through GitHub MCP.
user-invocable: false
---

# PR playbook

## Procedure
1. Run `python3 orchestrator.py status`: every earlier phase must be `approved`, and the verify artifact must state `PASS`. Confirm the human-authorized repo, head and base in the prompt. Stop and report if anything is missing.
2. Create the authorized head branch from the authorized base branch (not any other name).
3. Push exactly the files listed by the approved implementation artifact, with their current content.
4. Open one pull request from the feature branch to the base branch. Title and body come from the approved artifacts: summary, requirements covered, verification result.
5. Read back the pull request result and record its URL and branch.

## Artifact skeleton
```
## Summary        what the change does and why
## Branch         branch name and base
## Pull Request   URL returned by GitHub MCP
## Evidence       each tool call made and the identifier it returned
```

## Quality bar
- The PR URL must come verbatim from a GitHub MCP response; never construct one.
- Never push to the base branch, merge, delete, or fork. Hooks deny these.
- If any call fails, report the failure and stop. A partial result is reported as partial.
