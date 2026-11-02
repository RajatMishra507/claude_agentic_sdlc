## Tasks

All files are under `docs/todo_app/` (the only implementation write path is `docs/`). No existing file is modified. `docs/` itself gets no `__init__.py`. Python 3.9-compatible, stdlib only: use `typing.Optional`/`List`/`Tuple`, no `match`, no `X | Y` annotations.

**Fixed names chosen by this plan (so implementation and verification agree):**
- Run command: `python3 -m todo_app [--file PATH] <subcommand> ...`, run with `docs/` as the working directory or on `PYTHONPATH` (F2). The `--file` option goes before the subcommand.
- Data file: precedence is `--file PATH`, then environment variable `TODO_APP_FILE`, then `todo.json` in the current working directory. The default is not git-ignored, because `.gitignore` is outside the write paths (R6, F4).
- Messages (tests assert these substrings):
  - `add` prints `<id>  <title>  [open]`. `list` prints one `<id>  <title>  [<status>]` line per task (two spaces between fields).
  - Empty list: `No tasks.`
  - `task N marked done`, `task N is already done`, `task N reopened`, `task N is already open`, `task N deleted`.
  - Errors go to stderr: `error: invalid id '<raw>': must be a positive integer` and `error: unknown id N: no such task`.
- Exit codes: success and no-op return 0. `TodoError` (including `StoreError`) returns 1. Argparse usage errors return 2. `main(argv)` catches `SystemExit` from argparse and returns its code, so tests need no `pytest.raises(SystemExit)`.

### T1: Package scaffold, model, errors, test harness
- **Goal:** Create the package and test directory, the `Task`/`Status` model (C1), the errors and `Outcome` (C2), and the conftest that stops any test from touching the repo root (F3, F4).
- **Files:**
  - `docs/todo_app/__init__.py`
  - `docs/todo_app/task.py`
  - `docs/todo_app/errors.py`
  - `docs/todo_app/tests/__init__.py`
  - `docs/todo_app/tests/conftest.py`
  - `docs/todo_app/tests/test_todo_model.py`
- **Details:**
  - `Status` is an `Enum` with `open` and `done`.
  - `Task` is a frozen dataclass (`id: int`, `title: str`, `status: Status`). State changes use `dataclasses.replace` (F9).
  - `errors.py` defines `TodoError`, with `InvalidIdError`, `UnknownIdError` and `StoreError` all deriving from it (F9). It also defines the frozen dataclass `Outcome(changed: bool, message: str)`.
  - The autouse fixture in `conftest.py` does `monkeypatch.chdir(tmp_path)` and `monkeypatch.setenv("TODO_APP_FILE", str(tmp_path / "todo.json"))`.
  - Every test file has a name starting `test_todo_`, so none can collide with the repo's own `tests/` (F3).
- **REQ:** REQ-2, REQ-3, REQ-16, REQ-17 (also provides the exceptions and `Outcome` used for REQ-4, REQ-5, REQ-9, REQ-10, REQ-12, REQ-13, REQ-15)
- **Depends on:** none
- **Acceptance:**
  - `.venv/bin/pytest docs/todo_app/tests/test_todo_model.py -q` passes.
  - Its tests check: `Task` is frozen (assigning an attribute raises `FrozenInstanceError`); `Status` has exactly the values `open` and `done`; the title is kept verbatim, including spaces, unicode and a leading `-`; `InvalidIdError`, `UnknownIdError` and `StoreError` are all subclasses of `TodoError`; `Outcome` is immutable.
  - `docs/todo_app/__init__.py` and `docs/todo_app/tests/__init__.py` exist, and `docs/__init__.py` does not exist.

### T2: Strict id parser (C6)
- **Goal:** Convert a raw id string to a positive `int`, or raise `InvalidIdError` (A5, F6).
- **Files:** `docs/todo_app/ids.py`, `docs/todo_app/tests/test_todo_ids.py`
- **Details:** `parse_id(raw: str) -> int` accepts only a string that fully matches `[0-9]+` (ASCII digits) and has a value of at least 1. Everything else raises `InvalidIdError` with the message `invalid id '<raw>': must be a positive integer`.
- **REQ:** REQ-5, REQ-10, REQ-13, REQ-15
- **Depends on:** T1
- **Acceptance:** `.venv/bin/pytest docs/todo_app/tests/test_todo_ids.py -q` passes.
  - Valid: `"1"`, `"42"`, `"007"` (equals 7).
  - Raises `InvalidIdError`: `""`, `"0"`, `"-3"`, `"+5"`, `" 5"`, `"5 "`, `"1_0"`, `"1.5"`, `"abc"`, `"٣"` (non-ASCII digit).
  - The error message contains the raw value.

### T3: `TaskStore` interface and `JsonFileStore` (C3, C4)
- **Goal:** Replaceable persistence with atomic writes and a validated load (F5).
- **Files:** `docs/todo_app/store.py`, `docs/todo_app/tests/test_todo_store.py`
- **Details:**
  - `TaskStore` is an abstract class with `load() -> Tuple[List[Task], int]` and `save(tasks, next_id) -> None`.
  - `JsonFileStore(path)` stores UTF-8 JSON `{"next_id": n, "tasks": [{"id", "title", "status"}, ...]}` in list (creation) order.
  - A missing file loads as `([], 1)`.
  - `save` writes a temporary file in the same directory (write, flush, fsync), then `os.replace`. On any failure it removes the temporary file and raises `StoreError`, leaving the previous file intact.
  - `load` raises `StoreError` with a message that names the file for each of the following:
    - invalid JSON or an empty file;
    - a top level that is not an object, or missing `next_id`/`tasks`;
    - `tasks` not a list, or an entry not an object;
    - `id` not an `int`, `bool` rejected, or less than 1;
    - duplicate ids;
    - `status` not `open` or `done`;
    - `title` not a `str`;
    - `next_id` not an `int` (`bool` rejected), or `next_id` less than or equal to the largest stored id, or less than 1;
    - an unreadable file (for example a directory path).
  - Parsing uses `json` only.
- **REQ:** REQ-1, REQ-2, REQ-6, REQ-16, REQ-17
- **Depends on:** T1
- **Acceptance:** `.venv/bin/pytest docs/todo_app/tests/test_todo_store.py -q` passes. All paths come from `tmp_path`.
  - Save then load returns equal tasks in the same order, and `next_id` is preserved.
  - Missing file gives `([], 1)`.
  - One test per invalid-load case above raises `StoreError`.
  - The file keeps unicode and newline titles exactly.
  - When `os.replace` is monkeypatched to raise, `StoreError` is raised, the old file content is unchanged and no `*.tmp` leftover remains in the directory.
  - Saving into a missing parent directory raises `StoreError`.

### T4: `TaskService` (C5)
- **Goal:** All rules, no I/O of its own.
- **Files:** `docs/todo_app/service.py`, `docs/todo_app/tests/test_todo_service.py`
- **Details:**
  - `TaskService(store)` has `add(title) -> Task`, `list() -> List[Task]`, `complete(id) -> Outcome`, `reopen(id) -> Outcome` and `delete(id) -> Outcome`.
  - `add` takes the id from `next_id`, increments it, appends an `open` task, saves and returns it. The title is stored verbatim, with no length or content rules (REQ-16, Open Question 5).
  - `complete`, `reopen` and `delete` raise `UnknownIdError` for an absent id and save nothing.
  - A no-op returns `Outcome(False, ...)` and saves nothing.
  - A change saves and returns `Outcome(True, ...)`.
  - `delete` leaves `next_id` unchanged.
  - Messages are those in the Tasks preamble.
- **REQ:** REQ-2, REQ-3, REQ-4 (no-op `Outcome` mechanism only; see Open Questions), REQ-5 (unknown id), REQ-6, REQ-8, REQ-9, REQ-10, REQ-11, REQ-12, REQ-13, REQ-14, REQ-15, REQ-16
- **Depends on:** T1, T3 (interface only; tests use an in-memory fake `TaskStore` that counts `save` calls)
- **Acceptance:** `.venv/bin/pytest docs/todo_app/tests/test_todo_service.py -q` passes.
  - Two adds get ids 1 and 2, both `open`, and `list()` returns them in creation order.
  - After deleting the last task, the next add does not reuse its id.
  - `complete` on an open task gives `done` with `changed=True` and one save. `complete` on a done task gives `changed=False`, message `task N is already done`, and no save.
  - `reopen` mirrors `complete`.
  - `delete` removes the task, saves once, and leaves `next_id` unchanged.
  - `complete`, `reopen` and `delete` with an unknown id raise `UnknownIdError` and cause no save.
  - A title with a leading `-`, unicode, or a newline is stored verbatim.
  - Adding the same title twice gives two tasks (the service has no create-time duplicate rule; see Open Questions 1).

### T5: Formatter (C7)
- **Goal:** Pure rendering of a task and of the empty list, one format for create and list.
- **Files:** `docs/todo_app/formatter.py`, `docs/todo_app/tests/test_todo_format.py`
- **Details:** `format_task(task) -> str` returns `<id>  <title>  [<status>]`. `format_list(tasks) -> str` returns `No tasks.` for an empty list, otherwise the task lines joined with `\n`. It does not escape control characters (R5, F8 are accepted residuals).
- **REQ:** REQ-3, REQ-7
- **Depends on:** T1
- **Acceptance:** `.venv/bin/pytest docs/todo_app/tests/test_todo_format.py -q` passes.
  - `format_task(Task(1, "Buy milk", Status.OPEN))` equals `1  Buy milk  [open]`.
  - A done task shows `[done]`.
  - `format_list([])` equals `No tasks.`
  - Two tasks render in input order, one per line.

### T6: CLI and entry point (C8)
- **Goal:** Wire everything into `python3 -m todo_app` with `argparse` subcommands (A3, A4).
- **Files:** `docs/todo_app/cli.py`, `docs/todo_app/__main__.py`, `docs/todo_app/tests/test_todo_cli.py`
- **Details:**
  - `main(argv=None) -> int`. Global option `--file PATH`. Subcommands: `add TITLE`, `list`, `done ID`, `reopen ID`, `delete ID`. ID arguments are plain `str`, parsed by `parse_id` (T2).
  - The data file path follows the precedence in the preamble. The store is built only after the id has been parsed, so an invalid id never touches the store.
  - `Outcome` and results go to stdout with exit 0. `TodoError` goes to stderr as `error: <message>` with exit 1. `SystemExit` from argparse is caught and its code returned.
  - `__main__.py` is `sys.exit(main())`.
  - The `--help` text mentions `--` for titles that start with `-` (F7).
- **REQ:** REQ-1, REQ-3, REQ-4 (no-op messages for done/reopen), REQ-5, REQ-7, REQ-9, REQ-10, REQ-12, REQ-13, REQ-15, REQ-17 (also exercises REQ-2, REQ-6, REQ-8, REQ-11, REQ-14, REQ-16 end to end)
- **Depends on:** T2, T3, T4, T5
- **Acceptance:** `.venv/bin/pytest docs/todo_app/tests/test_todo_cli.py -q` passes. Every test passes `--file` with a `tmp_path` path or relies on the T1 autouse fixture, and none writes a data file outside `tmp_path`.
  - `add "Buy milk"` returns 0 and prints a line with id `1`, `Buy milk` and `[open]`.
  - `list` after two adds prints both in creation order. On an empty store it prints `No tasks.` and returns 0.
  - Full cycle: `done 1` prints `marked done`; a second `done 1` prints `already done` and returns 0, and the file is byte-identical before and after it; `reopen 1` prints `reopened`; a second `reopen 1` prints `already open` and returns 0; `delete 1` prints `deleted`; `list` then prints `No tasks.`
  - `done 99`, `reopen 99` and `delete 99` each return 1 with `unknown id 99` on stderr, empty stdout, and the data file unchanged.
  - `done abc`, `done 0`, `done 1.5`, `done +5`, `reopen abc` and `delete abc` each return non-zero with `invalid id` on stderr, and no data file is created.
  - `done -3` returns non-zero with a non-empty stderr and no data file created. The implementer records in `implementation.md` whether the message came from `InvalidIdError` or from argparse (F6).
  - `add -- -draft` stores the title `-draft`.
  - Missing subcommand or missing argument returns 2.
  - A corrupt data file gives return 1 and `error:` on stderr, with the file unchanged.
  - With `TODO_APP_FILE` unset and no `--file`, the data file is created as `todo.json` in the current directory, which is `tmp_path` via the autouse fixture. With `--file` set, `--file` wins over `TODO_APP_FILE`.
  - One subprocess smoke test runs `[sys.executable, "-m", "todo_app", "--file", <tmp file>, "add", "x"]` with `cwd` set to the `docs/` directory (`Path(__file__).resolve().parents[2]`). It expects exit 0, `[open]` in stdout, and the file created.

### T7: Compatibility and hygiene tests, README
- **Goal:** Check the REQ-17 constraints and the Python 3.9 and stdlib-only rules mechanically, and document how to run, test and what is assumed (F2, F3, F4, F7, F8, RR7).
- **Files:** `docs/todo_app/tests/test_todo_hygiene.py`, `docs/todo_app/README.md`
- **Details:**
  - The hygiene test parses every non-test `docs/todo_app/*.py` file with `ast.parse(..., feature_version=(3, 9))`.
  - It checks that top-level imports are limited to `__future__`, `abc`, `argparse`, `dataclasses`, `enum`, `json`, `os`, `pathlib`, `re`, `sys`, `tempfile`, `typing`, or relative imports of the package.
  - It checks that no annotation contains a `X | Y` (`BitOr`) expression.
  - The README states: the run command and working directory (`cd docs && python3 -m todo_app ...`), the data-file precedence and default, the test command, the assumptions A1-A5, that `add -- -title` is needed for titles starting with `-`, and the accepted limitations (no file locking, control characters and non-UTF-8 terminals not handled, empty titles accepted). It also states that REQ-4 and REQ-5 have no create-specific behaviour pending Open Question 1.
- **REQ:** REQ-17 (also REQ-1, REQ-4, REQ-5 documentation of scope)
- **Depends on:** T1, T2, T3, T4, T5, T6
- **Acceptance:**
  - `.venv/bin/pytest docs/todo_app/tests/test_todo_hygiene.py -q` passes.
  - `docs/todo_app/README.md` exists and contains the headings `Run`, `Test`, `Assumptions` and `Limitations`.
  - `git status --short` after the full suite shows changes only under `docs/todo_app/`, with no stray `todo.json` anywhere.

### Requirement-to-task coverage

| REQ | Tasks | Note |
|---|---|---|
| REQ-1 | T3, T6, T7 | Depends on assumption A1 (persistence). |
| REQ-2 | T1, T3, T4 | |
| REQ-3 | T1, T4, T5, T6 | |
| REQ-4 | T1, T4, T6, T7 | Partial: no-op message verified for done/reopen only. No create-specific behaviour until Q1 is answered. |
| REQ-5 | T1, T2, T4, T6, T7 | Partial: verified for done/reopen/delete only. Nothing for create until Q1 is answered. |
| REQ-6 | T3, T4, T6 | |
| REQ-7 | T5, T6 | |
| REQ-8 | T4, T6 | |
| REQ-9 | T4, T6 | |
| REQ-10 | T2, T4, T6 | |
| REQ-11 | T4, T6 | |
| REQ-12 | T4, T6 | |
| REQ-13 | T2, T4, T6 | |
| REQ-14 | T4, T6 | |
| REQ-15 | T2, T4, T6 | |
| REQ-16 | T1, T3, T4, T6 | |
| REQ-17 | T1, T3, T5, T6, T7 | |

### Design-review items and where the plan handles them

| Item | Handled in |
|---|---|
| F1 (REQ-4/REQ-5 for create) | Not resolved by this plan. See Open Questions 1 and the REQ-4/REQ-5 rows above. |
| F2 (run command) | Tasks preamble, T6 subprocess smoke test, T7 README |
| F3 (test layout and collection) | T1 (`__init__.py` chain, unique `test_todo_*` names), Test Strategy |
| F4 (stray data file) | Autouse fixture in T1, T6 tests, T7 `git status` check |
| F5 (load invariants) | T3 |
| F6 (strict id rule) | T2, T6 |
| F7 (leading dash) | T4, T6, T7 |
| F8 (output encoding) | Accepted residual, documented in T7 |
| F9 (`StoreError` home, frozen dataclass) | T1 |
| F10 (placement under `docs/`) | Needs human confirmation; see Open Questions 2 |

## Sequencing

1. **T1** first. It creates the package, the test harness and the shared types.
2. **T2, T3 and T5** can then run in any order. They depend only on T1.
3. **T4** needs T1 and the `TaskStore` interface from T3. Its tests use a fake store, so it does not need `JsonFileStore` to work.
4. **T6** needs T2, T3, T4 and T5.
5. **T7** is last, because it scans all modules and documents the final behaviour.

A suggested linear order is T1, T2, T3, T5, T4, T6, T7. After each task, its own test file must pass before the next starts. Before T7 is marked complete, run the full suite once.

## Test Strategy

**Layout (F3).** The tests live in `docs/todo_app/tests/`. Both `docs/todo_app/__init__.py` and `docs/todo_app/tests/__init__.py` exist, and `docs/` has no `__init__.py`. With pytest's default import mode, `docs/` goes on `sys.path` and `import todo_app` works. Test files are named `test_todo_*.py`, so their names cannot clash with the repo's own `tests/`. The repo's `tests/conftest.py` applies only to `tests/` and is not relied on.

**Commands for the Verify Agent** (all allowed by the verify allowlist in `sdlc/phases.json`):
- `.venv/bin/pytest docs/todo_app/tests -q` runs the new tests alone.
- `.venv/bin/pytest -q` runs the whole repository, to prove the new tests are collected next to the existing engine tests and that nothing existing broke.
- `python3 -m pytest docs/todo_app/tests -q` is an alternative runner check.
- `git status --short` and `git diff --stat` confirm that only files under `docs/todo_app/` changed and that no data file such as `todo.json` was created in the repository.

**Isolation (F4).** An autouse fixture changes the working directory to `tmp_path` and points `TODO_APP_FILE` at a file there. Every CLI test therefore writes only under `tmp_path`.

**Levels.** Service rules are tested against a fake in-memory store. The store is tested with `tmp_path`, including every invalid-load case. The CLI is tested in process through `main(argv)` with `capsys` for stdout, stderr and exit codes. One subprocess smoke test confirms that `python3 -m todo_app` works from `docs/`. The verify allowlist cannot run the app directly, so these pytest runs are the only runtime evidence.

**What is not verified:**
- Python 3.9 itself. `.venv` is 3.14. The `feature_version=(3, 9)` parse and the annotation scan in T7 are partial checks only. The Review Agent should also read the code for 3.10+ features (RR7).
- Concurrent use (R4) and non-UTF-8 terminals (F8).
- REQ-4 and REQ-5 for `add`, which depend on Open Question 1.

## Rollback

- Every task only adds new files under `docs/todo_app/`. No existing file is changed, and nothing outside `docs/` is touched. Nothing needs migrating.
- To undo the whole feature, a human removes the `docs/todo_app/` directory, or uses `reopen implementation` so the engine archives the phase and its downstream artifacts. Agents must not run destructive git commands, and this plan does not ask for any.
- To undo one task, remove only that task's files. T1 is the base for all the others, so removing T1 means removing every task. Dependent tasks must be removed first, in the reverse of the Sequencing order.
- A `todo.json` or other data file made by someone running the app by hand is user data, is not tracked by the plan, and is not part of the rollback.
- If the human decides the application must not live under `docs/` (Open Questions 2), the output of this plan is discarded and the design is revisited. Moving the files would then need a different `write_paths`, which this plan does not change.

## Open Questions

1. **Open Question 1 from requirements (design-review condition 1).** What do "repeating a no-op" and "invalid or unknown id" mean for create (REQ-4, REQ-5)? This plan implements only the shared no-op and id-error handling for `done`, `reopen` and `delete`, and plans no `add --id` or duplicate-detection behaviour. Please either answer the question (the plan is then amended before implementation) or record that REQ-4 and REQ-5 are limited to the id-taking commands. Until then REQ-4 is only partly verifiable and REQ-5 is verified for done, reopen and delete.
2. **Placement under `docs/` (design-review condition 3, F10).** Please confirm that putting the application and its tests under `docs/todo_app/` is acceptable, given that `sdlc/config.json` describes this repository as Automated Documentation Sync and `sdlc/phases.json` limits implementation to `docs/`.
3. Please confirm the assumptions that the plan builds on: persistence in a local JSON file (A1; Open Question 2), sequential integer ids (A2; Open Question 4), subcommands add/list/done/reopen/delete (A3; Open Question 3), `list` showing id, title and status (A4; Open Question 6), and the strict positive-integer id rule (A5).
4. Names chosen by the plan, not by the requirements: environment variable `TODO_APP_FILE`, default file `todo.json` in the working directory, and the exact message wording. Say if any must change.
5. Open Question 5 (title rules) is unanswered. Empty and very long titles are stored as given, and the README will say so.
