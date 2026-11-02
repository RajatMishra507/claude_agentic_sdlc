import pytest

from todo_app.errors import InvalidIdError
from todo_app.ids import parse_id


@pytest.mark.parametrize("raw, expected", [("1", 1), ("42", 42), ("007", 7)])
def test_valid_ids(raw, expected):
    assert parse_id(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "0", "-3", "+5", " 5", "5 ", "5\n", "1_0", "1.5", "abc", "٣"],
)
def test_invalid_ids_raise(raw):
    with pytest.raises(InvalidIdError) as info:
        parse_id(raw)
    assert repr(raw)[1:-1] in str(info.value) or raw in str(info.value)
    assert "must be a positive integer" in str(info.value)
