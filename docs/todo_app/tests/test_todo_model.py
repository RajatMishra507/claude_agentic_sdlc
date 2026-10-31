import dataclasses
from pathlib import Path

import pytest

from todo_app.errors import InvalidIdError, Outcome, StoreError, TodoError, UnknownIdError
from todo_app.task import Status, Task

PACKAGE_DIR = Path(__file__).resolve().parents[1]


def test_task_is_frozen():
    task = Task(1, "a", Status.OPEN)
    with pytest.raises(dataclasses.FrozenInstanceError):
        task.title = "b"


def test_status_has_exactly_open_and_done():
    assert {s.value for s in Status} == {"open", "done"}
    assert len(list(Status)) == 2


@pytest.mark.parametrize("title", ["  spaced  ", "café ✓", "-draft", "line1\nline2", ""])
def test_title_is_kept_verbatim(title):
    assert Task(1, title, Status.OPEN).title == title


@pytest.mark.parametrize("cls", [InvalidIdError, UnknownIdError, StoreError])
def test_errors_derive_from_todo_error(cls):
    assert issubclass(cls, TodoError)


def test_outcome_is_immutable():
    outcome = Outcome(True, "x")
    assert outcome.changed is True
    assert outcome.message == "x"
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.changed = False


def test_package_layout_markers():
    assert (PACKAGE_DIR / "__init__.py").is_file()
    assert (PACKAGE_DIR / "tests" / "__init__.py").is_file()
    assert not (PACKAGE_DIR.parent / "__init__.py").exists()
