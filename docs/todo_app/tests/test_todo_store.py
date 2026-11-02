import json
import os

import pytest

from todo_app.errors import StoreError
from todo_app.store import JsonFileStore, TaskStore
from todo_app.task import Status, Task


def _entry(**over):
    entry = {"id": 1, "title": "a", "status": "open"}
    entry.update(over)
    return entry


def _doc(tasks=None, next_id=None):
    tasks = [_entry()] if tasks is None else tasks
    return {"next_id": 2 if next_id is None else next_id, "tasks": tasks}


def test_store_is_abstract():
    with pytest.raises(TypeError):
        TaskStore()


def test_missing_file_loads_empty(tmp_path):
    assert JsonFileStore(tmp_path / "none.json").load() == ([], 1)


def test_save_then_load_roundtrip(tmp_path):
    store = JsonFileStore(tmp_path / "t.json")
    tasks = [Task(1, "first", Status.DONE), Task(3, "third", Status.OPEN)]
    store.save(tasks, 4)
    assert store.load() == (tasks, 4)


def test_unicode_and_newline_titles_survive(tmp_path):
    store = JsonFileStore(tmp_path / "t.json")
    tasks = [Task(1, "café ✓ 日本", Status.OPEN), Task(2, "a\nb\r\n-c", Status.OPEN)]
    store.save(tasks, 3)
    assert store.load()[0] == tasks


def test_file_is_utf8_json_with_expected_shape(tmp_path):
    path = tmp_path / "t.json"
    JsonFileStore(path).save([Task(1, "x", Status.OPEN)], 2)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"next_id": 2, "tasks": [{"id": 1, "title": "x", "status": "open"}]}


BAD_CASES = {
    "empty_file": "",
    "invalid_json": "{not json",
    "top_level_list": "[]",
    "missing_next_id": json.dumps({"tasks": []}),
    "missing_tasks": json.dumps({"next_id": 1}),
    "tasks_not_list": json.dumps({"next_id": 1, "tasks": {}}),
    "entry_not_object": json.dumps(_doc([1])),
    "id_string": json.dumps(_doc([_entry(id="1")])),
    "id_bool": json.dumps(_doc([_entry(id=True)])),
    "id_float": json.dumps(_doc([_entry(id=1.0)])),
    "id_zero": json.dumps(_doc([_entry(id=0)])),
    "id_negative": json.dumps(_doc([_entry(id=-1)])),
    "id_missing": json.dumps(_doc([{"title": "a", "status": "open"}])),
    "duplicate_ids": json.dumps(_doc([_entry(), _entry(title="b")], next_id=5)),
    "status_unknown": json.dumps(_doc([_entry(status="pending")])),
    "status_not_string": json.dumps(_doc([_entry(status=1)])),
    "title_not_string": json.dumps(_doc([_entry(title=5)])),
    "title_missing": json.dumps(_doc([{"id": 1, "status": "open"}])),
    "next_id_string": json.dumps(_doc(next_id="2")),
    "next_id_bool": json.dumps(_doc(next_id=True)),
    "next_id_equal_max": json.dumps(_doc(next_id=1)),
    "next_id_below_max": json.dumps(_doc([_entry(id=5)], next_id=3)),
    "next_id_zero": json.dumps({"next_id": 0, "tasks": []}),
}


@pytest.mark.parametrize("name", sorted(BAD_CASES))
def test_invalid_file_raises_store_error(tmp_path, name):
    path = tmp_path / "bad.json"
    path.write_text(BAD_CASES[name], encoding="utf-8")
    with pytest.raises(StoreError) as info:
        JsonFileStore(path).load()
    assert str(path) in str(info.value)


def test_invalid_utf8_raises_store_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(StoreError):
        JsonFileStore(path).load()


def test_unreadable_path_raises_store_error(tmp_path):
    # A directory exists but cannot be read as a file.
    with pytest.raises(StoreError):
        JsonFileStore(tmp_path).load()


def test_failed_replace_keeps_old_file_and_leaves_no_temp(tmp_path, monkeypatch):
    path = tmp_path / "todo.json"
    store = JsonFileStore(path)
    store.save([Task(1, "old", Status.OPEN)], 2)
    before = path.read_bytes()

    def boom(src, dst):
        raise OSError("simulated failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(StoreError):
        store.save([Task(1, "new", Status.DONE)], 9)

    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["todo.json"]


def test_save_into_missing_directory_raises_store_error(tmp_path):
    store = JsonFileStore(tmp_path / "missing" / "todo.json")
    with pytest.raises(StoreError):
        store.save([], 1)
