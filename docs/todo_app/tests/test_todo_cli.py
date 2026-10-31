import os
import subprocess
import sys
from pathlib import Path

import pytest

from todo_app.cli import main

DOCS_DIR = Path(__file__).resolve().parents[2]


def run(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_add_prints_id_title_and_open_status(capsys, data_file):
    code, out, err = run(capsys, "add", "Buy milk")
    assert code == 0
    assert err == ""
    assert "1" in out and "Buy milk" in out and "[open]" in out
    assert data_file.exists()


def test_list_shows_tasks_in_creation_order(capsys):
    run(capsys, "add", "first")
    run(capsys, "add", "second")
    code, out, _ = run(capsys, "list")
    assert code == 0
    lines = out.splitlines()
    assert len(lines) == 2
    assert "first" in lines[0] and "second" in lines[1]
    assert lines[0].startswith("1  ") and lines[1].startswith("2  ")


def test_list_empty_prints_message_and_returns_zero(capsys):
    code, out, err = run(capsys, "list")
    assert (code, out.strip(), err) == (0, "No tasks.", "")


def test_full_cycle(capsys, data_file):
    run(capsys, "add", "task")

    code, out, _ = run(capsys, "done", "1")
    assert code == 0 and "marked done" in out

    before = data_file.read_bytes()
    code, out, err = run(capsys, "done", "1")
    assert code == 0 and "already done" in out and err == ""
    assert data_file.read_bytes() == before

    code, out, _ = run(capsys, "reopen", "1")
    assert code == 0 and "reopened" in out

    before = data_file.read_bytes()
    code, out, err = run(capsys, "reopen", "1")
    assert code == 0 and "already open" in out and err == ""
    assert data_file.read_bytes() == before

    code, out, _ = run(capsys, "delete", "1")
    assert code == 0 and "deleted" in out

    code, out, _ = run(capsys, "list")
    assert code == 0 and out.strip() == "No tasks."


def test_done_status_shows_in_list(capsys):
    run(capsys, "add", "task")
    run(capsys, "done", "1")
    _, out, _ = run(capsys, "list")
    assert "[done]" in out


@pytest.mark.parametrize("command", ["done", "reopen", "delete"])
def test_unknown_id_is_an_error_and_changes_nothing(capsys, data_file, command):
    run(capsys, "add", "task")
    before = data_file.read_bytes()
    code, out, err = run(capsys, command, "99")
    assert code == 1
    assert "unknown id 99" in err
    assert out == ""
    assert data_file.read_bytes() == before


@pytest.mark.parametrize(
    "argv",
    [
        ("done", "abc"),
        ("done", "0"),
        ("done", "1.5"),
        ("done", "+5"),
        ("reopen", "abc"),
        ("delete", "abc"),
    ],
)
def test_invalid_id_is_an_error_and_creates_no_file(capsys, data_file, argv):
    code, out, err = run(capsys, *argv)
    assert code != 0
    assert "invalid id" in err
    assert out == ""
    assert not data_file.exists()


def test_negative_id_is_an_error_and_creates_no_file(capsys, data_file):
    code, out, err = run(capsys, "done", "-3")
    assert code != 0
    assert err.strip() != ""
    assert not data_file.exists()


def test_title_starting_with_dash_after_double_dash(capsys):
    code, out, _ = run(capsys, "add", "--", "-draft")
    assert code == 0
    assert "-draft" in out
    _, listing, _ = run(capsys, "list")
    assert "-draft" in listing


def test_add_help_mentions_double_dash(capsys):
    code, out, _ = run(capsys, "add", "--help")
    assert code == 0
    assert "add -- -draft" in " ".join(out.split())


@pytest.mark.parametrize("argv", [(), ("done",), ("add",), ("bogus",)])
def test_usage_errors_return_two(capsys, argv):
    code, out, err = run(capsys, *argv)
    assert code == 2
    assert err.strip() != ""


def test_corrupt_data_file_is_reported_and_left_unchanged(capsys, data_file):
    data_file.write_text("{not json", encoding="utf-8")
    for argv in (("list",), ("add", "x"), ("done", "1")):
        code, out, err = run(capsys, *argv)
        assert code == 1
        assert err.startswith("error:")
        assert data_file.read_text(encoding="utf-8") == "{not json"


def test_default_file_is_todo_json_in_current_directory(capsys, tmp_path, monkeypatch):
    monkeypatch.delenv("TODO_APP_FILE", raising=False)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    assert run(capsys, "add", "x")[0] == 0
    assert (cwd / "todo.json").exists()


def test_env_variable_selects_file(capsys, tmp_path, monkeypatch):
    target = tmp_path / "env.json"
    monkeypatch.setenv("TODO_APP_FILE", str(target))
    assert run(capsys, "add", "x")[0] == 0
    assert target.exists()


def test_file_option_wins_over_env_variable(capsys, tmp_path, data_file):
    chosen = tmp_path / "chosen.json"
    code, _, _ = run(capsys, "--file", str(chosen), "add", "x")
    assert code == 0
    assert chosen.exists()
    assert not data_file.exists()


def test_module_entry_point_smoke(tmp_path):
    target = tmp_path / "smoke.json"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-m", "todo_app", "--file", str(target), "add", "x"],
        cwd=str(DOCS_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    assert result.returncode == 0, result.stderr
    assert "[open]" in result.stdout
    assert target.exists()
