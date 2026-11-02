"""Pure rendering of tasks and of the empty list."""

from typing import List

from .task import Task

EMPTY_MESSAGE = "No tasks."


def format_task(task: Task) -> str:
    return "{}  {}  [{}]".format(task.id, task.title, task.status.value)


def format_list(tasks: List[Task]) -> str:
    if not tasks:
        return EMPTY_MESSAGE
    return "\n".join(format_task(task) for task in tasks)
