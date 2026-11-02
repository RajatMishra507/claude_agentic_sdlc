from todo_app.formatter import format_list, format_task
from todo_app.task import Status, Task


def test_format_open_task():
    assert format_task(Task(1, "Buy milk", Status.OPEN)) == "1  Buy milk  [open]"


def test_format_done_task():
    assert format_task(Task(2, "Pay rent", Status.DONE)) == "2  Pay rent  [done]"


def test_format_empty_list():
    assert format_list([]) == "No tasks."


def test_format_list_keeps_input_order_one_per_line():
    tasks = [Task(2, "b", Status.OPEN), Task(1, "a", Status.DONE)]
    assert format_list(tasks) == "2  b  [open]\n1  a  [done]"
