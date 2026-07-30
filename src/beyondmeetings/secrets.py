"""API keys, stored in the OS keyring with a 0600 file fallback.

Headless machines and minimal desktops frequently have no keyring backend,
so the fallback is a supported path, not an error case.
"""
from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

import keyring
import tomli_w

from .config import DEFAULT_CONFIG_PATH

log = logging.getLogger(__name__)

SERVICE = "beyondmeetings"

# Set when the keyring was unavailable, so the wizard can say where a key
# actually went instead of implying it reached the OS keyring.
_last_store: str | None = None


def last_store() -> str | None:
    return _last_store


def _fallback_path(fallback_dir: Path | None) -> Path:
    base = fallback_dir or DEFAULT_CONFIG_PATH.parent
    return base / "secrets.toml"


def set_secret(name: str, value: str, fallback_dir: Path | None = None) -> None:
    global _last_store
    try:
        keyring.set_password(SERVICE, name, value)
        _last_store = "keyring"
        return
    except Exception as exc:
        # The fallback is a supported path; silence about it was not. The user
        # was told "key verified" and never learned it sits in a file.
        log.warning("OS keyring unavailable (%s); using a 0600 file instead", exc)
        _last_store = "file"

    path = _fallback_path(fallback_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {}
    if path.exists():
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    data[name] = value

    # Create with 0600 rather than chmod after writing — the old order left the
    # key world-readable for the duration of the write.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            tomli_w.dump(data, fh)
    finally:
        os.chmod(path, 0o600)  # tighten an existing file that was too open


def secret_location(name: str, fallback_dir: Path | None = None) -> str | None:
    """Where a stored secret actually lives: 'keyring', 'file', or None.

    Asked directly rather than remembered from the last write, which is process
    local and so reported nothing useful on a fresh `doctor` run.
    """
    try:
        if keyring.get_password(SERVICE, name):
            return "keyring"
    except Exception:
        pass

    path = _fallback_path(fallback_dir)
    if path.exists():
        with path.open("rb") as fh:
            if tomllib.load(fh).get(name):
                return "file"
    return None


def get_secret(name: str, fallback_dir: Path | None = None) -> str | None:
    try:
        value = keyring.get_password(SERVICE, name)
        if value:
            return value
    except Exception:
        pass

    path = _fallback_path(fallback_dir)
    if not path.exists():
        return None
    with path.open("rb") as fh:
        return tomllib.load(fh).get(name)
