## Changes

All changes are new files under `docs/todo_app/`. No existing file was modified, and nothing outside `docs/` was touched. `docs/__init__.py` was not created.

Application modules:
- `docs/todo_app/__init__.py`: package marker.
- `docs/todo_app/task.py`: `Status` enum (`open`, `done`) and the frozen dataclass `Task(id, title, status)`.
- `docs/todo_app/errors.py`: `TodoError` with `InvalidIdError`, `UnknownIdError` and `StoreError` deriving from it, and the frozen dataclass `Outcome(changed, message)`.
- `docs/todo_app/ids.py`: `parse_id(raw)`. It accepts only a full match of ASCII `[0-9]+` with a value of at least 1. Otherwise it raises `InvalidIdError("invalid id '<raw>': must be a positive integer")`.
- `docs/todo_app/store.py`: abstract `TaskStore` (`load`, `save`) and `JsonFileStore`. A missing file loads as `([], 1)`. `load` validates the file and raises `StoreError` naming the file for: unreadable file or invalid UTF-8, invalid or empty JSON, a non-object top level, missing `next_id`/`tasks`, `tasks` not a list, an entry not an object, a bad `id` (not int, bool, below 1, missing), duplicate ids, a bad `status`, a non-string `title`, a bad `next_id` (not int, bool, below 1), and `next_id` less than or equal to the largest id. `save` writes a temporary file in the same directory (write, flush, fsync) and then calls `os.replace`. On failure it removes the temporary file and raises `StoreError`.
- `docs/todo_app/service.py`: `TaskService` with `add`, `list`, `complete`, `reopen` and `delete`. It does no I/O of its own. A no-op returns `Outcome(False, ...)` and does not save. A change saves and returns `Outcome(True, ...)`. An absent id raises `UnknownIdError("unknown id N: no such task")`. `delete` leaves `next_id` unchanged. Titles are stored verbatim.
- `docs/todo_app/formatter.py`: `format_task` renders `<id>  <title>  [<status>]`. `format_list` renders `No tasks.` for an empty list.
- `docs/todo_app/cli.py`: `main(argv=None) -> int` with the global `--file PATH` option and the subcommands `add TITLE`, `list`, `done ID`, `reopen ID` and `delete ID`. Data file precedence is `--file`, then `TODO_APP_FILE`, then `todo.json` in the current directory. The id is parsed before the store is built. Success and no-op messages go to stdout with exit 0. `TodoError` goes to stderr as `error: <message>` with exit 1. `SystemExit` from argparse is caught and its code returned (2 for usage errors). Help text mentions `--` for titles starting with `-`.
- `docs/todo_app/__main__.py`: `sys.exit(main())`.

Tests, all named `test_todo_*.py`:
- `docs/todo_app/tests/__init__.py` (empty) and `docs/todo_app/tests/conftest.py`. The conftest has an autouse fixture that does `monkeypatch.chdir(tmp_path)` and sets `TODO_APP_FILE` to `tmp_path/todo.json`. It also has a `data_file` fixture.
- `test_todo_model.py`: frozen `Task`, status values, verbatim titles, error hierarchy, immutable `Outcome`, and the layout markers (`docs/__init__.py` absent).
- `test_todo_ids.py`: the valid and invalid id lists from the plan.
- `test_todo_store.py`: round trip, missing file, unicode and newline titles, file shape, one test per invalid-load case, invalid UTF-8, a directory path, a failed `os.replace` (old file unchanged, no temporary file left) and a save into a missing directory.
- `test_todo_service.py`: uses an in-memory fake store that counts saves. It covers sequential ids, creation order, no id reuse after delete, verbatim titles, duplicate titles, changes and no-ops for complete and reopen, delete, and unknown ids with no save.
- `test_todo_format.py`: the format and empty-list cases.
- `test_todo_cli.py`: in-process tests through `main(argv)` with `capsys`. They cover the full cycle (including byte-identical files after no-ops), unknown ids, invalid ids with no data file created, `done -3`, `add -- -draft`, `add --help`, usage errors returning 2, a corrupt file, file precedence (default, environment variable, `--file` over the environment variable), and one subprocess smoke test of `python -m todo_app` with `cwd` set to `docs/`.
- `test_todo_hygiene.py`: parses each non-test module with `ast.parse(feature_version=(3, 9))`, limits imports to the allowed stdlib list, forbids `match` and `X | Y` annotations, and checks the README headings.

Documentation:
- `docs/todo_app/README.md` with the headings Run, Test, Assumptions and Limitations. It states the run command and working directory, the data-file precedence, the test command, assumptions A1-A5, the names chosen by the plan, the `--` rule for titles starting with `-`, and the limitations (no locking, no control-character escaping, no non-UTF-8 terminal handling, empty titles accepted). It states that REQ-4 and REQ-5 have no create-specific behaviour pending Open Question 1.

Not verified in this phase: I had no shell, so I did not run pytest, the application or `git status`. The acceptance commands in the plan (for example `.venv/bin/pytest docs/todo_app/tests -q`) have not been run.

F6 note, as the plan asked: for `done -3` I did not observe the outcome. From the argparse behaviour I expect that `-3` is treated as a positional value, because the parser defines no option that looks like a negative number. If so, the message comes from `InvalidIdError` (`error: invalid id '-3': ...`, exit 1). The test only asserts a non-zero exit, non-empty stderr and no data file, so it passes whichever path is taken. The actual path needs checking when the tests are run.

## Rationale

- Layout and imports (F2, F3). The package is under `docs/` because `sdlc/phases.json` limits implementation to `docs/`. `__init__.py` files exist in `docs/todo_app/` and `docs/todo_app/tests/` but not in `docs/`. Under pytest's default import mode, `docs/` is then put on `sys.path` and `import todo_app` works. Test files are named `test_todo_*.py` to avoid clashing with the repo's own `tests/`. Modules use relative imports so `python3 -m todo_app` works from `docs/`.
- Test isolation (F4). The autouse fixture moves each test into `tmp_path` and points `TODO_APP_FILE` there, so no test writes a data file in the repository. The subprocess smoke test passes `--file` and sets `PYTHONDONTWRITEBYTECODE=1`.
- Load invariants (F5). `JsonFileStore.load` checks that ids are unique integers (not bool), that the status is valid, that titles are strings, and that `next_id` is greater than every stored id. A damaged file therefore gives a `StoreError` instead of silently breaking id uniqueness or ordering.
- Strict id rule (F6). `parse_id` uses `re.fullmatch` on `[0-9]+`. That rejects signs, spaces, a trailing newline, underscores, decimals and non-ASCII digits, which plain `int()` would accept.
- Frozen model and error home (F9). `Task` and `Outcome` are frozen dataclasses and state changes use `dataclasses.replace`. `StoreError` derives from `TodoError` and lives in `errors.py`, so the CLI catches one base class.
- Python 3.9 and stdlib only (REQ-17, RR7). Annotations use `typing.List` and `Optional`. There is no `match` and no `X | Y` annotation. The hygiene test checks this mechanically. This is a partial check only, because the venv is Python 3.14.
- REQ-4 and REQ-5 for `add` (F1). The plan did not resolve Open Question 1, so I added no `add --id` option, duplicate-title rule or other create-specific behaviour. No-op messages are implemented for `done` and `reopen`, and invalid and unknown id errors for `done`, `reopen` and `delete`. The README says this.
- Residual items accepted by the plan and recorded in the README: no file locking (R4), no control-character escaping or terminal-encoding handling (R5, F8), and empty titles accepted (Open Question 5).
- `save` creates the temporary file with the `mkstemp` default mode (0600), so a replaced data file takes that mode. The plan did not cover this. I left it as is.

## Task Mapping

| Task | Files that satisfy it |
|---|---|
| T1: scaffold, model, errors, harness | `docs/todo_app/__init__.py`, `docs/todo_app/task.py`, `docs/todo_app/errors.py`, `docs/todo_app/tests/__init__.py`, `docs/todo_app/tests/conftest.py`, `docs/todo_app/tests/test_todo_model.py` |
| T2: strict id parser | `docs/todo_app/ids.py`, `docs/todo_app/tests/test_todo_ids.py` |
| T3: `TaskStore` and `JsonFileStore` | `docs/todo_app/store.py`, `docs/todo_app/tests/test_todo_store.py` |
| T4: `TaskService` | `docs/todo_app/service.py`, `docs/todo_app/tests/test_todo_service.py` |
| T5: formatter | `docs/todo_app/formatter.py`, `docs/todo_app/tests/test_todo_format.py` |
| T6: CLI and entry point | `docs/todo_app/cli.py`, `docs/todo_app/__main__.py`, `docs/todo_app/tests/test_todo_cli.py` |
| T7: hygiene tests and README | `docs/todo_app/tests/test_todo_hygiene.py`, `docs/todo_app/README.md` |

Partial coverage carried over from the plan: REQ-4 and REQ-5 have no create-specific behaviour, pending Open Question 1.
