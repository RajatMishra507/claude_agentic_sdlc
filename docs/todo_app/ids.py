"""Strict id parser."""

import re

from .errors import InvalidIdError

_ID_PATTERN = re.compile(r"[0-9]+")


def parse_id(raw: str) -> int:
    """Convert a raw CLI string to a positive int or raise InvalidIdError.

    Only ASCII digits are accepted: no sign, spaces, underscores, decimals or
    non-ASCII digits. The value must be at least 1.
    """
    if isinstance(raw, str) and _ID_PATTERN.fullmatch(raw):
        value = int(raw)
        if value >= 1:
            return value
    raise InvalidIdError("invalid id '{}': must be a positive integer".format(raw))
