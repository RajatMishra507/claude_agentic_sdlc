# todo_app

A small Python command-line application for managing a simple task list. Each task has a unique id, a free-text title and a status of `open` or `done`. It uses the Python standard library only and is written to run on Python 3.9 or later.

This package lives under `docs/` only because the implementation phase of this repository may write nothing outside `docs/`.

## Run

Run from the `docs/` directory (or put `docs/` on `PYTHONPATH`), because the package is `docs/todo_app/`:

```
cd docs
python3 -m todo_app add "Buy milk"
python3 -m todo_app list
python3 -m todo_app done 1
python3 -m todo_app reopen 1
python3 -m todo_app delete 1
```

Commands:

| Command | Behaviour |
|---|---|
| `add TITLE` | Creates an `open` task with a new id and prints `<id>  <title>  [open]`. |
| `list` | Prints one `<id>  <title>  [<status>]` line per task in creation order, or `No tasks.` if there are none. |
| `done ID` | Sets an open task to `done` (`task N marked done`). If it is already done, prints `task N is already done` and changes nothing. |
| `reopen ID` | Sets a done task to `open` (`task N reopened`). If it is already open, prints `task N is already open` and changes nothing. |
| `delete ID` | Removes the task (`task N deleted`). |

An unknown id prints `error: unknown id N: no such task` to stderr and exits with 1. An id that is not a positive integer prints `error: invalid id '<value>': must be a positive integer` to stderr. No-ops exit with 0. Usage errors (missing subcommand or argument) exit with 2.

The `--file PATH` option goes before the subcommand: `python3 -m todo_app --file my.json list`.

Data file, in order of precedence:
1. `--file PATH`
2. the `TODO_APP_FILE` environment variable
3. `todo.json` in the current working directory

A title that starts with `-` needs `--` before it, for example `python3 -m todo_app add -- -draft`.

## Test

From the repository root:

```
.venv/bin/pytest docs/todo_app/tests -q
```

The tests are in `docs/todo_app/tests/` and are named `test_todo_*.py`. Each test works in a temporary directory and uses a temporary data file, so running them does not create a `todo.json` in the repository.

## Assumptions

The source requirements (the Confluence page "Todo List User Story") do not state the following. They are design choices and may change when the questions are answered.

- A1: The task list is kept between runs in a local JSON file.
- A2: Ids are positive integers assigned in sequence and are not reused after a delete.
- A3: The commands are `add`, `list`, `done`, `reopen` and `delete`.
- A4: `list` shows the id, title and status of each task.
- A5: An "invalid" id is a value that is not a positive integer made of ASCII digits. An "unknown" id is a well-formed id that matches no task.
- The environment variable name `TODO_APP_FILE`, the default file name `todo.json` and the exact message wording are choices made by the implementation plan.
- REQ-4 and REQ-5 (the create criterion about a repeated no-op and an invalid or unknown id) have no create-specific behaviour. It is unclear what they mean for `add`, because a new task gets its id automatically. The no-op messages and id errors are implemented for `done`, `reopen` and `delete` only. This is pending the answer to Open Question 1.

## Limitations

- No file locking. If two commands run at the same time, the last one to write wins. Writes are atomic (a temporary file is replaced into place), so the file is never left half-written.
- Titles are stored exactly as given. Empty and very long titles are accepted. Control characters in a title are not escaped and can change how `list` looks. Output to a terminal that cannot encode a title character can fail.
- Python 3.9 compatibility is checked only in part (a syntax parse and an annotation scan in the tests); it is not run on a 3.9 interpreter.
