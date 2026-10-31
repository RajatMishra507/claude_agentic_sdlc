"""Command-line interface: argparse subcommands wired to the service."""

import argparse
import os
import sys
from typing import List, Optional

from .errors import TodoError
from .formatter import format_list, format_task
from .ids import parse_id
from .service import TaskService
from .store import JsonFileStore

ENV_FILE = "TODO_APP_FILE"
DEFAULT_FILE = "todo.json"

_EPILOG = (
    "The data file is chosen from --file, then the TODO_APP_FILE environment "
    "variable, then todo.json in the current directory. A title that starts "
    "with '-' needs '--' before it, for example: add -- -draft"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="todo_app",
        description="Manage a simple task list.",
        epilog=_EPILOG,
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        default=None,
        help="data file to use (give this option before the subcommand)",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    add = sub.add_parser("add", help="add a new open task")
    add.add_argument(
        "title",
        metavar="TITLE",
        help="task title (free text); use '--' before a title that starts "
        "with '-', for example: add -- -draft",
    )
    sub.add_parser("list", help="list tasks in creation order")
    for name, text in (
        ("done", "mark a task as done"),
        ("reopen", "mark a task as open again"),
        ("delete", "delete a task"),
    ):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("id", metavar="ID", help="task id (a positive integer)")
    return parser


def _data_path(option: Optional[str]) -> str:
    if option:
        return option
    return os.environ.get(ENV_FILE) or DEFAULT_FILE


def _exit_code(exc: SystemExit) -> int:
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1


def _run(args: argparse.Namespace) -> int:
    # The id is parsed before the store is built, so an invalid id never
    # touches the data file.
    task_id = parse_id(args.id) if args.command in ("done", "reopen", "delete") else None
    service = TaskService(JsonFileStore(_data_path(args.file)))

    if args.command == "add":
        print(format_task(service.add(args.title)))
    elif args.command == "list":
        print(format_list(service.list()))
    else:
        actions = {
            "done": service.complete,
            "reopen": service.reopen,
            "delete": service.delete,
        }
        print(actions[args.command](task_id).message)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _exit_code(exc)
    try:
        return _run(args)
    except TodoError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1
