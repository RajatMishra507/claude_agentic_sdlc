"""Persistence: the TaskStore contract and a JSON-file implementation."""

import abc
import json
import os
import tempfile
from pathlib import Path
from typing import Any, List, Tuple

from .errors import StoreError
from .task import Status, Task


class TaskStore(abc.ABC):
    """Load/save contract that keeps the service free of file I/O."""

    @abc.abstractmethod
    def load(self) -> Tuple[List[Task], int]:
        """Return (tasks in creation order, next_id)."""

    @abc.abstractmethod
    def save(self, tasks: List[Task], next_id: int) -> None:
        """Persist the tasks (in the given order) and the next id."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class JsonFileStore(TaskStore):
    """Stores {"next_id": n, "tasks": [{"id", "title", "status"}, ...]} as UTF-8 JSON."""

    def __init__(self, path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _fail(self, reason: str) -> StoreError:
        return StoreError("{}: {}".format(self._path, reason))

    def load(self) -> Tuple[List[Task], int]:
        if not self._path.exists():
            return [], 1
        try:
            text = self._path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            raise self._fail("cannot read data file ({})".format(exc)) from exc
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise self._fail("data file is not valid JSON ({})".format(exc)) from exc
        return self._parse(data)

    def _parse(self, data: Any) -> Tuple[List[Task], int]:
        if not isinstance(data, dict):
            raise self._fail("top level must be a JSON object")
        if "next_id" not in data or "tasks" not in data:
            raise self._fail("missing 'next_id' or 'tasks'")
        next_id = data["next_id"]
        if not _is_int(next_id) or next_id < 1:
            raise self._fail("'next_id' must be an integer of at least 1")
        raw_tasks = data["tasks"]
        if not isinstance(raw_tasks, list):
            raise self._fail("'tasks' must be a list")

        tasks = []  # type: List[Task]
        seen = set()
        for index, entry in enumerate(raw_tasks):
            if not isinstance(entry, dict):
                raise self._fail("task entry {} is not an object".format(index))
            task_id = entry.get("id")
            if not _is_int(task_id) or task_id < 1:
                raise self._fail("task entry {} has an invalid 'id'".format(index))
            if task_id in seen:
                raise self._fail("duplicate task id {}".format(task_id))
            seen.add(task_id)
            status = entry.get("status")
            if not isinstance(status, str) or status not in (s.value for s in Status):
                raise self._fail("task {} has an invalid 'status'".format(task_id))
            title = entry.get("title")
            if not isinstance(title, str):
                raise self._fail("task {} has an invalid 'title'".format(task_id))
            tasks.append(Task(task_id, title, Status(status)))

        if tasks and next_id <= max(task.id for task in tasks):
            raise self._fail("'next_id' must be greater than every task id")
        return tasks, next_id

    def save(self, tasks: List[Task], next_id: int) -> None:
        payload = {
            "next_id": next_id,
            "tasks": [
                {"id": task.id, "title": task.title, "status": task.status.value}
                for task in tasks
            ],
        }
        tmp_name = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self._path.parent),
                prefix=self._path.name + ".",
                suffix=".tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, str(self._path))
        except (OSError, ValueError, TypeError) as exc:
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
            raise self._fail("cannot write data file ({})".format(exc)) from exc
