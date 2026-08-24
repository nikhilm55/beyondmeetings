"""Keep the suite away from the developer's real meeting data.

`config.DEFAULT_DATA_DIR` is resolved through platformdirs at import time, so a
`Config()` left with an empty `library_path` falls back to the machine's actual
library. That made `test_history_is_empty_without_a_vault` pass on a clean
checkout and fail on any machine that had recorded a meeting — the suite was
reading real notes.

Redirecting the platform directories has to happen here, at conftest import,
because pytest imports this module before the test modules import
beyondmeetings; by the time a test runs, config.py's module-level constants are
already frozen. Only the environment variables platformdirs consults are set —
deliberately not HOME, which would move the keyring and other per-user state
that the existing tests are happy to read.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_SANDBOX = Path(tempfile.mkdtemp(prefix="beyondmeetings-tests-"))

# Linux resolves through the XDG pair, Windows through LOCALAPPDATA/APPDATA.
# Setting both keeps the suite hermetic on either CI platform.
_REDIRECTS = (
    ("XDG_DATA_HOME", "data"),
    ("XDG_CONFIG_HOME", "config"),
    ("XDG_CACHE_HOME", "cache"),
    ("LOCALAPPDATA", "localappdata"),
    ("APPDATA", "appdata"),
)

for _var, _subdir in _REDIRECTS:
    _target = _SANDBOX / _subdir
    _target.mkdir(parents=True, exist_ok=True)
    os.environ[_var] = str(_target)


@atexit.register
def _cleanup_sandbox() -> None:
    shutil.rmtree(_SANDBOX, ignore_errors=True)
