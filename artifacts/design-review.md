## Findings

Severity scale: high = a requirement cannot be met or verified, or a concrete failure is likely; medium = likely rework or verification trouble; low = minor; none = reviewed, no issue.

| ID | Severity | Component / REQ | Issue |
|---|---|---|---|
| F1 | high | REQ-4, REQ-5; D6, coverage matrix, R1 | The architecture defines no behaviour for `add` under REQ-4 ("repeating a no-op produces a clear message") or REQ-5 ("invalid or unknown id produces a clear error"). D6 says create-specific behaviour "waits for an answer to Q1". The coverage matrix still lists REQ-4 as covered by C2/C5/C8. That overstates coverage, because nothing in the design makes `add` produce a no-op message. Failure scenario: planning and implementation proceed with no decision on Q1. Either the implementer invents behaviour (for example `add --id`), or REQ-4 gets no task and no test and the later verify phase passes with REQ-4 unverified. REQ-5 is partly covered, because invalid and unknown ids are handled for done, reopen and delete, but not for create as the requirement is worded. |
| F2 | medium | REQ-1, REQ-17; C8, D2, D8 | The documented entry point `python3 -m todo_app` cannot work from the repository root once the package is at `docs/todo_app/`. `docs/` is not on `sys.path`. The user would have to run from `docs/` or set `PYTHONPATH`. The architecture neither states this nor specifies how a user launches the app. The verify allowlist (sdlc/phases.json:86-88) covers pytest and git-read commands only. In-process `main(argv)` tests would therefore be the only runtime evidence. |
| F3 | medium | R2, C9, D9; REQ-1 to REQ-17 | Test collection and import is left to the plan (R2). Under pytest's default import mode, `import todo_app` from tests under `docs/todo_app/tests/` works only if the package chain has `__init__.py` files. Otherwise the first directory without one goes on `sys.path` and the imports fail. Test basenames could also collide with files in the repo's own `tests/`. Failure scenario: pytest collects nothing or hits ImportError, the verify phase has no real passing output, and the PASS cannot be backed (CLAUDE.md requires recorded passing output). The existing `tests/conftest.py` only adds the repo root to `sys.path` and does not help here. |
| F4 | medium | C4, R6, C9 | The default data file is in the current working directory. If any test or manual run goes through `main()` without `--file` or the environment override, it writes a stray `todo` JSON file into the repository root. That is outside `docs/` and would be flagged by the workspace-diff check at engine/validators.py:186, or it would pollute the repo. The design says tests use `tmp_path` but does not make that a rule for every CLI test. It also does not say whether the default file name is git-ignored. |
| F5 | medium | C4, REQ-2, REQ-6, REQ-16 | "Checks the schema on load" is not specified. The uniqueness guarantee of D4 depends on `next_id` being greater than every stored id and on ids being unique integers. A hand-edited or partly corrupt file (duplicate ids, `next_id` less than or equal to max id, `true` where an int is expected, a status other than `open`/`done`, a non-string title) would otherwise load and silently break REQ-2 or REQ-6. The load invariants should be listed so they can be tested. |
| F6 | medium | C6, C8, REQ-5, REQ-10, REQ-13, REQ-15 | A5 says an invalid id is "not a positive integer" but gives no parsing rule. Plain `int()` accepts `" 5"`, `"+5"`, `"1_0"` and non-ASCII digits. A negative value such as `-3` passed as an `argparse` positional is treated as an option flag, so the user gets an argparse usage error (exit 2) and never reaches `InvalidIdError`. Behaviour is still an error, but the message and path differ from the design's "id parser raises InvalidIdError" and may not be "clear" for REQ-5, REQ-10, REQ-13 and REQ-15. |
| F7 | low | C5, C8, REQ-16, A-title | Titles are free text, but a title starting with `-` (for example `add -draft`) is rejected by `argparse` unless the user types `--`. Empty or whitespace-only titles are stored silently unless Q5 is answered. This is acknowledged for the empty case. The leading-dash case is not mentioned. |
| F8 | low | C7, R5, REQ-3 | Beyond the newline issue in R5, titles with control or ANSI escape characters can alter terminal output. A title with non-ASCII characters can also raise `UnicodeEncodeError` on a terminal with a non-UTF-8 stdout. The design does not say how output encoding is handled or what happens then. Impact is limited to a single-user local tool. |
| F9 | low | C2, C4, C8, C1 | Maintainability inconsistencies. `StoreError` is caught in C8 and raised in C4, but C2 lists only `TodoError`, `InvalidIdError` and `UnknownIdError`, so its home and base class are not stated. C1 is described as "immutable-style" while C5 changes status, and the design does not say whether it uses `frozen=True` with `replace` or mutation. The `TaskStore` interface has one real implementation (justified by testability and D3). |
| F10 | medium | D2, R7; REQ-17 | The configured purpose in `sdlc/config.json` is "Automated Documentation Sync" for `docs/`, while the approved requirements describe a to-do CLI application. The architecture places application code and tests under `docs/` only because of `write_paths`. I confirmed the constraint at sdlc/phases.json:62, hooks/guard.py:316-317 and engine/validators.py:186. The decision is reasonable but belongs to a human. Alternatives (changing `write_paths`) are out of scope for this design, and I do not recommend one. |
| F11 | low | R4 | No file locking, so concurrent invocations are last-writer-wins and one change can be lost. Accepted by the design for a single-user CLI, and the atomic replace prevents corrupted files. I agree with the acceptance. |

**Security.** No blocking issue. Inputs are limited to argv and a local JSON file. The design parses with `json` only (no `eval` or `pickle`), validates ids before use, uses atomic writes, and has no network, secrets or third-party packages. Residual items are F5 (load validation), F6 (id parsing strictness), F8 (terminal output) and the `--file`/environment path override. The override writes with the invoking user's own privileges and is acceptable for a local single-user tool.

**Scalability.** No issue for the stated scope. Every command loads and rewrites the whole file, which is O(n). That is fine for a simple personal task list. No requirement sets a size or concurrency target. F11 notes the lack of locking.

**Maintainability.** Mostly good. The modules are small and single-purpose, the service is free of I/O, and every assumption is isolated behind one component. The issues are F9 (small inconsistencies), F2/F3 (non-obvious run and test mechanics from the `docs/` placement) and the fact that nine components is on the heavy side for "small" (REQ-17). The architecture justifies this in D1, and I do not consider it a defect.

## Requirement Coverage

Status is judged on whether the architecture defines how the REQ is met, not on whether the assumptions behind it are confirmed.

| REQ | Status | Notes |
|---|---|---|
| REQ-1 | covered | C3/C4/C8. Depends on assumption A1 (persistence). The run command needs clarifying (F2). |
| REQ-2 | covered | C1/C4/C5, D4 counter. Load-time invariants needed to protect uniqueness (F5). |
| REQ-3 | covered | C5/C7/C8 print id, title and status on create. |
| REQ-4 | uncovered | No `add` behaviour defined. D6 defers it to Q1 and the matrix overstates coverage (F1). |
| REQ-5 | partial | Invalid/unknown id errors exist for done, reopen and delete (C6/C2/C8). Nothing for create as worded (F1). Id parsing rules need tightening (F6). |
| REQ-6 | covered | Append-only storage order, D5. |
| REQ-7 | covered | C7 empty-list message, C8. |
| REQ-8 | covered | C5 `complete`. |
| REQ-9 | covered | No-op `Outcome`, exit 0, no write. |
| REQ-10 | covered | `UnknownIdError`, stderr, non-zero exit, no save. Negative-id path via argparse noted in F6. |
| REQ-11 | covered | C5 `reopen`. |
| REQ-12 | covered | No-op `Outcome`. |
| REQ-13 | covered | `UnknownIdError` for reopen. |
| REQ-14 | covered | C5 `delete`, `next_id` unchanged. |
| REQ-15 | covered | `UnknownIdError` for delete. |
| REQ-16 | covered | Titles stored verbatim. Leading-dash and encoding edge cases noted in F7 and F8. |
| REQ-17 | covered | Stdlib-only Python package, `argparse`. Placement under `docs/` is a human decision (F10). |

Summary: 15 covered, 1 partial (REQ-5), 1 uncovered (REQ-4).

## Risks

| # | Risk | Likelihood / impact | Notes |
|---|---|---|---|
| RR1 | Q1 stays unanswered and the implementer invents create behaviour for REQ-4 and REQ-5, or leaves it unverified (F1). | Medium / high | Requires a human decision before planning. |
| RR2 | Tests are not collected, or their imports fail, because the package is under `docs/` (F3). The verify phase then has no passing output. | Medium / high for the pipeline | Planning must specify the `__init__.py` chain, test file names and the exact `.venv/bin/pytest` invocation. |
| RR3 | Stray data file or `__pycache__` produced outside the expected tree (F4). | Medium / low | Tests must always supply a `tmp_path` file. |
| RR4 | Assumptions A1-A5 (persistence, id format, CLI syntax, list output, id validity) differ from the author's intent. | Medium / medium | Isolated by design (architecture R3). Open Questions 2-6 remain unanswered. |
| RR5 | Hand-edited data file breaks id uniqueness (F5). | Low / medium | Define and test the load invariants. |
| RR6 | Reviewer or stakeholder objects to application code in a documentation-sync repo (F10). | Medium / low | Human decision. |
| RR7 | Python 3.9 compatibility drift (architecture R8). | Low / low | Not testable here: `.venv` is 3.14, so a 3.9-only break would not be caught by the verify runs. Planning could note it as a review check. |

## Verdict

**approve-with-conditions.**

Reasons:
- The design is coherent and proportionate. It meets 15 of 17 requirements by design, separates rules from I/O and has a sensible failure model (no-ops exit 0 without writes, errors go to stderr and exit non-zero, atomic saves). I found no blocking security or scalability problem. Its claims about the repository (the `docs/`-only write constraint) hold up against the files I inspected.
- It is not approve-as-is because REQ-4 is effectively unaddressed and REQ-5 is only partly addressed, while the coverage matrix says otherwise (F1). The run and test mechanics under `docs/` are also left open, and they directly decide whether the verify phase can produce real passing output (F2, F3).
- It is not rework-needed because the gaps are bounded and do not require changing the component structure. The reviewer has not been asked to redesign it.

Conditions for the human before the planning phase starts:
1. Resolve Open Question 1, or explicitly record that REQ-4 and REQ-5 are descoped or limited to the id-taking commands, so planning has a defined target (F1).
2. Planning should state: the run command and its working directory or `PYTHONPATH` (F2); the test directory, `__init__.py` layout and collection command (F3); that every CLI test supplies its own temporary data file (F4); the `load()` invariants (F5); and the strict id parsing rule (F6).
3. A human should confirm that placing the application under `docs/` is acceptable (F10).

This verdict is advice only. A human approves or rejects this phase.
