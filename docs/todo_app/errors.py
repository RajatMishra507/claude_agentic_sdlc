"""Domain errors and the Outcome value reported by the service."""

import dataclasses


class TodoError(Exception):
    """Base class for all expected application errors."""


class InvalidIdError(TodoError):
    """The raw id is not a positive integer."""


class UnknownIdError(TodoError):
    """The id is well formed but no task has it."""


class StoreError(TodoError):
    """The data file could not be read, validated or written."""


@dataclasses.dataclass(frozen=True)
class Outcome:
    """Result of a state-changing operation.

    changed is False for a no-op (for example completing an already-done task).
    """

    changed: bool
    message: str
