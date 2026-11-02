## Context

**Problem.** Build a small Python command-line application that lets a user manage a simple task list: create, view, complete, reopen and delete tasks (REQ-1, REQ-17). Each task has a unique id, a free-text title and a status of `open` or `done` (REQ-2, REQ-3, REQ-16). Missing or unknown ids and repeated state changes give clear messages (REQ-4, REQ-5, REQ-9, REQ-10, REQ-12, REQ-13, REQ-15).

**Repository facts (inspected).**
- The repository is the SDLC workflow engine (`orchestrator.py`, `engine/`, `hooks/`, `tests/`). There is no existing to-do application code to extend. `docs/` currently holds only `docs/codemie/analytics/*.json`.
- `sdlc/phases.json` limits the implementation phase to `write_paths: ["docs/"]`. `hooks/guard.py` (around line 316) denies writes outside those paths. `engine/validators.py` (around line 186) rejects changed files outside them. Any application code produced by this pipeline therefore has to live under `docs/`. `sdlc/config.json` `doc_sync.target_paths` also lists only `docs/`.
- `CLAUDE.md` says runtime code is Python 3.9+ compatible and standard-library only, and tests use pytest (`.venv/bin/pytest`). The `.venv` uses Python 3.14. I found no `pytest.ini`, `pyproject.toml` or `setup.cfg`, so pytest uses default discovery from the repository root.
- `github_repo` in `sdlc/config.json` is empty. This is a later-phase concern and is not designed here.

**Constraints.**
- Python only, small, no third-party runtime dependencies (REQ-17, CLAUDE.md conventions).
- Code is confined to `docs/` (see above).
- The requirements do not specify persistence, CLI syntax, id format, title validation or what "no-op" and "id" mean for create (Requirements Open Questions 1-6). Where the design needs one of these, it states an **Assumption (A#)** and lists the matching question. Each assumption is isolated behind one component, so changing it does not change the others.

**Assumptions.**
- A1: The task list persists between runs in a local JSON file. REQ-1 describes a command-line task list, which would be unusable across invocations without persistence. The requirements do not state this (Open Question 2).
- A2: Ids are positive integers assigned sequentially and never reused (Open Question 4).
- A3: The CLI uses subcommands `add`, `list`, `done`, `reopen`, `delete` (Open Question 3).
- A4: `list` shows id, title and status for every task (Open Question 6).
- A5: "Invalid id" means a value that is not a positive integer. "Unknown id" means a well-formed id with no matching task (Open Question 4).

## Components

All components live in one package, proposed as `docs/todo_app/` (the path is forced by the `docs/`-only write constraint). The names below are logical and are not a claim that the files exist.

| # | Component | Responsibility | Depends on | REQ ids |
|---|---|---|---|---|
| C1 | `task` model (`Task`, `Status`) | Immutable-style record of `id: int`, `title: str`, `status: Status` (`open`/`done`). It is the only place the status vocabulary is defined. | stdlib `dataclasses`, `enum` | REQ-2, REQ-3, REQ-16 |
| C2 | `errors` + `Outcome` | Domain exceptions `InvalidIdError` and `UnknownIdError` (both derive from `TodoError`). A small `Outcome` value (`changed: bool`, `message: str`) lets the service report a state change or a no-op without raising. | none | REQ-4, REQ-5, REQ-9, REQ-10, REQ-12, REQ-13, REQ-15 |
| C3 | `TaskStore` interface | Abstract load/save contract: `load() -> (tasks, next_id)` and `save(tasks, next_id)`. It keeps persistence replaceable and keeps the service free of file I/O. | C1 | REQ-1, REQ-6 |
| C4 | `JsonFileStore` (implements C3) | Persists `{"next_id": n, "tasks": [{id, title, status}, ...]}` as UTF-8 JSON. List order is creation order. Writes go to a temporary file in the same directory, then `os.replace`. A missing file means an empty list. A corrupt or unreadable file raises a clear `StoreError`. The path defaults to a file in the current working directory and can be overridden by a `--file` option or an environment variable (A1). | C3, stdlib `json`, `os`, `pathlib` | REQ-1, REQ-2, REQ-6, REQ-16, REQ-17 |
| C5 | `TaskService` | Holds all rules and has no I/O of its own. `add(title)` assigns `next_id`, increments it, appends an `open` task and returns it. `list()` returns the tasks in stored (creation) order. `complete(id)`, `reopen(id)` and `delete(id)` look the task up. They raise `UnknownIdError` if it is absent, return a no-op `Outcome` if the task is already in the target state, and otherwise change state and return a changed `Outcome`. Titles are stored verbatim (A-title below). | C1, C2, C3 | REQ-2, REQ-3, REQ-6, REQ-8, REQ-9, REQ-10, REQ-11, REQ-12, REQ-13, REQ-14, REQ-15, REQ-16 |
| C6 | `id parser` | Converts the raw CLI id string to a positive `int`. It raises `InvalidIdError` for anything else (A5). It is used by every subcommand that takes an id. | C2 | REQ-5, REQ-10, REQ-13, REQ-15 |
| C7 | `formatter` | Pure functions that render a task as `<id>  <title>  [<status>]` and render the empty-list message (for example `No tasks.`). One format is used for create and list. | C1 | REQ-3, REQ-7 |
| C8 | `cli` (`main(argv) -> int`) and `__main__` entry | Uses `argparse` with subcommands `add TITLE`, `list`, `done ID`, `reopen ID`, `delete ID` (A3). It wires C4 into C5, calls the service, and prints the formatter output or the `Outcome`/error message. Successes and no-ops print to stdout and exit 0. `TodoError`/`StoreError` print to stderr and exit non-zero. It is run as `python3 -m todo_app`. | C5, C6, C7, C4, stdlib `argparse`, `sys` | REQ-1, REQ-3, REQ-4, REQ-5, REQ-7, REQ-9, REQ-10, REQ-12, REQ-13, REQ-15, REQ-17 |
| C9 | Unit and CLI tests | pytest tests for the service (using an in-memory fake `TaskStore`), the store (using `tmp_path`) and the CLI (calling `main([...])` and checking `capsys` and exit codes). The test location is an open question (see Risks R2). | pytest (already the repo test runner) | Verifies REQ-1 to REQ-17 |

**REQ coverage matrix.**

| REQ | Components |
|---|---|
| REQ-1 | C3, C4, C8 |
| REQ-2 | C1, C4, C5 |
| REQ-3 | C1, C5, C7, C8 |
| REQ-4 | C2, C5, C8 (meaning unresolved, see Decision D6) |
| REQ-5 | C2, C6, C8 (meaning unresolved, see Decision D6) |
| REQ-6 | C3, C4, C5 |
| REQ-7 | C7, C8 |
| REQ-8 | C5 |
| REQ-9 | C2, C5, C8 |
| REQ-10 | C2, C5, C6, C8 |
| REQ-11 | C5 |
| REQ-12 | C2, C5, C8 |
| REQ-13 | C2, C5, C6, C8 |
| REQ-14 | C5 |
| REQ-15 | C2, C5, C6, C8 |
| REQ-16 | C1, C4, C5 |
| REQ-17 | C4, C8 (stdlib-only package) |

**Title handling (A-title).** The service and store keep the title string exactly as given and add no length or content rules (REQ-16). The CLI requires that a title argument be supplied. Whether empty or very long titles must be rejected is Open Question 5. If a rule is needed, it is added in one place, `TaskService.add`.

**Security and trust boundaries.** The only external inputs are command-line arguments and the JSON data file. The id parser validates ids before use. The store parses the file with `json` only (no `eval`, no `pickle`) and checks the schema on load, so a malformed file gives a `StoreError` and is never treated as code. No network, secrets or third-party packages are involved.

## Data Flow

**Common path.**
1. The user runs `python3 -m todo_app <subcommand> [args]`.
2. C8 parses the arguments. Unknown subcommands or a missing required argument make `argparse` print usage and exit non-zero.
3. For commands that take an id, C6 converts it. A non-integer or non-positive value raises `InvalidIdError` (REQ-5, REQ-10, REQ-13, REQ-15). The error goes to stderr and the exit code is non-zero. The store is not touched.
4. C8 builds `TaskService(JsonFileStore(path))`. The service calls `store.load()`.
5. The service applies the operation (below).
6. If the state changed, the service calls `store.save()`. Saving is atomic: temporary file, then `os.replace`. No-ops and errors never save.
7. C8 prints the result via C7 or the `Outcome` message and returns the exit code.

**Per-operation flow.**
- **add TITLE** (REQ-2, REQ-3, REQ-16): the service takes `id = next_id`, sets `next_id += 1`, appends `Task(id, title, open)` and saves. It prints the task's id, title and status. Ids are never reused, so uniqueness holds even after deletes (A2).
- **list** (REQ-6, REQ-7): the service returns the tasks in stored order, which is creation order. If the list is empty, C7 prints the empty-list message. Otherwise it prints one line per task with id, title and status (A4).
- **done ID** (REQ-8, REQ-9, REQ-10): if the id is not found, `UnknownIdError` is raised, nothing is saved and the exit code is non-zero. If the status is already `done`, it returns a no-op `Outcome` ("task N is already done"), saves nothing and exits 0. If the status is `open`, it sets `done`, saves and prints confirmation.
- **reopen ID** (REQ-11, REQ-12, REQ-13): the mirror of `done`, with statuses swapped.
- **delete ID** (REQ-14, REQ-15): if the id is not found, `UnknownIdError` is raised and nothing changes. Otherwise the task is removed, the store is saved and a confirmation is printed. `next_id` is left unchanged.

**Failure paths.**
- Invalid id: `InvalidIdError`, stderr, non-zero exit, no state change.
- Unknown id: `UnknownIdError`, stderr, non-zero exit, no state change.
- Missing data file: treated as an empty list, with no error.
- Corrupt, unreadable or unwritable data file: `StoreError` with a clear message, non-zero exit. Because of the atomic replace, a failed save leaves the previous file intact.
- No-op (already done or already open): message on stdout, exit 0, no write.

## Decisions

**D1. Single package of small modules, with a service layer separate from the CLI and the store.** (REQ-1, REQ-17, all behaviour REQs)
- Alternatives: (a) one script file; (b) a class-based app mixing CLI, rules and storage.
- Rationale: this keeps each module small and single-purpose, as the repository conventions ask. It lets the rules (no-op, unknown id, ordering) be tested without a filesystem or `argparse`. The extra structure is only a few small modules, so it does not conflict with the "small application" requirement.

**D2. Place the application under `docs/todo_app/`.** (REQ-17)
- Alternatives: (a) a top-level `todo_app/` or `src/` package; (b) add to `engine/`.
- Rationale: `sdlc/phases.json` limits the implementation phase to `docs/` and `hooks/guard.py` enforces it. A top-level package would be blocked, and `engine/` is the workflow engine and not part of this feature. Changing `write_paths` would mean editing `sdlc/phases.json`, which this design does not do (see Q-A). The cost is that application code lives in a directory that otherwise holds documentation.

**D3. Persist to a local JSON file behind a `TaskStore` interface (A1).** (REQ-1, REQ-2, REQ-6, REQ-17)
- Alternatives: (a) in-memory only, where the list is lost when the process exits; (b) SQLite (`sqlite3`, stdlib); (c) CSV or plain text.
- Rationale: a CLI that forgets everything on exit cannot "manage a list" across commands. JSON is human-readable, stdlib-only and keeps order naturally. SQLite would be more than a small app needs. The interface means a different backend can be swapped in if Open Question 2 is answered differently. Persistence itself is an assumption, not a stated requirement.

**D4. Sequential integer ids from a persisted `next_id` counter, never reused (A2).** (REQ-2)
- Alternatives: (a) `max(id)+1`, which reuses an id after the highest task is deleted; (b) UUIDs.
- Rationale: a counter guarantees uniqueness over the life of the list. Short integers are easy to type on the command line. UUIDs are awkward to type and are not needed. Open Question 4 may override this.

**D5. Use creation order as storage order, with no sort key.** (REQ-6)
- Alternatives: (a) store a `created_at` timestamp and sort; (b) sort by id.
- Rationale: appending to a list and never reordering it already gives creation order and needs no clock. Because ids only grow, sorting by id would give the same result, so a timestamp would add nothing.

**D6. Handle the create "no-op / invalid or unknown id" criterion (REQ-4, REQ-5) with the shared outcome and error mechanism, and do not invent a create-specific behaviour.** (REQ-4, REQ-5)
- Alternatives: (a) invent that `add` accepts an optional id and rejects duplicates; (b) drop these REQs.
- Rationale: a new task gets its id automatically (REQ-2), so "no-op" and "id" have no clear meaning for create (Open Question 1). Inventing an `add --id` option would add scope. The design makes sure a no-op message (`Outcome`) and invalid/unknown id errors exist and are handled uniformly across all id-taking commands (REQ-5 via C6 and C2). Behaviour for `add` specifically waits for an answer to Q1.

**D7. Report outcomes with an `Outcome` value for no-ops and exceptions for errors, and set exit codes accordingly (no-op 0, error non-zero).** (REQ-4, REQ-5, REQ-9, REQ-10, REQ-12, REQ-13, REQ-15)
- Alternatives: (a) exceptions for no-ops as well; (b) print messages inside the service.
- Rationale: a repeated action is not a failure, but an unknown id is. Separating them lets the CLI choose stdout or stderr and the exit code in one place. The service stays free of printing.

**D8. Use `argparse` subcommands with `python3 -m todo_app` as the entry point (A3).** (REQ-1, REQ-17)
- Alternatives: (a) hand-parsed `sys.argv`; (b) third-party `click` or `typer`; (c) an interactive prompt loop.
- Rationale: `argparse` is stdlib, gives usage and error handling for free, and has no dependency (CLAUDE.md requires a stdlib-only runtime). An interactive loop would not fit the "command line" wording and is harder to test. Open Question 3 may change the command names but not the structure.

**D9. Write tests as pytest tests that call `main(argv)` and use `tmp_path`, not subprocesses.** (REQ-1 to REQ-17)
- Alternatives: (a) subprocess-based tests only; (b) manual testing.
- Rationale: in-process tests are fast and deterministic and work with the existing `.venv/bin/pytest` runner. The test file location is unresolved (see R2).

## Risks

| # | Risk / assumption | Impact | Mitigation |
|---|---|---|---|
| R1 | REQ-4 and REQ-5 are ambiguous for create (Open Question 1). | The delivered `add` behaviour may not match the author's intent. Two REQs would be only partly verifiable. | Shared no-op/error handling is built (D6). The create-specific behaviour is held until Q1 is answered. Design review should check this. |
| R2 | The implementation phase can only write under `docs/`, so tests would also have to be under `docs/` (for example `docs/todo_app/tests/`). Default pytest discovery from the root would collect them, but `docs/todo_app` must be importable (for example through `rootdir`/`conftest.py` path setup or `python -m pytest` from `docs/`). | Tests may not be collected, or imports may fail, and the verify phase would then lack real passing output. | Place tests inside the package tree under `docs/`. Use relative or `conftest.py`-based imports that work from the repo root. The plan phase should confirm this. See Q-A. |
| R3 | Persistence, id format, CLI syntax and title rules are assumptions (A1-A5; Open Questions 2-6). | Rework if the answers differ. | Each assumption is isolated: the store behind C3, ids in C5, syntax in C8, title rules in `TaskService.add`. |
| R4 | Two commands running at the same time can overwrite each other's changes (no file locking; a last-writer-wins race). | Lost updates under concurrent use. | Accepted for a single-user local CLI. The atomic replace prevents a half-written file. Locking is not designed because no requirement asks for it. |
| R5 | Titles are free text (REQ-16). Newlines or control characters in a title could break the one-line-per-task display. | Confusing `list` output. Data is still stored correctly by JSON. | JSON handles any string safely. If display is a problem, the formatter can escape control characters. It is not specified, so it is left as is. |
| R6 | The data file is written to the current working directory by default. | A user may be surprised by where the file appears. | Allow `--file` or an environment variable override, and document the default. |
| R7 | Application code placed under `docs/` could conflict with the "Automated Documentation Sync" purpose in `sdlc/config.json` `doc_sync`. | A reviewer may question the location. | Recorded in D2 and raised as Q-A for a human decision. |
| R8 | Python version drift: runtime must work on 3.9+ while `.venv` uses 3.14. | A newer-only syntax could break older interpreters. | Avoid 3.10+ features (`match`, `X \| Y` annotations at runtime); use `typing.Optional` and `List`. |
