import pytest

from todo_app.errors import UnknownIdError
from todo_app.service import TaskService
from todo_app.store import TaskStore
from todo_app.task import Status, Task


class FakeStore(TaskStore):
    def __init__(self, tasks=None, next_id=1):
        self.tasks = list(tasks or [])
        self.next_id = next_id
        self.saves = 0

    def load(self):
        return list(self.tasks), self.next_id

    def save(self, tasks, next_id):
        self.saves += 1
        self.tasks = list(tasks)
        self.next_id = next_id


def test_adds_get_sequential_ids_open_status_and_creation_order():
    store = FakeStore()
    service = TaskService(store)
    first = service.add("one")
    second = service.add("two")
    assert (first.id, second.id) == (1, 2)
    assert first.status is Status.OPEN and second.status is Status.OPEN
    assert [t.title for t in service.list()] == ["one", "two"]


def test_id_is_not_reused_after_deleting_last_task():
    store = FakeStore()
    service = TaskService(store)
    service.add("one")
    service.add("two")
    service.delete(2)
    assert service.add("three").id == 3


@pytest.mark.parametrize("title", ["-draft", "café ✓", "a\nb", "", "  x  "])
def test_title_is_stored_verbatim(title):
    service = TaskService(FakeStore())
    assert service.add(title).title == title
    assert service.list()[0].title == title


def test_same_title_twice_gives_two_tasks():
    service = TaskService(FakeStore())
    service.add("same")
    service.add("same")
    assert [t.id for t in service.list()] == [1, 2]


def test_complete_open_task_changes_status_and_saves_once():
    store = FakeStore([Task(1, "a", Status.OPEN)], 2)
    outcome = TaskService(store).complete(1)
    assert outcome.changed is True
    assert outcome.message == "task 1 marked done"
    assert store.tasks[0].status is Status.DONE
    assert store.saves == 1


def test_complete_done_task_is_noop_without_save():
    store = FakeStore([Task(1, "a", Status.DONE)], 2)
    outcome = TaskService(store).complete(1)
    assert outcome.changed is False
    assert outcome.message == "task 1 is already done"
    assert store.saves == 0


def test_reopen_done_task_changes_status_and_saves_once():
    store = FakeStore([Task(1, "a", Status.DONE)], 2)
    outcome = TaskService(store).reopen(1)
    assert outcome.changed is True
    assert outcome.message == "task 1 reopened"
    assert store.tasks[0].status is Status.OPEN
    assert store.saves == 1


def test_reopen_open_task_is_noop_without_save():
    store = FakeStore([Task(1, "a", Status.OPEN)], 2)
    outcome = TaskService(store).reopen(1)
    assert outcome.changed is False
    assert outcome.message == "task 1 is already open"
    assert store.saves == 0


def test_delete_removes_task_saves_once_and_keeps_next_id():
    store = FakeStore([Task(1, "a", Status.OPEN), Task(2, "b", Status.OPEN)], 3)
    outcome = TaskService(store).delete(1)
    assert outcome.changed is True
    assert outcome.message == "task 1 deleted"
    assert [t.id for t in store.tasks] == [2]
    assert store.next_id == 3
    assert store.saves == 1


@pytest.mark.parametrize("method", ["complete", "reopen", "delete"])
def test_unknown_id_raises_and_does_not_save(method):
    store = FakeStore([Task(1, "a", Status.OPEN)], 2)
    with pytest.raises(UnknownIdError) as info:
        getattr(TaskService(store), method)(99)
    assert "unknown id 99" in str(info.value)
    assert store.saves == 0
    assert store.tasks == [Task(1, "a", Status.OPEN)]


def test_list_on_empty_store_is_empty():
    assert TaskService(FakeStore()).list() == []
