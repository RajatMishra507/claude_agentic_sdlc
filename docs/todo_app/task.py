"""Task model: the only place the status vocabulary is defined."""

import dataclasses
import enum


class Status(enum.Enum):
    OPEN = "open"
    DONE = "done"


@dataclasses.dataclass(frozen=True)
class Task:
    """A task. Instances are immutable; use dataclasses.replace to change state."""

    id: int
    title: str
    status: Status
