"""Human approver identity and authentication.

Approving, rejecting, reopening and authorizing a PR need a registered human
approver who proves a passphrase typed on the controlling terminal. Agents have
neither the passphrase nor a way to type it, so this holds even if an agent
learns the command line or opens its own pseudo-terminal.
"""
from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import os
import re

from . import common as c
from . import evidence

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{1,63}$")
AGENT_LIKE = re.compile(r"^(agent|claude|bot|system|orchestrator|assistant|ai)([^a-z]|$)", re.I)
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "SDLC_ACTIVE_PHASE", "SDLC_ACTIVE_AGENT")
MIN_SECRET = 10
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def is_agent_identity(identifier: str) -> bool:
    names = set(c.AGENTS.values()) | {c.ORCHESTRATOR_AGENT}
    return identifier.lower() in names or bool(AGENT_LIKE.match(identifier))


def validate_id(identifier: str) -> str:
    if not ID_RE.match(identifier or ""):
        raise c.SdlcError("approver id %r is invalid (2-64 chars: letters, digits, . _ @ -)" % identifier)
    if is_agent_identity(identifier):
        raise c.SdlcError("approver id %r looks like an agent identity; approvals must come from humans" % identifier)
    return identifier


def _file():
    return evidence.approvers_path(c.ROOT)


def registry() -> dict:
    fp = _file()
    if not fp.is_file():
        return {}
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except ValueError:
        raise c.SdlcError("approver registry %s is corrupt" % fp)


def _hash(secret: str, salt: bytes) -> str:
    return hashlib.scrypt(secret.encode("utf-8"), salt=salt, dklen=32, **SCRYPT).hex()


def register(identifier: str, secret: str) -> None:
    validate_id(identifier)
    if len(secret) < MIN_SECRET:
        raise c.SdlcError("passphrase must be at least %d characters" % MIN_SECRET)
    reg = registry()
    salt = os.urandom(16)
    reg[identifier] = {"salt": salt.hex(), "hash": _hash(secret, salt), "registered_at": c.utcnow()}
    _file().parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    c.atomic_write(_file(), json.dumps(reg, indent=2) + "\n")
    os.chmod(str(_file()), 0o600)


def authenticate(identifier: str, secret: str) -> bool:
    record = registry().get(identifier)
    if not record:
        return False
    return hmac.compare_digest(_hash(secret, bytes.fromhex(record["salt"])), record["hash"])


class Console:
    """Human terminal I/O. Tests substitute a scripted console."""

    def __init__(self, tty_in, tty_out):
        self.tty_in = tty_in
        self.tty_out = tty_out

    def show(self, message: str) -> None:
        self.tty_out.write(message + "\n")
        self.tty_out.flush()

    def ask(self, prompt: str) -> str:
        self.tty_out.write(prompt)
        self.tty_out.flush()
        line = self.tty_in.readline()
        if line == "":
            raise c.SdlcError("no input received")
        return line.strip()

    def secret(self, prompt: str) -> str:
        return getpass.getpass(prompt)


def forbid_agent_context() -> None:
    for key in AGENT_ENV:
        if os.environ.get(key):
            raise c.SdlcError("this command is reserved for humans in their own terminal, not an agent session (%s set)" % key)


def human_console() -> Console:
    forbid_agent_context()
    try:
        # Separate handles: Python 3.14 rejects a text-mode "r+" open of the non-seekable tty.
        return Console(open("/dev/tty", "r"), open("/dev/tty", "w"))
    except OSError:
        raise c.SdlcError("no controlling terminal; this command requires an interactive human terminal")


def require_approver(console, approver: str) -> str:
    """Authenticate `approver` on the console; return the verified id."""
    validate_id(approver)
    if approver not in registry():
        raise c.SdlcError("approver %r is not registered; run 'python3 orchestrator.py init --approver %s'" % (approver, approver))
    if not authenticate(approver, console.secret("Passphrase for %s: " % approver)):
        raise c.SdlcError("authentication failed for approver %r" % approver)
    return approver
