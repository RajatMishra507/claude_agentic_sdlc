## Findings

Severity scale: critical = security or data-loss defect; high = a requirement is broken or likely broken; medium = likely rework or verification trouble; low = minor or maintainability. Review was read-only: I read every module, the conftest, and the model, store, service, CLI and hygiene tests plus the README. I did not read `test_todo_ids.py` or `test_todo_format.py`. I ran no tests, because only `git diff` and `git status` are permitted.

| ID | Severity | File / location | Issue |
|---|---|---|---|
| R-1 | medium | all of `docs/todo_app/tests/` | The implementation artifact says that no test, no application run and no `git status` was executed in the implementation phase. Nothing in this review phase can run them either. Every statement below that a test passes is therefore a reading of the code, not an observed result. The verify phase must record real passing output for `.venv/bin/pytest docs/todo_app/tests -q` and for the whole `.venv/bin/pytest -q`. Without it, a PASS cannot be backed. |
| R-2 | medium | `docs/todo_app/tests/test_todo_cli.py:106-110` (`test_negative_id_is_an_error_and_creates_no_file`); `cli.py:36-53` | The plan (T6, F6) asked the implementer to record whether `done -3` is rejected by `InvalidIdError` or by argparse. The implementer did not observe it and only predicts the `InvalidIdError` path. The test is written to pass on either path (non-zero exit, non-empty stderr, no file). By my reading of `build_parser`, neither the top-level parser nor the subparsers define any option that looks like a negative number, so `-3` should be treated as a positional value. I could not confirm this by running it. The clear-message requirement for REQ-10/13/15 is therefore met only if that prediction holds. The verify phase should record the actual stderr text. |
| R-3 | medium | `docs/todo_app/cli.py:77-88` and `tests/test_todo_cli.py` | REQ-4 and REQ-5 for `add` have no behaviour and no test. This is the known, carried-over gap from design review F1 and plan Open Question 1, and it is documented in `README.md` (Assumptions). Without a human answer, REQ-4 is verified only through the `done`/`reopen` no-op messages, and REQ-5 through `done`/`reopen`/`delete`. The implementation did not invent an `add --id` option or a duplicate rule, which is correct. I list it so the human knows the requirement is knowingly only partly met. |
| R-4 | low | `docs/todo_app/store.py:100-111` (`save`) | `tempfile.mkstemp` creates the temporary file with mode 0600, and `os.replace` then gives the data file that mode. A data file that was previously 0644 would become 0600. The implementer disclosed this and left it, since the plan did not cover it. It is harmless for a personal single-user file but is an unplanned behaviour. |
| R-5 | low | `docs/todo_app/store.py:106` | `os.fdopen(fd, ...)` is inside the `try`, but if `fdopen` itself failed, the raw `fd` would not be closed. This is very unlikely. The temporary file is still removed in the `except` branch. |
| R-6 | low | `docs/todo_app/store.py:44` | `self._path.exists()` is called outside any `try`. On some platforms or Python versions a permission error on a parent directory may propagate as a raw `OSError` instead of a `StoreError`, and `main()` catches only `TodoError`, which would show a traceback. The tested cases (directory path, missing parent for save, invalid UTF-8) are handled. |
| R-7 | low | `docs/todo_app/cli.py:56-59` | `--file ""` (an empty string) is silently ignored and falls back to the environment variable or `todo.json`, because `if option:` is false for an empty string. Minor, and not specified in the plan. |
| R-8 | low | `docs/todo_app/service.py:23` | The method `list` shadows the builtin `list` inside the class body. No code in the class body uses the builtin afterwards, so there is no bug today, but it is a maintainability trap if the class is extended. The name came from the plan. |
| R-9 | low | `docs/todo_app/tests/test_todo_hygiene.py:46-57` | The 3.9 check is `ast.parse(feature_version=(3, 9))`, an import allowlist, and a `BitOr`-in-annotation scan. These catch syntax-level drift only. They would not catch use of 3.10+ library APIs (for example `zip(strict=...)` or `int.bit_count`). I read all eight modules for this and found none. This residual risk is accepted and stated in the README. |
| R-10 | low | `git status` / `git diff --stat` (not part of this feature) | The working tree also shows changes outside `docs/todo_app/`: modified `.claude/settings.json`, `.gitignore`, `.mcp.json`, `CLAUDE.md`, `hooks/guard.py`, `orchestrator.py`, `sdlc/phases.json`, `sdlc/state.json`, and untracked `engine/`, `tests/`, `artifacts/` and others. They look like the repository's workflow scaffolding and engine-owned state, and the implementation artifact states it changed nothing outside `docs/todo_app/`. I cannot tell from the diff alone which phase made those edits. The human should confirm that none came from the implementation phase. I report it only because unplanned changes must be reported. No `docs/todo_app/` file adds to it. |
| R-11 | low | `docs/todo_app/README.md`, `store.py` | Plan-accepted residuals, not defects: no file locking, no control-character escaping, no non-UTF-8 terminal handling, empty titles accepted, and application code placed under `docs/` (design-review F10) pending human confirmation. All are documented in the README. |

**Security.** No issue found. Inputs are argv and a local JSON file. The file is parsed with `json` only (no `eval` or `pickle`). Ids are validated with an ASCII-only `re.fullmatch` before the store is touched. Writes are atomic with temporary-file cleanup. The `--file` / `TODO_APP_FILE` override writes with the invoking user's privileges, which was accepted in design review. No secrets, network or third-party packages are involved.

**Correctness (by reading).**
- Ids come from a persisted `next_id` counter, and `delete` leaves it unchanged, so ids are not reused (`service.py:15-21, 38-43`).
- Creation order is preserved by appending to a list and never re-sorting.
- No-ops return before `save`, so there is no write on a no-op or an unknown id.
- Load validation covers every case in the plan list (`store.py:56-89`): bool rejected for `id` and `next_id`, duplicates, bad status, non-string title, `next_id <= max id`, and the non-object top level.
- Exit codes match the plan: 0 for success and no-op, 1 for `TodoError`, and argparse's code (2) for usage errors, returned through `_exit_code`.
- The id is parsed before the store is built (`cli.py:74-75`), so an invalid id never creates a data file.

**Python 3.9 / stdlib check (RR7).** I read all eight modules and found no `match` statement, no `X | Y` annotation, and no 3.10+ API. Imports are limited to `abc`, `argparse`, `dataclasses`, `enum`, `json`, `os`, `pathlib`, `re`, `sys`, `tempfile` and `typing`, plus relative imports. The `# type:` comment style is used for local annotations.

**Test quality (by reading).** The tests are specific and match the plan's acceptance lists. They include byte-identical file checks after no-ops, one parametrized case per invalid-load rule, a failed-`os.replace` test that checks the old content and that no temporary file is left, and a subprocess smoke test that sets `cwd` to `docs/`. The autouse fixture in `conftest.py` (chdir to `tmp_path`, `TODO_APP_FILE` set) properly prevents stray data files. I found no `todo.json` anywhere in the tree and no `__pycache__` under `docs/`, and `.gitignore` ignores `__pycache__/`.

## Task Compliance

| Task | Status | Evidence |
|---|---|---|
| T1 Scaffold, model, errors, harness | compliant | `task.py` has a frozen `Task` and a two-value `Status`. `errors.py` derives `InvalidIdError`, `UnknownIdError` and `StoreError` from `TodoError` and defines a frozen `Outcome`. `__init__.py` exists in `docs/todo_app/` and `docs/todo_app/tests/`, and `docs/__init__.py` is absent (checked by `test_package_layout_markers` and by the file listing). `conftest.py` has the autouse chdir/env fixture. All test files are named `test_todo_*`. |
| T2 Strict id parser | compliant | `ids.py` uses `re.fullmatch(r"[0-9]+")` and requires a value of at least 1. The message is `invalid id '<raw>': must be a positive integer`, as planned. I did not read `test_todo_ids.py`, so its coverage of the planned valid and invalid lists is taken from the implementation artifact. |
| T3 `TaskStore` and `JsonFileStore` | compliant | `store.py` has the abstract class, a missing file giving `([], 1)`, all planned load checks, and save via `mkstemp` + fsync + `os.replace` with cleanup. `test_todo_store.py` has 24 parametrized invalid cases plus the UTF-8, directory, failed-replace and missing-directory tests. Items that were not covered, as extras: R-4, R-5, R-6. |
| T4 `TaskService` | compliant | `service.py` has `add`, `list`, `complete`, `reopen` and `delete`, with no I/O of its own. No-op messages and change messages match the plan. `UnknownIdError` is raised with no save. `test_todo_service.py` uses a save-counting fake store and covers ids, order, no reuse after delete, verbatim titles and duplicates. |
| T5 Formatter | compliant | `formatter.py` renders `<id>  <title>  [<status>]` and `No tasks.` as planned. I did not read `test_todo_format.py`. The CLI tests check the same output end to end. |
| T6 CLI and entry point | partial | `cli.py` and `__main__.py` meet the planned structure: `--file`, five subcommands, precedence, ids parsed before the store, `SystemExit` caught, exit codes 0/1/2, and `--` help text. The CLI tests cover every planned acceptance bullet. It is partial for one reason only: the `done -3` path the plan asked to be recorded was not observed (R-2). |
| T7 Hygiene tests and README | compliant | `test_todo_hygiene.py` implements the `feature_version=(3, 9)` parse, the import allowlist, the `match` ban, the annotation `BitOr` scan, and the README heading check. `README.md` has Run, Test, Assumptions and Limitations, and covers all the planned content, including the REQ-4/REQ-5 note. The planned `git status --short` check after the full suite has not been run (R-1). |

Requirement view: REQ-1 to REQ-3 and REQ-6 to REQ-17 are implemented and tested by reading. REQ-4 is partial and REQ-5 is partial. Both are limited to `done`/`reopen`/`delete` and have no create-specific behaviour, as the plan and README state (R-3). Nothing was added outside the plan inside `docs/todo_app/`.

## Verdict

**ready-to-verify**, with conditions.

Reasons:
- The code matches the plan task by task, is small, stdlib-only, free of 3.10+ syntax, and handles bad input and failed writes without corrupting the data file. I found no critical or high issue.
- Medium findings R-1 and R-2 are verification gaps, not code defects. Both can be closed only by running the tests.

Conditions for the verify phase and the human:
1. Verify must run `.venv/bin/pytest docs/todo_app/tests -q` and `.venv/bin/pytest -q`, and record real output. A PASS needs that output (R-1).
2. Verify should record the actual stderr for `done -3` (R-2) and run `git status --short` to confirm no stray `todo.json` (T7).
3. The human should decide on REQ-4/REQ-5 for `add` (Open Question 1) and on placing the app under `docs/` (F10). The human should also confirm that the out-of-scope working-tree changes in R-10 did not come from the implementation phase.

This verdict is advice only. A human approves or rejects this phase.
