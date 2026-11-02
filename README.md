# Agentic SDLC: Automated Documentation Sync

Nine agents move a documentation change from a Confluence user story to a GitHub pull request across eight SDLC phases. A Python engine decides what happens next, validates every artifact, and stops after each phase until a registered human approves. Agents do the work; they never approve it.

**Status:** engine, guard, agents, skills, commands and tests are implemented and tested against a stand-in agent. The Atlassian and GitHub MCP servers have **not** been verified as connected (see [Verification status](#verification-status)).

## 1. Project overview
- **Use case:** keep documentation under `docs/` consistent with an approved Confluence/Jira story.
- **Principle:** Python is the authority. Instructions to agents are guidance; ordering, validation, approval and PR authorization are enforced by `orchestrator.py`, `engine/` and `hooks/guard.py`.
- **Environment:** Claude Code through EPAM CodeMie. `codemie-claude` launches Claude Code here; `claude` is not on PATH.

## 2. Architecture
```
human --(init/approve/reject/reopen/authorize-pr, passphrase on own terminal)--> engine
                                                                                  |
/orchestrator, /requirements ... /pr  --> orchestrator agent --> orchestrator.py run
                                                                                  |
engine: check order + approvals -> launch specialist: claude -p --agent <name> (env: active phase)
   specialist --tool calls--> hooks/guard.py (PreToolUse allow/deny, PostToolUse signed evidence)
   specialist --JSON--> engine: validate (headings, evidence, workspace diff) -> artifacts/<agent>.md -> STOP
```
Layers: (1) engine state machine, (2) per-phase tool allowlists via the guard hook, (3) signed tool-call evidence, (4) hash-chained audit log bound to the state, (5) human credentials for every authority-changing action.

## 3. The nine agents
| Agent | Responsibility | Access | Output |
|---|---|---|---|
| orchestrator | Reads state, runs the next eligible phase through the engine, reports, stops | Bash limited to `status`, `describe`, `run`, `doctor`, `verify-audit`, `verify-evidence`, `check-mcp` | status report |
| requirements | Extracts REQ-n requirements from Confluence/Jira with quotes and source URLs | Atlassian MCP, read-only | `artifacts/requirements.md` |
| architecture | Components, interfaces, data flow, decisions | read-only | `artifacts/architecture.md` |
| design-review | Gaps, risks, security, scalability, maintainability | read-only | `artifacts/design-review.md` |
| planning | Ordered tasks with dependencies and acceptance criteria | read-only | `artifacts/planning.md` |
| implementation | Implements only the plan | Edit/Write under `docs/` only | `artifacts/implementation.md` |
| review | Findings with severity | `git diff`, `git status` | `artifacts/review.md` |
| verify | Runs checks; states `Verdict: PASS` or `Verdict: FAIL` | `pytest`, `git diff`, `git status` | `artifacts/verify.md` |
| pr | Creates the authorized branch and pull request | GitHub MCP, pinned to the authorization | `artifacts/pr.md` |

Agents return JSON; the **engine** validates and saves the artifacts, so an agent cannot fabricate a file. Definitions are in `.claude/agents/`, per-phase playbooks in `.claude/skills/<phase>-playbook/`.

## 4. The eight phases
requirements, architecture, design_review, planning, implementation, review, verify, pr, strictly in that order. States: `pending -> in_progress -> submitted -> approved` (or `rejected`, then resubmit). Every phase has `approval_required: true`, which the engine refuses to load without.

## 5. Orchestrator workflow
1. `status` shows the current phase. 2. `describe <phase>` shows its contract. 3. `run` starts the phase: the engine checks all predecessors are approved, launches the specialist with the approved upstream artifacts, diffs the workspace, validates the result and submits it. 4. **Stop.** 5. A human approves or rejects. 6. Only then can the next phase start.
A phase that fails validation stays `in_progress` and blocked; `run --retry` is a deliberate human step. Missing information comes back as `QUESTION for the human` lines, since a non-interactive run cannot ask mid-run.

## 6. Human approval mechanism
`approve`, `reject`, `reopen` and `authorize-pr` need: a registered human approver id (`init --approver ID`), that person's passphrase (scrypt hash stored in `~/.config/sdlc-engine/`, outside the project), a real controlling terminal, and a typed confirmation containing the artifact hash. They refuse inside an agent session. Duplicate approval, self-approval, agent-like ids (`claude`, `bot-*`, agent names), and approval of invalid or tampered artifacts are refused. A `Verdict: FAIL` verify artifact can never be approved.
Reopening requires a reason, resets the phase and everything downstream, archives their artifacts under `artifacts/_archive/`, invalidates their approvals and the PR authorization.

## 7. Atlassian MCP setup
Declared in `.mcp.json` (`https://mcp.atlassian.com/v2/mcp`, override with `ATLASSIAN_MCP_URL`; endpoint taken from Atlassian's developer page and unconfirmed until `check-mcp` passes). Default auth is OAuth 2.1:
1. In a terminal in this folder run `codemie-claude`, approve the project MCP servers when asked.
2. Type `/mcp`, choose `atlassian`, finish the browser login. The token lives in Claude Code, not the repo. Later `claude -p` phase runs reuse it but cannot log in themselves.
Headless alternative, only if your Atlassian admin enables API-token auth: a Basic `Authorization` header from email + API token supplied via an environment variable, never written into `.mcp.json`.
Evidence rules: a requirement is accepted only with a Confluence (`/wiki/`) or Jira (`/browse/`) URL on a host listed in `requirements_sources`, and a quote found in a signed, recorded Atlassian response. If Atlassian is unavailable or unauthenticated, the phase fails with the recorded error and writes no artifact.

## 8. GitHub MCP setup
Declared in `.mcp.json` (`https://api.githubcopilot.com/mcp/`, bearer token from `GITHUB_PERSONAL_ACCESS_TOKEN`).
1. Create a fine-grained token for the one target repository: Contents and Pull requests read/write.
2. Put it in `.env` (gitignored) as `GITHUB_PERSONAL_ACCESS_TOKEN`. The engine loads it for phase runs; for interactive checks run `set -a; . ./.env; set +a` first, because Claude Code expands `${VAR}` from the process environment only.
Authorization: `authorize-pr` records one repo, head branch (prefix `sdlc/`, never `main`/`master`/`develop`/`release/*`), base branch, PR title, a body generated from the approved artifacts, and the sha256 of every file to publish. It is single-use and is invalidated if any earlier approval changes. The guard allows only `create_branch`, `create_or_update_file`, `push_files` and `create_pull_request` with exactly those values; merges, deletes and forks are denied.

## 9. Hooks and security
`.claude/settings.json` wires `hooks/guard.py` for PreToolUse (`pre`, denies on any error), PostToolUse (`post`) and PostToolUseFailure (`post-failure`), plus deny rules. The guard enforces: per-phase tool allowlists and write paths; MCP servers only inside their phase; no `.env`, secret-store or runtime-state access; no human-only commands (`approve`, `reject`, `reopen`, `authorize-pr`, `init`, `submit`, `start`); no force pushes, `reset --hard`, `clean -f`, branch deletion or pushes to protected branches; a dangerous-shell denylist; and GitHub writes pinned to the authorization. Tool calls are recorded with an HMAC chain keyed outside the project, so evidence cannot be typed in. State is bound to a hash-chained audit log; edits, truncation, or changes to approved artifacts halt the pipeline.
Limits: shell allowlists are not a sandbox; `pytest` in verify runs repository code; the first approver is trust-on-first-use, so run `init` yourself before any agent session.

## 10. Folder structure
```
orchestrator.py            CLI entry point            engine/   state, audit, workflow, approvals, auth,
hooks/guard.py             security hook                        validators, runner, evidence, prcontent, report
sdlc/phases.json           phase table                .claude/agents/      the 9 agents
sdlc/config.json           sources, repo, branches    .claude/skills/      8 *-playbook skills
sdlc/state.json, audit.jsonl   runtime state/audit     .claude/commands/    /orchestrator and /<phase> commands
artifacts/                 engine-written artifacts   .claude/settings.json  hooks and permissions
tests/                     pytest suites              .mcp.json            MCP servers (no secrets)
```

## 11. Installation and setup
1. `python3 -m venv .venv && .venv/bin/pip install pytest`
2. Edit `sdlc/config.json`: `requirements_sources` (Confluence/Jira URLs on your site) and `github_repo` (`owner/repo`).
3. If `sdlc/state.json` is from an older schema, reset it: `: > sdlc/state.json && rm -f sdlc/audit.jsonl`, then `python3 -c "from engine import state; state.init()"`.
4. Register yourself: `python3 orchestrator.py init --approver YOUR_ID` (asks for a passphrase twice).
5. Set up the MCP servers (sections 7 and 8), then `python3 orchestrator.py check-mcp`.
6. If `claude` is not on PATH the engine tries `codemie-claude`; otherwise set `SDLC_CLAUDE_BIN`. Then `python3 orchestrator.py doctor`.

## 12. How to run the project
```
python3 orchestrator.py status
python3 orchestrator.py run                 # next phase: agent -> validate -> submitted, then stops
```
Inside Claude Code the same flow is available as `/orchestrator` and `/requirements` ... `/pr`.

## 13. Approve or reject a phase
In **your own terminal** (not inside an agent session), after reviewing `artifacts/<agent>.md`:
```
python3 orchestrator.py approve requirements --approver YOUR_ID
python3 orchestrator.py reject  requirements --approver YOUR_ID --reason "REQ-3 lacks a source"
python3 orchestrator.py run --phase requirements     # resubmit after a rejection
python3 orchestrator.py reopen  architecture --approver YOUR_ID --reason "Requirement changed"
```

## 14. Authorize and create a PR
After `verify` is approved with `Verdict: PASS`:
```
python3 orchestrator.py authorize-pr --repo OWNER/REPO --head sdlc/docs-sync --base main --approver YOUR_ID [--title "..."]
python3 orchestrator.py run --phase pr       # the pr agent creates the branch and PR through GitHub MCP
python3 orchestrator.py approve pr --approver YOUR_ID
```
You see the exact title, body, files and a content digest, and confirm the digest. `verify-evidence pr` re-checks the recorded PR creation against the signed log and audit record.

## 15. Run the tests
```
.venv/bin/pytest -q                                   # full suite
.venv/bin/pytest -q --ignore=tests/test_cli_pty.py    # without the pseudo-terminal CLI tests
SDLC_LIVE_MCP=1 .venv/bin/pytest -q tests/test_live_mcp.py -rs   # live MCP, after connecting
```
| File | Covers |
|---|---|
| `test_orchestrator.py` | phase order, invalid artifacts, human approval, agent approval attempts, rejection/resubmission |
| `test_reopen_pr_audit.py` | reopen and downstream reset, PR authorization, audit/tamper detection |
| `test_mcp_evidence.py` | Atlassian/GitHub evidence, MCP unavailable, forged identifiers, connection-test parsing, config hygiene |
| `test_guard.py` | every guard rule: agent commands, git, protected branches, GitHub pinning, secrets, shell |
| `test_agent_contracts.py` | agent/skill/command definitions stay consistent with `phases.json`; verify verdict rules |
| `test_integration_hooks.py` | full pipeline with every tool call routed through the real guard hooks; forbidden actions in every phase |
| `test_cli_pty.py` | the real CLI end to end; passphrase and confirmation typed through a pseudo-terminal |
| `test_live_mcp.py` | live MCP connection (opt-in; skipped by default) |
Tests use a stand-in for `claude -p`; they never contact Atlassian, GitHub or a model, except the opt-in live tests.

## 16. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `unsupported state version 1` | Old state file; do setup step 3 |
| `check-mcp`: `Pending approval` | Run `codemie-claude` in this folder and approve the servers |
| `check-mcp`: `Needs authentication` | `/mcp` -> `atlassian` -> log in; for GitHub export the token and restart |
| `Missing environment variables: GITHUB_PERSONAL_ACCESS_TOKEN` | Token not exported in the shell that launched Claude Code |
| `no controlling terminal` / `reserved for humans` | Run approve/reject/reopen/authorize-pr in a normal terminal, not an agent session |
| `authentication failed for approver` | Wrong passphrase, or the id is not registered (`init --approver`) |
| `Atlassian MCP is unavailable or authentication failed` | The recorded tool error is shown; fix login/URL, then `run --retry` |
| `blocked; ... rerun with --retry` | Validation failed; read the listed errors, then `run --retry` |
| `state.json does not match the audit log` | Edited outside the engine, or the audit log was truncated; restore both from version control or re-initialize |
| `the verification verdict is FAIL` | Reject `verify`, fix via `reopen implementation`, and verify again |
| `SDLC guard: ...` | A hook denied the action; the message names the rule |

## Verification status
See the final report for the exact test counts. MCP status is whatever `python3 orchestrator.py check-mcp` prints right now; it says `CONNECTED` only when the Claude Code CLI itself reports `Connected`.
