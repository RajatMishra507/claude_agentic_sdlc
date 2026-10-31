"""Test isolation: no test may write a data file outside its tmp_path."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_todo_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TODO_APP_FILE", str(tmp_path / "todo.json"))


@pytest.fixture
def data_file(tmp_path):
    return tmp_path / "todo.json"
