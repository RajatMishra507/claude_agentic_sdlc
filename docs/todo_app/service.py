"""TaskService: all task rules, no I/O of its own."""

import dataclasses
from typing import List

from .errors import Outcome, UnknownIdError
from .store import TaskStore
from .task import Status, Task


class TaskService:
    def __init__(self, store: TaskStore) -> None:
        self._store = store

    def add(self, title: str) -> Task:
        """Create an open task with the next id. The title is stored verbatim."""
        tasks, next_id = self._store.load()
        task = Task(next_id, title, Status.OPEN)
        tasks.append(task)
        self._store.save(tasks, next_id + 1)
        return task

    def list(self) -> List[Task]:
        """Return the tasks in creation order."""
        tasks, _ = self._store.load()
        return tasks

    def complete(self, task_id: int) -> Outcome:
        return self._transition(
            task_id, Status.DONE, "task {} marked done", "task {} is already done"
        )

    def reopen(self, task_id: int) -> Outcome:
        return self._transition(
            task_id, Status.OPEN, "task {} reopened", "task {} is already open"
        )

    def delete(self, task_id: int) -> Outcome:
        tasks, next_id = self._store.load()
        index = self._find(tasks, task_id)
        del tasks[index]
        self._store.save(tasks, next_id)
        return Outcome(True, "task {} deleted".format(task_id))

    def _transition(
        self, task_id: int, target: Status, changed_msg: str, noop_msg: str
    ) -> Outcome:
        tasks, next_id = self._store.load()
        index = self._find(tasks, task_id)
        task = tasks[index]
        if task.status is target:
            return Outcome(False, noop_msg.format(task_id))
        tasks[index] = dataclasses.replace(task, status=target)
        self._store.save(tasks, next_id)
        return Outcome(True, changed_msg.format(task_id))

    @staticmethod
    def _find(tasks: List[Task], task_id: int) -> int:
        for index, task in enumerate(tasks):
            if task.id == task_id:
                return index
        raise UnknownIdError("unknown id {}: no such task".format(task_id))
