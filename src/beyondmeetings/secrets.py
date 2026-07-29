"""API keys, stored in the OS keyring with a 0600 file fallback.

Headless machines and minimal desktops frequently have no keyring backend,
so the fallback is a supported path, not an error case.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

import keyring
import tomli_w

from .config import DEFAULT_CONFIG_PATH

SERVICE = "beyondmeetings"


def _fallback_path(fallback_dir: Path | None) -> Path:
    base = fallback_dir or DEFAULT_CONFIG_PATH.parent
    return base / "secrets.toml"


def set_secret(name: str, value: str, fallback_dir: Path | None = None) -> None:
    try:
        keyring.set_password(SERVICE, name, value)
        return
    except Exception:
        pass

    path = _fallback_path(fallback_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    data[name] = value
    with path.open("wb") as fh:
        tomli_w.dump(data, fh)
    os.chmod(path, 0o600)


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
