# beyondMeetings Milestone 2 — Setup Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stranger runs one `curl` command and reaches a working install — prerequisite detection with a completion ring, per-row Fix buttons, key entry validated by live API calls, and generated agent rules files.

**Architecture:** Every prerequisite is a `Check` object with `detect()` and optional `fix()`. The same objects drive both the browser wizard and `beyondmeetings doctor`, so the two can never disagree. FastAPI serves a JSON API plus one static page; the page is vanilla JS with no build step.

**Tech Stack:** FastAPI + uvicorn (added deps), existing pydantic/httpx. Vanilla HTML/CSS/JS — no bundler, no framework, no CDN.

**Spec:** `docs/superpowers/specs/2026-07-30-beyondmeetings-setup-design.md` §6, §7, §11
**Tracker:** `PROGRESS.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `src/beyondmeetings/doctor/base.py` | `CheckResult`, `Check`, `run_all()`, `completion_percent()` |
| `src/beyondmeetings/doctor/system.py` | PipeWire and ffmpeg checks + package-manager hints |
| `src/beyondmeetings/doctor/obsidian.py` | Obsidian detection + flatpak install |
| `src/beyondmeetings/doctor/vault.py` | Vault path + scaffold check |
| `src/beyondmeetings/doctor/keys.py` | Groq + provider key checks, validated by live API call |
| `src/beyondmeetings/doctor/rules.py` | Rules-files-generated check |
| `src/beyondmeetings/doctor/registry.py` | Assembles the ordered check list from config |
| `src/beyondmeetings/rules.py` | One template → `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` |
| `src/beyondmeetings/server.py` | FastAPI app: JSON API + static page |
| `src/beyondmeetings/web/setup.html` | Checklist wizard UI |
| `src/beyondmeetings/web/setup.css` | Styles, light + dark |
| `src/beyondmeetings/web/setup.js` | Poll state, render rows, dispatch fixes |
| `install.sh` | Bootstrap: system Python or `uv`, venv, symlink, launch wizard |

---

## Task 1: Check framework

**Files:**
- Create: `src/beyondmeetings/doctor/__init__.py`, `src/beyondmeetings/doctor/base.py`
- Test: `tests/test_doctor_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_base.py
from beyondmeetings.doctor.base import (
    Check, CheckResult, completion_percent, run_all,
)


class Stub(Check):
    def __init__(self, id, status, required=True, fixable=False):
        self.id = id
        self.label = id.title()
        self.required = required
        self._status = status
        self._fixable = fixable
        self.fixed = False

    def detect(self) -> CheckResult:
        return CheckResult(status=self._status)

    @property
    def fixable(self) -> bool:
        return self._fixable

    def fix(self, **kwargs) -> CheckResult:
        self.fixed = True
        return CheckResult(status="ok")


def test_run_all_reports_each_check():
    rows = run_all([Stub("a", "ok"), Stub("b", "missing")])
    assert [r["id"] for r in rows] == ["a", "b"]
    assert rows[0]["status"] == "ok"
    assert rows[1]["status"] == "missing"


def test_percent_counts_only_required_checks():
    checks = [Stub("a", "ok"), Stub("b", "missing"), Stub("c", "missing", required=False)]
    assert completion_percent(run_all(checks)) == 50


def test_percent_is_100_when_all_required_pass():
    checks = [Stub("a", "ok"), Stub("b", "missing", required=False)]
    assert completion_percent(run_all(checks)) == 100


def test_percent_is_0_with_no_required_checks_passing():
    assert completion_percent(run_all([Stub("a", "missing")])) == 0


def test_percent_is_100_when_there_are_no_required_checks():
    assert completion_percent(run_all([Stub("a", "ok", required=False)])) == 100


def test_row_exposes_fixable_and_required():
    row = run_all([Stub("a", "missing", fixable=True)])[0]
    assert row["fixable"] is True
    assert row["required"] is True


def test_detect_failure_is_reported_as_broken_not_raised():
    class Exploding(Stub):
        def detect(self):
            raise OSError("boom")

    row = run_all([Exploding("a", "ok")])[0]
    assert row["status"] == "broken"
    assert "boom" in row["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_doctor_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.doctor'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/doctor/__init__.py
```

```python
# src/beyondmeetings/doctor/base.py
"""Prerequisite checks.

One object per prerequisite, driving both the wizard and `doctor`. A check
that raises during detection is reported as broken rather than crashing the
page — a wizard that dies on a weird machine is worse than one that says so.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel

Status = Literal["ok", "missing", "broken"]


class CheckResult(BaseModel):
    status: Status
    detail: str = ""


class InputField(BaseModel):
    name: str
    label: str
    placeholder: str = ""
    secret: bool = False


class Check(ABC):
    id: str
    label: str
    description: str = ""
    required: bool = True
    inputs: list[InputField] = []

    @abstractmethod
    def detect(self) -> CheckResult:
        ...

    @property
    def fixable(self) -> bool:
        return False

    def fix(self, **kwargs) -> CheckResult:
        raise NotImplementedError(f"{self.id} cannot be fixed automatically")


def run_all(checks: list[Check]) -> list[dict]:
    rows = []
    for check in checks:
        try:
            result = check.detect()
        except Exception as exc:  # a broken probe must not break the page
            result = CheckResult(status="broken", detail=str(exc))
        rows.append(
            {
                "id": check.id,
                "label": check.label,
                "description": check.description,
                "status": result.status,
                "detail": result.detail,
                "required": check.required,
                "fixable": check.fixable,
                "inputs": [i.model_dump() for i in check.inputs],
            }
        )
    return rows


def completion_percent(rows: list[dict]) -> int:
    required = [r for r in rows if r["required"]]
    if not required:
        return 100
    passing = sum(1 for r in required if r["status"] == "ok")
    return round(100 * passing / len(required))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_doctor_base.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/doctor tests/test_doctor_base.py
git commit -m "feat: prerequisite check framework"
```

---

## Task 2: System checks (PipeWire, ffmpeg)

**Files:**
- Create: `src/beyondmeetings/doctor/system.py`
- Test: `tests/test_doctor_system.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_system.py
from beyondmeetings.doctor.system import FfmpegCheck, PipeWireCheck, install_hint


def test_pipewire_ok_when_both_binaries_present(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: f"/usr/bin/{n}")
    assert PipeWireCheck().detect().status == "ok"


def test_pipewire_missing_when_pw_record_absent(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None if n == "pw-record" else "/usr/bin/x")
    result = PipeWireCheck().detect()
    assert result.status == "missing"
    assert "pw-record" in result.detail


def test_pipewire_is_not_auto_fixable():
    assert PipeWireCheck().fixable is False


def test_ffmpeg_ok_when_present(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/ffmpeg")
    assert FfmpegCheck().detect().status == "ok"


def test_ffmpeg_missing_when_absent(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    assert FfmpegCheck().detect().status == "missing"


def test_ffmpeg_is_fixable():
    assert FfmpegCheck().fixable is True


def test_install_hint_matches_the_available_package_manager(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/dnf" if n == "dnf" else None)
    assert install_hint("ffmpeg") == "sudo dnf install -y ffmpeg"


def test_install_hint_falls_back_when_no_manager_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    assert "package manager" in install_hint("ffmpeg")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_doctor_system.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.doctor.system'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/doctor/system.py
"""Checks for the binaries the audio pipeline shells out to."""
from __future__ import annotations

import shutil
import subprocess

from .base import Check, CheckResult

MANAGERS = [
    ("apt-get", "sudo apt-get install -y {pkg}"),
    ("dnf", "sudo dnf install -y {pkg}"),
    ("pacman", "sudo pacman -S --noconfirm {pkg}"),
    ("zypper", "sudo zypper install -y {pkg}"),
]


def install_hint(package: str) -> str:
    for binary, template in MANAGERS:
        if shutil.which(binary):
            return template.format(pkg=package)
    return f"Install {package} with your system package manager."


class PipeWireCheck(Check):
    id = "pipewire"
    label = "PipeWire audio"
    description = "Captures every participant by mixing all audio sources."
    required = True

    def detect(self) -> CheckResult:
        missing = [b for b in ("pactl", "pw-record") if not shutil.which(b)]
        if missing:
            return CheckResult(
                status="missing",
                detail=(
                    f"Not found: {', '.join(missing)}. beyondMeetings needs PipeWire "
                    "for system-wide audio capture. On most desktops it is already "
                    "running; on servers or PulseAudio-only systems it is not "
                    "available and recording cannot work."
                ),
            )
        return CheckResult(status="ok", detail="pactl and pw-record found")


class FfmpegCheck(Check):
    id = "ffmpeg"
    label = "ffmpeg"
    description = "Compresses recordings before upload."
    required = True

    def detect(self) -> CheckResult:
        found = shutil.which("ffmpeg")
        if not found:
            return CheckResult(status="missing", detail=install_hint("ffmpeg"))
        return CheckResult(status="ok", detail=found)

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, **kwargs) -> CheckResult:
        command = install_hint("ffmpeg")
        if not command.startswith("sudo"):
            return CheckResult(status="missing", detail=command)
        proc = subprocess.run(command.split(), capture_output=True, text=True)
        if proc.returncode != 0:
            return CheckResult(
                status="missing",
                detail=f"Install failed. Run manually: {command}",
            )
        return self.detect()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_doctor_system.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/doctor/system.py tests/test_doctor_system.py
git commit -m "feat: PipeWire and ffmpeg checks"
```

---

## Task 3: Key checks with live validation

**Files:**
- Create: `src/beyondmeetings/doctor/keys.py`
- Test: `tests/test_doctor_keys.py`

A regex-valid key that the API rejects is the most common silent first-run failure. These probe for real.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_keys.py
import pytest

from beyondmeetings.doctor.keys import (
    GroqKeyCheck, ProviderKeyCheck, validate_anthropic_key, validate_groq_key,
)


def test_groq_validation_accepts_a_working_key(httpx_mock):
    httpx_mock.add_response(json={"data": []})
    assert validate_groq_key("gsk_good") == (True, "")


def test_groq_validation_rejects_a_bad_key(httpx_mock):
    httpx_mock.add_response(status_code=401, json={"error": {"message": "invalid"}})
    ok, detail = validate_groq_key("gsk_bad")
    assert ok is False
    assert "invalid" in detail


def test_groq_validation_reports_network_failure(httpx_mock):
    import httpx as _httpx
    httpx_mock.add_exception(_httpx.ConnectError("no route"))
    ok, detail = validate_groq_key("gsk_any")
    assert ok is False
    assert "no route" in detail


def test_anthropic_validation_accepts_a_working_key(httpx_mock):
    httpx_mock.add_response(json={"content": [{"type": "text", "text": "hi"}]})
    assert validate_anthropic_key("sk-good") == (True, "")


def test_anthropic_validation_rejects_a_bad_key(httpx_mock):
    httpx_mock.add_response(status_code=401, json={"error": {"message": "bad key"}})
    ok, detail = validate_anthropic_key("sk-bad")
    assert ok is False
    assert "bad key" in detail


def test_groq_check_missing_when_no_key_stored(tmp_path):
    check = GroqKeyCheck(secret_dir=tmp_path)
    assert check.detect().status == "missing"


def test_groq_check_ok_when_stored_key_validates(tmp_path, httpx_mock, monkeypatch):
    from beyondmeetings import secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", _BrokenKeyring())
    secrets_mod.set_secret("groq_api_key", "gsk_good", fallback_dir=tmp_path)
    httpx_mock.add_response(json={"data": []})
    assert GroqKeyCheck(secret_dir=tmp_path).detect().status == "ok"


def test_groq_check_broken_when_stored_key_rejected(tmp_path, httpx_mock, monkeypatch):
    from beyondmeetings import secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", _BrokenKeyring())
    secrets_mod.set_secret("groq_api_key", "gsk_bad", fallback_dir=tmp_path)
    httpx_mock.add_response(status_code=401, json={"error": {"message": "invalid"}})
    assert GroqKeyCheck(secret_dir=tmp_path).detect().status == "broken"


def test_groq_fix_stores_a_valid_key(tmp_path, httpx_mock, monkeypatch):
    from beyondmeetings import secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", _BrokenKeyring())
    httpx_mock.add_response(json={"data": []})
    httpx_mock.add_response(json={"data": []})
    check = GroqKeyCheck(secret_dir=tmp_path)
    assert check.fix(api_key="gsk_new").status == "ok"
    assert secrets_mod.get_secret("groq_api_key", fallback_dir=tmp_path) == "gsk_new"


def test_groq_fix_refuses_to_store_an_invalid_key(tmp_path, httpx_mock, monkeypatch):
    from beyondmeetings import secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", _BrokenKeyring())
    httpx_mock.add_response(status_code=401, json={"error": {"message": "nope"}})
    check = GroqKeyCheck(secret_dir=tmp_path)
    assert check.fix(api_key="gsk_bad").status != "ok"
    assert secrets_mod.get_secret("groq_api_key", fallback_dir=tmp_path) is None


def test_provider_check_exposes_a_secret_input_field(tmp_path):
    check = ProviderKeyCheck(provider="anthropic", secret_dir=tmp_path)
    assert check.inputs[0].secret is True


def test_provider_check_rejects_unknown_provider(tmp_path):
    with pytest.raises(ValueError):
        ProviderKeyCheck(provider="nope", secret_dir=tmp_path)


class _BrokenKeyring:
    """Forces the file fallback so tests never touch the real OS keyring."""

    def set_password(self, *a):
        raise RuntimeError("no backend")

    def get_password(self, *a):
        raise RuntimeError("no backend")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_doctor_keys.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.doctor.keys'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/doctor/keys.py
"""API key checks.

Keys are validated with a real request. "I pasted my key and nothing
happened" is the most common first-run failure in tools like this, and a
regex cannot catch a revoked or wrong-account key.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from ..labels import provider_label
from ..secrets import get_secret, set_secret
from .base import Check, CheckResult, InputField

TIMEOUT = 20.0


def _error_detail(response: httpx.Response) -> str:
    try:
        return response.json().get("error", {}).get("message", response.text[:200])
    except Exception:
        return response.text[:200]


def validate_groq_key(api_key: str) -> tuple[bool, str]:
    try:
        response = httpx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return False, f"Could not reach Groq: {exc}"
    if response.status_code == 200:
        return True, ""
    return False, _error_detail(response)


def validate_anthropic_key(api_key: str) -> tuple[bool, str]:
    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-opus-5",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return False, f"Could not reach Anthropic: {exc}"
    if response.status_code == 200:
        return True, ""
    return False, _error_detail(response)


VALIDATORS = {
    "anthropic": validate_anthropic_key,
    "openai": None,
    "gemini": None,
    "ollama": None,
}


class _KeyCheck(Check):
    secret_name: str

    def __init__(self, secret_dir: Path | None = None):
        self.secret_dir = secret_dir

    def _validate(self, api_key: str) -> tuple[bool, str]:
        raise NotImplementedError

    def detect(self) -> CheckResult:
        key = get_secret(self.secret_name, fallback_dir=self.secret_dir)
        if not key:
            return CheckResult(status="missing", detail="No key stored yet.")
        ok, detail = self._validate(key)
        if ok:
            return CheckResult(status="ok", detail="Key verified with a live call.")
        return CheckResult(status="broken", detail=f"Stored key rejected: {detail}")

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, api_key: str = "", **kwargs) -> CheckResult:
        api_key = api_key.strip()
        if not api_key:
            return CheckResult(status="missing", detail="No key provided.")
        ok, detail = self._validate(api_key)
        if not ok:
            return CheckResult(status="broken", detail=f"Key rejected: {detail}")
        set_secret(self.secret_name, api_key, fallback_dir=self.secret_dir)
        return self.detect()


class GroqKeyCheck(_KeyCheck):
    id = "groq_key"
    label = "Groq API key"
    description = "Transcribes your recordings. The free tier is ample."
    secret_name = "groq_api_key"
    inputs = [
        InputField(name="api_key", label="Groq API key",
                   placeholder="gsk_…", secret=True)
    ]

    def _validate(self, api_key: str) -> tuple[bool, str]:
        return validate_groq_key(api_key)


class ProviderKeyCheck(_KeyCheck):
    id = "provider_key"
    description = "Writes your meeting notes."

    def __init__(self, provider: str, secret_dir: Path | None = None):
        if provider not in VALIDATORS:
            raise ValueError(f"unknown provider: {provider}")
        super().__init__(secret_dir)
        self.provider = provider
        self.secret_name = f"{provider}_api_key"
        self.label = f"{provider_label(provider)} API key"
        self.inputs = [
            InputField(
                name="api_key",
                label=f"{provider_label(provider)} API key",
                placeholder="sk-…",
                secret=True,
            )
        ]

    def _validate(self, api_key: str) -> tuple[bool, str]:
        validator = VALIDATORS[self.provider]
        if validator is None:
            return False, (
                f"{provider_label(self.provider)} is not supported yet — "
                "it arrives in milestone 3."
            )
        return validator(api_key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_doctor_keys.py -v`
Expected: PASS — 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/doctor/keys.py tests/test_doctor_keys.py
git commit -m "feat: API key checks validated by live calls"
```

---

## Task 4: Obsidian and vault checks

**Files:**
- Create: `src/beyondmeetings/doctor/obsidian.py`, `src/beyondmeetings/doctor/vault.py`
- Test: `tests/test_doctor_obsidian.py`, `tests/test_doctor_vault.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_doctor_obsidian.py
from beyondmeetings.doctor.obsidian import ObsidianCheck


def test_ok_when_binary_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/obsidian")
    assert ObsidianCheck().detect().status == "ok"


def test_ok_when_installed_as_a_flatpak(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/flatpak" if n == "flatpak" else None)
    monkeypatch.setattr(
        "beyondmeetings.doctor.obsidian._flatpak_list",
        lambda: "md.obsidian.Obsidian\n",
    )
    assert ObsidianCheck().detect().status == "ok"


def test_missing_when_neither_present(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    monkeypatch.setattr("beyondmeetings.doctor.obsidian._flatpak_list", lambda: "")
    assert ObsidianCheck().detect().status == "missing"


def test_detail_explains_how_to_install_without_flatpak(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    monkeypatch.setattr("beyondmeetings.doctor.obsidian._flatpak_list", lambda: "")
    assert "obsidian.md" in ObsidianCheck().detect().detail


def test_is_fixable_only_when_flatpak_is_available(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: None)
    assert ObsidianCheck().fixable is False
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/flatpak")
    assert ObsidianCheck().fixable is True
```

```python
# tests/test_doctor_vault.py
from beyondmeetings.config import Config
from beyondmeetings.doctor.vault import VaultCheck


def test_missing_when_no_path_configured(tmp_path):
    assert VaultCheck(Config()).detect().status == "missing"


def test_broken_when_path_does_not_exist(tmp_path):
    check = VaultCheck(Config(vault_path=str(tmp_path / "nope")))
    assert check.detect().status == "broken"


def test_missing_when_path_exists_but_is_not_scaffolded(tmp_path):
    assert VaultCheck(Config(vault_path=str(tmp_path))).detect().status == "missing"


def test_ok_once_scaffolded(tmp_path):
    from beyondmeetings.vault.scaffold import scaffold_vault
    scaffold_vault(tmp_path)
    assert VaultCheck(Config(vault_path=str(tmp_path))).detect().status == "ok"


def test_fix_scaffolds_the_given_path(tmp_path):
    check = VaultCheck(Config())
    result = check.fix(vault_path=str(tmp_path))
    assert result.status == "ok"
    assert (tmp_path / "Home.md").is_file()
    assert (tmp_path / "Tasks" / "Task Board.md").is_file()


def test_fix_persists_the_path_into_config(tmp_path):
    cfg_path = tmp_path / "config.toml"
    vault = tmp_path / "vault"
    vault.mkdir()
    check = VaultCheck(Config(), config_path=cfg_path)
    check.fix(vault_path=str(vault))
    from beyondmeetings.config import load_config
    assert load_config(cfg_path).vault_path == str(vault)


def test_fix_refuses_a_path_that_does_not_exist(tmp_path):
    check = VaultCheck(Config())
    assert check.fix(vault_path=str(tmp_path / "absent")).status == "broken"


def test_fix_never_overwrites_an_existing_vault(tmp_path):
    (tmp_path / "Home.md").write_text("MY REAL HOME")
    VaultCheck(Config()).fix(vault_path=str(tmp_path))
    assert (tmp_path / "Home.md").read_text() == "MY REAL HOME"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_doctor_obsidian.py tests/test_doctor_vault.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/doctor/obsidian.py
"""Obsidian detection and flatpak installation."""
from __future__ import annotations

import shutil
import subprocess

from .base import Check, CheckResult

FLATPAK_ID = "md.obsidian.Obsidian"


def _flatpak_list() -> str:
    if not shutil.which("flatpak"):
        return ""
    return subprocess.run(
        ["flatpak", "list", "--app", "--columns=application"],
        capture_output=True, text=True, check=False,
    ).stdout


class ObsidianCheck(Check):
    id = "obsidian"
    label = "Obsidian"
    description = "Where your meeting notes and task board live."
    required = True

    def detect(self) -> CheckResult:
        binary = shutil.which("obsidian")
        if binary:
            return CheckResult(status="ok", detail=binary)
        if FLATPAK_ID in _flatpak_list():
            return CheckResult(status="ok", detail=f"flatpak: {FLATPAK_ID}")

        if shutil.which("flatpak"):
            detail = (
                "Not installed. beyondMeetings can install it from Flathub, "
                "or download it yourself from obsidian.md."
            )
        else:
            detail = (
                "Not installed, and flatpak is unavailable for automatic install. "
                "Download Obsidian from obsidian.md and install the .deb or AppImage."
            )
        return CheckResult(status="missing", detail=detail)

    @property
    def fixable(self) -> bool:
        return bool(shutil.which("flatpak"))

    def fix(self, **kwargs) -> CheckResult:
        proc = subprocess.run(
            ["flatpak", "install", "-y", "--noninteractive", "flathub", FLATPAK_ID],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            return CheckResult(
                status="missing",
                detail=f"Flatpak install failed: {proc.stderr[:300]}",
            )
        return self.detect()
```

```python
# src/beyondmeetings/doctor/vault.py
"""Vault path selection and scaffolding."""
from __future__ import annotations

from pathlib import Path

from ..config import Config, save_config
from ..vault.scaffold import scaffold_vault
from .base import Check, CheckResult, InputField


class VaultCheck(Check):
    id = "vault"
    label = "Obsidian vault"
    description = "Creates Meetings/, Tasks/Task Board.md and Home.md."
    required = True
    inputs = [
        InputField(name="vault_path", label="Vault folder",
                   placeholder="/home/you/Documents/Obsidian Vault")
    ]

    def __init__(self, config: Config, config_path: Path | None = None):
        self.config = config
        self.config_path = config_path

    def detect(self) -> CheckResult:
        if not self.config.vault_path:
            return CheckResult(status="missing", detail="No vault chosen yet.")
        vault = Path(self.config.vault_path)
        if not vault.is_dir():
            return CheckResult(
                status="broken", detail=f"{vault} does not exist."
            )
        if not (vault / "Home.md").is_file():
            return CheckResult(status="missing", detail="Vault not scaffolded yet.")
        return CheckResult(status="ok", detail=str(vault))

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, vault_path: str = "", **kwargs) -> CheckResult:
        target = Path(vault_path).expanduser() if vault_path else Path(
            self.config.vault_path or ""
        )
        if not vault_path and not self.config.vault_path:
            return CheckResult(status="missing", detail="No vault path provided.")
        if not target.is_dir():
            return CheckResult(
                status="broken",
                detail=f"{target} does not exist. Create it first, then retry.",
            )

        scaffold_vault(target)
        self.config.vault_path = str(target)
        save_config(self.config, self.config_path)
        return self.detect()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_doctor_obsidian.py tests/test_doctor_vault.py -v`
Expected: PASS — 13 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/doctor/obsidian.py src/beyondmeetings/doctor/vault.py tests/test_doctor_obsidian.py tests/test_doctor_vault.py
git commit -m "feat: Obsidian and vault checks"
```

---

## Task 5: Rules file generation

**Files:**
- Create: `src/beyondmeetings/rules.py`
- Test: `tests/test_rules.py`

One template, three filenames, marked generated. Spec §7 explains why.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rules.py
from beyondmeetings.rules import FILENAMES, render_rules, write_rules


def test_all_three_files_are_written(tmp_path):
    write_rules(tmp_path, vault_path="/v")
    for name in FILENAMES:
        assert (tmp_path / name).is_file()


def test_every_file_has_identical_content(tmp_path):
    write_rules(tmp_path, vault_path="/v")
    bodies = {(tmp_path / n).read_text() for n in FILENAMES}
    assert len(bodies) == 1


def test_content_is_marked_generated(tmp_path):
    write_rules(tmp_path, vault_path="/v")
    assert "do not edit" in (tmp_path / "CLAUDE.md").read_text().lower()


def test_rules_drive_the_cli_rather_than_reimplementing_it():
    text = render_rules(vault_path="/v")
    assert "beyondmeetings start" in text
    assert "beyondmeetings stop" in text


def test_rules_forbid_asking_for_a_meeting_name():
    text = render_rules(vault_path="/v")
    assert "never ask" in text.lower()


def test_vault_path_is_documented(tmp_path):
    assert "/home/x/Vault" in render_rules(vault_path="/home/x/Vault")


def test_link_convention_is_documented():
    assert "[[Meetings/YYYY-MM-DD/Meeting Name]]" in render_rules(vault_path="/v")


def test_existing_files_are_overwritten(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("stale content")
    write_rules(tmp_path, vault_path="/v")
    assert "stale content" not in (tmp_path / "CLAUDE.md").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.rules'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/rules.py
"""Generate agent rules files from a single template.

Three filenames, one body. They are thin drivers over the CLI: behaviour
lives in Python so every agent produces identical notes. Duplicated prose
rots — the original project's AGENTS.md drifted months out of date from its
own CLAUDE.md.
"""
from __future__ import annotations

from pathlib import Path

FILENAMES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")

TEMPLATE = """# beyondMeetings — Agent Instructions

<!-- GENERATED FILE — do not edit. Regenerate with `beyondmeetings setup`. -->
<!-- CLAUDE.md, AGENTS.md and GEMINI.md are identical copies of one template. -->

beyondMeetings records meetings, transcribes them, and writes structured notes
into an Obsidian vault. **All behaviour lives in the `beyondmeetings` command.**
Your job is to run it at the right moment — never to reimplement it.

## When the user says "start recording"

Run this immediately:

```bash
beyondmeetings start "[meeting name]"
```

**Never ask for a meeting name.** A meeting is already under way and every
second spent asking is audio lost. If no name was given, run `beyondmeetings
start` with no argument — it assigns a timestamp placeholder, and the real
title is derived from the transcript when notes are generated.

Then confirm: "Recording started. Tell me when to stop."

## When the user says "stop recording" or "generate notes"

```bash
beyondmeetings stop
```

This does everything: stops capture, transcribes, analyses the transcript,
writes the meeting note, adds tasks to the Task Board, updates Home.md, and
links follow-up meetings. It prints the transcript and note paths.

Long meetings can take a few minutes if the transcription API is rate-limited.
That is expected — do not re-run it.

## Regenerating notes for an existing transcript

```bash
beyondmeetings notes /path/to/transcript.txt
```

## Vault conventions

The vault is at `{vault_path}`.

| What | Where |
|---|---|
| Meeting notes | `Meetings/YYYY-MM-DD/[Meeting Name].md` |
| Task board | `Tasks/Task Board.md` |
| Dashboard | `Home.md` |

Notes are linked by full path with the date folder:
`[[Meetings/YYYY-MM-DD/Meeting Name]]`. The filename itself carries no date
prefix — the folder is the date.

**Do not hand-edit the Task Board counters.** They are computed.
"""


def render_rules(vault_path: str) -> str:
    return TEMPLATE.format(vault_path=vault_path)


def write_rules(target_dir: Path, vault_path: str) -> list[Path]:
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    body = render_rules(vault_path)
    written = []
    for name in FILENAMES:
        path = target_dir / name
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_rules.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/rules.py tests/test_rules.py
git commit -m "feat: generate agent rules files from one template"
```

---

## Task 6: Rules check and registry

**Files:**
- Create: `src/beyondmeetings/doctor/rules_check.py`, `src/beyondmeetings/doctor/registry.py`
- Test: `tests/test_doctor_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_registry.py
from beyondmeetings.config import Config
from beyondmeetings.doctor.registry import build_checks
from beyondmeetings.doctor.rules_check import RulesCheck


def test_rules_missing_when_files_absent(tmp_path):
    assert RulesCheck(Config(vault_path=str(tmp_path)), tmp_path).detect().status == "missing"


def test_rules_ok_after_fix(tmp_path):
    check = RulesCheck(Config(vault_path=str(tmp_path)), tmp_path)
    assert check.fix().status == "ok"
    assert (tmp_path / "CLAUDE.md").is_file()


def test_rules_not_required(tmp_path):
    assert RulesCheck(Config(), tmp_path).required is False


def test_registry_returns_checks_in_a_stable_order(tmp_path):
    ids = [c.id for c in build_checks(Config(), config_path=tmp_path / "c.toml")]
    assert ids == ["pipewire", "ffmpeg", "groq_key", "provider_key",
                   "obsidian", "vault", "rules"]


def test_registry_uses_the_configured_provider(tmp_path):
    checks = build_checks(Config(provider="anthropic"), config_path=tmp_path / "c.toml")
    provider_check = next(c for c in checks if c.id == "provider_key")
    assert "Claude" in provider_check.label


def test_registry_ids_are_unique(tmp_path):
    ids = [c.id for c in build_checks(Config(), config_path=tmp_path / "c.toml")]
    assert len(ids) == len(set(ids))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_doctor_registry.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/doctor/rules_check.py
"""Whether the generated agent rules files are present."""
from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..rules import FILENAMES, write_rules
from .base import Check, CheckResult


class RulesCheck(Check):
    id = "rules"
    label = "Agent rules files"
    description = "CLAUDE.md, AGENTS.md and GEMINI.md so agents can drive the CLI."
    required = False

    def __init__(self, config: Config, target_dir: Path):
        self.config = config
        self.target_dir = Path(target_dir)

    def detect(self) -> CheckResult:
        missing = [n for n in FILENAMES if not (self.target_dir / n).is_file()]
        if missing:
            return CheckResult(status="missing", detail=f"Not written: {', '.join(missing)}")
        return CheckResult(status="ok", detail=str(self.target_dir))

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, **kwargs) -> CheckResult:
        write_rules(self.target_dir, self.config.vault_path or "(vault not set)")
        return self.detect()
```

```python
# src/beyondmeetings/doctor/registry.py
"""The ordered list of prerequisite checks."""
from __future__ import annotations

from pathlib import Path

from ..config import Config, DEFAULT_CONFIG_PATH
from .base import Check
from .keys import GroqKeyCheck, ProviderKeyCheck
from .obsidian import ObsidianCheck
from .rules_check import RulesCheck
from .system import FfmpegCheck, PipeWireCheck
from .vault import VaultCheck


def build_checks(
    config: Config,
    config_path: Path | None = None,
    secret_dir: Path | None = None,
) -> list[Check]:
    config_path = config_path or DEFAULT_CONFIG_PATH
    rules_dir = Path(config.vault_path) if config.vault_path else config_path.parent
    return [
        PipeWireCheck(),
        FfmpegCheck(),
        GroqKeyCheck(secret_dir=secret_dir),
        ProviderKeyCheck(provider=config.provider, secret_dir=secret_dir),
        ObsidianCheck(),
        VaultCheck(config, config_path=config_path),
        RulesCheck(config, target_dir=rules_dir),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_doctor_registry.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/doctor tests/test_doctor_registry.py
git commit -m "feat: rules check and check registry"
```

---

## Task 7: Server API

**Files:**
- Modify: `pyproject.toml` (add `fastapi`, `uvicorn`)
- Create: `src/beyondmeetings/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server.py
import pytest
from fastapi.testclient import TestClient

from beyondmeetings.config import Config
from beyondmeetings.doctor.base import Check, CheckResult, InputField
from beyondmeetings.server import create_app


class StubCheck(Check):
    id = "stub"
    label = "Stub"
    required = True
    inputs = [InputField(name="value", label="Value")]

    def __init__(self):
        self.status = "missing"
        self.received = None

    def detect(self):
        return CheckResult(status=self.status)

    @property
    def fixable(self):
        return True

    def fix(self, **kwargs):
        self.received = kwargs
        self.status = "ok"
        return CheckResult(status="ok")


@pytest.fixture
def client(tmp_path):
    check = StubCheck()
    app = create_app(
        config=Config(),
        config_path=tmp_path / "config.toml",
        checks_factory=lambda cfg: [check],
    )
    app.state.stub = check
    return TestClient(app)


def test_status_returns_rows_and_percent(client):
    body = client.get("/api/status").json()
    assert body["percent"] == 0
    assert body["checks"][0]["id"] == "stub"


def test_fix_dispatches_to_the_named_check(client):
    response = client.post("/api/fix/stub", json={"value": "hello"})
    assert response.status_code == 200
    assert client.app.state.stub.received == {"value": "hello"}


def test_percent_updates_after_a_successful_fix(client):
    client.post("/api/fix/stub", json={})
    assert client.get("/api/status").json()["percent"] == 100


def test_fix_on_unknown_check_returns_404(client):
    assert client.post("/api/fix/nope", json={}).status_code == 404


def test_settings_persists_provider_choice(client, tmp_path):
    client.post("/api/settings", json={"provider": "openai"})
    from beyondmeetings.config import load_config
    assert load_config(tmp_path / "config.toml").provider == "openai"


def test_settings_rejects_unknown_field(client):
    assert client.post("/api/settings", json={"nope": 1}).status_code == 422


def test_setup_page_is_served(client):
    response = client.get("/setup")
    assert response.status_code == 200
    assert "beyondMeetings" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.server'`

- [ ] **Step 3: Write minimal implementation**

Add to `pyproject.toml` dependencies: `"fastapi>=0.110"`, `"uvicorn>=0.27"`. Then:

```python
# src/beyondmeetings/server.py
"""Local web server for the setup wizard.

The same Check objects back both this API and `beyondmeetings doctor`, so the
browser and the terminal can never disagree about what is wrong.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .config import Config, DEFAULT_CONFIG_PATH, load_config, save_config
from .doctor.base import Check, completion_percent, run_all
from .doctor.registry import build_checks

WEB_DIR = Path(__file__).parent / "web"


class SettingsPatch(BaseModel, extra="forbid"):
    provider: str | None = None
    spoken_language: str | None = None
    notes_language: str | None = None
    projects: list[str] | None = None
    transcriber: str | None = None


def create_app(
    config: Config | None = None,
    config_path: Path | None = None,
    checks_factory: Callable[[Config], list[Check]] | None = None,
) -> FastAPI:
    config_path = config_path or DEFAULT_CONFIG_PATH
    state = {"config": config if config is not None else load_config(config_path)}
    factory = checks_factory or (
        lambda cfg: build_checks(cfg, config_path=config_path)
    )

    app = FastAPI(title="beyondMeetings setup")

    def current_checks() -> list[Check]:
        return factory(state["config"])

    @app.get("/api/status")
    def status():
        rows = run_all(current_checks())
        return {"percent": completion_percent(rows), "checks": rows,
                "config": state["config"].model_dump()}

    @app.post("/api/fix/{check_id}")
    def fix(check_id: str, payload: dict | None = None):
        check = next((c for c in current_checks() if c.id == check_id), None)
        if check is None:
            raise HTTPException(status_code=404, detail=f"no such check: {check_id}")
        result = check.fix(**(payload or {}))
        rows = run_all(current_checks())
        return {"result": result.model_dump(), "percent": completion_percent(rows),
                "checks": rows}

    @app.post("/api/settings")
    def settings(patch: SettingsPatch):
        updated = state["config"].model_copy(
            update={k: v for k, v in patch.model_dump().items() if v is not None}
        )
        save_config(updated, config_path)
        state["config"] = updated
        return {"config": updated.model_dump()}

    @app.get("/setup", response_class=HTMLResponse)
    @app.get("/", response_class=HTMLResponse)
    def page():
        return (WEB_DIR / "setup.html").read_text(encoding="utf-8")

    @app.get("/setup.css")
    def css():
        from fastapi.responses import Response
        return Response((WEB_DIR / "setup.css").read_text(), media_type="text/css")

    @app.get("/setup.js")
    def js():
        from fastapi.responses import Response
        return Response(
            (WEB_DIR / "setup.js").read_text(), media_type="application/javascript"
        )

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pip install -q -e ".[dev]" && .venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/beyondmeetings/server.py tests/test_server.py
git commit -m "feat: setup server API"
```

---

## Task 8: Wizard UI

**Files:**
- Create: `src/beyondmeetings/web/setup.html`, `setup.css`, `setup.js`
- Modify: `pyproject.toml` (include web assets in the wheel)

Single-screen checklist with a completion ring, per-row Fix buttons, and in-place input panels. No build step, no CDN.

- [ ] **Step 1: Write `setup.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>beyondMeetings — Setup</title>
  <link rel="stylesheet" href="/setup.css">
</head>
<body>
  <main>
    <header class="hero">
      <div class="ring" id="ring"><span id="pct">0%</span></div>
      <div>
        <h1>beyondMeetings</h1>
        <p class="sub" id="summary">Checking your system…</p>
        <button id="fixall" class="btn primary" hidden>Fix everything I can</button>
      </div>
    </header>

    <section class="rows" id="rows" aria-live="polite"></section>

    <footer class="done" id="done" hidden>
      <h2>You're ready.</h2>
      <p>Start a meeting from the terminal:</p>
      <code>beyondmeetings start "My meeting"</code>
    </footer>
  </main>
  <script src="/setup.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `setup.css`**

```css
:root {
  --bg: #fbfbfd; --fg: #16161a; --muted: #6b6b76;
  --line: #e3e3e8; --card: #fff;
  --accent: #6366f1; --ok: #16a34a; --bad: #dc2626;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131316; --fg: #ededf0; --muted: #9a9aa5;
    --line: #2a2a31; --card: #1b1b20;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 20px; background: var(--bg); color: var(--fg);
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, sans-serif;
}
main { max-width: 720px; margin: 0 auto; }
h1 { margin: 0 0 4px; font-size: 26px; letter-spacing: -0.02em; }
.sub { margin: 0; color: var(--muted); font-size: 14px; }
.hero { display: flex; align-items: center; gap: 26px; margin-bottom: 30px; }
.ring {
  width: 108px; height: 108px; border-radius: 50%; flex: none;
  display: grid; place-items: center;
  background: conic-gradient(var(--accent) 0% 0%, var(--line) 0% 100%);
  transition: background .45s ease;
}
.ring span {
  width: 84px; height: 84px; border-radius: 50%; background: var(--bg);
  display: grid; place-items: center; font-size: 21px; font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.rows {
  border: 1px solid var(--line); border-radius: 12px;
  overflow: hidden; background: var(--card);
}
.row {
  display: flex; align-items: flex-start; gap: 12px; padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}
.row:last-child { border-bottom: 0; }
.dot { margin-top: 3px; font-size: 15px; line-height: 1; flex: none; width: 16px; }
.dot.ok { color: var(--ok); } .dot.bad { color: var(--bad); }
.dot.optional { color: var(--muted); }
.meta { flex: 1; min-width: 0; }
.name { font-weight: 600; }
.tag {
  font-size: 10.5px; text-transform: uppercase; letter-spacing: .07em;
  color: var(--muted); border: 1px solid var(--line);
  padding: 1px 6px; border-radius: 20px; margin-left: 7px;
}
.detail { color: var(--muted); font-size: 13px; margin-top: 2px; word-wrap: break-word; }
.btn {
  font: inherit; font-size: 13px; padding: 6px 13px; border-radius: 7px;
  border: 1px solid var(--line); background: transparent; color: var(--fg);
  cursor: pointer; flex: none;
}
.btn:hover:not(:disabled) { border-color: var(--accent); }
.btn:disabled { opacity: .5; cursor: default; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.panel {
  display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap;
}
.panel input {
  font: inherit; font-size: 13px; padding: 7px 10px; border-radius: 7px;
  border: 1px solid var(--line); background: var(--bg); color: var(--fg);
  flex: 1; min-width: 200px;
}
.done {
  margin-top: 26px; padding: 22px; border-radius: 12px;
  border: 1px solid var(--ok); background: color-mix(in srgb, var(--ok) 8%, transparent);
}
.done h2 { margin: 0 0 6px; font-size: 18px; }
.done code {
  display: inline-block; margin-top: 8px; padding: 8px 12px;
  background: var(--card); border: 1px solid var(--line); border-radius: 7px;
  font-size: 13px;
}
</style>
```

- [ ] **Step 3: Write `setup.js`**

```javascript
const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

function render(state) {
  const pct = state.percent;
  $("pct").textContent = `${pct}%`;
  $("ring").style.background =
    `conic-gradient(var(--accent) 0% ${pct}%, var(--line) ${pct}% 100%)`;

  const blocking = state.checks.filter((c) => c.required && c.status !== "ok");
  $("summary").textContent = blocking.length
    ? `${blocking.length} item${blocking.length > 1 ? "s" : ""} still need attention`
    : "Everything required is in place";

  const autoFixable = state.checks.filter(
    (c) => c.status !== "ok" && c.fixable && c.inputs.length === 0
  );
  $("fixall").hidden = autoFixable.length === 0;
  $("done").hidden = pct !== 100;

  $("rows").replaceChildren(...state.checks.map(renderRow));
}

function renderRow(check) {
  const row = document.createElement("div");
  row.className = "row";

  const dot = document.createElement("span");
  const ok = check.status === "ok";
  dot.className = `dot ${ok ? "ok" : check.required ? "bad" : "optional"}`;
  dot.textContent = ok ? "✓" : check.required ? "✗" : "○";
  row.append(dot);

  const meta = document.createElement("div");
  meta.className = "meta";
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = check.label;
  if (!check.required) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = "optional";
    name.append(tag);
  }
  meta.append(name);

  const detail = document.createElement("div");
  detail.className = "detail";
  detail.textContent = check.detail || check.description;
  meta.append(detail);

  if (!ok && check.inputs.length) meta.append(renderPanel(check));
  row.append(meta);

  if (!ok && check.fixable && !check.inputs.length) {
    const btn = document.createElement("button");
    btn.className = "btn";
    btn.textContent = "Fix";
    btn.onclick = () => runFix(check.id, {}, btn);
    row.append(btn);
  }
  return row;
}

function renderPanel(check) {
  const panel = document.createElement("div");
  panel.className = "panel";
  const fields = {};
  for (const input of check.inputs) {
    const el = document.createElement("input");
    el.type = input.secret ? "password" : "text";
    el.placeholder = input.placeholder || input.label;
    el.setAttribute("aria-label", input.label);
    fields[input.name] = el;
    panel.append(el);
  }
  const btn = document.createElement("button");
  btn.className = "btn primary";
  btn.textContent = "Save & verify";
  btn.onclick = () => {
    const payload = {};
    for (const [k, el] of Object.entries(fields)) payload[k] = el.value;
    runFix(check.id, payload, btn);
  };
  panel.append(btn);
  return panel;
}

async function runFix(id, payload, btn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Working…";
  try {
    render(await api(`/api/fix/${id}`, payload));
  } catch (err) {
    btn.disabled = false;
    btn.textContent = original;
    alert(`Could not complete: ${err.message}`);
  }
}

$("fixall").onclick = async () => {
  const btn = $("fixall");
  btn.disabled = true;
  btn.textContent = "Working…";
  let state = await api("/api/status");
  for (const check of state.checks) {
    if (check.status !== "ok" && check.fixable && !check.inputs.length) {
      state = await api(`/api/fix/${check.id}`, {});
    }
  }
  btn.disabled = false;
  btn.textContent = "Fix everything I can";
  render(state);
};

api("/api/status").then(render);
```

- [ ] **Step 4: Include assets in the wheel and verify the page loads**

Add to `pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/beyondmeetings/web" = "beyondmeetings/web"
```

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS — 7 passed, including `test_setup_page_is_served`

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/web pyproject.toml
git commit -m "feat: setup wizard UI"
```

---

## Task 9: CLI `doctor` and `setup`

**Files:**
- Modify: `src/beyondmeetings/cli.py`
- Test: `tests/test_cli_doctor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_doctor.py
from beyondmeetings.cli import build_parser, format_doctor_report


ROWS = [
    {"id": "a", "label": "PipeWire", "status": "ok", "detail": "found",
     "required": True, "fixable": False, "description": "", "inputs": []},
    {"id": "b", "label": "ffmpeg", "status": "missing", "detail": "run apt",
     "required": True, "fixable": True, "description": "", "inputs": []},
    {"id": "c", "label": "Rules", "status": "missing", "detail": "",
     "required": False, "fixable": True, "description": "", "inputs": []},
]


def test_doctor_subcommand_parses():
    assert build_parser().parse_args(["doctor"]).command == "doctor"


def test_setup_subcommand_parses():
    args = build_parser().parse_args(["setup"])
    assert args.command == "setup"
    assert args.port == 7788


def test_setup_accepts_a_custom_port():
    assert build_parser().parse_args(["setup", "--port", "9000"]).port == 9000


def test_report_shows_percent():
    assert "50%" in format_doctor_report(ROWS)


def test_report_marks_each_status():
    text = format_doctor_report(ROWS)
    assert "✓ PipeWire" in text
    assert "✗ ffmpeg" in text


def test_report_labels_optional_rows():
    assert "optional" in format_doctor_report(ROWS)


def test_report_includes_detail_text():
    assert "run apt" in format_doctor_report(ROWS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_doctor.py -v`
Expected: FAIL — `ImportError: cannot import name 'format_doctor_report'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/beyondmeetings/cli.py` — new imports, parser entries, report formatter, and command branches:

```python
# add near the other imports
import webbrowser

from .config import DEFAULT_CONFIG_PATH
from .doctor.base import completion_percent, run_all
from .doctor.registry import build_checks


def format_doctor_report(rows: list[dict]) -> str:
    lines = [f"beyondMeetings — {completion_percent(rows)}% ready", ""]
    for row in rows:
        mark = "✓" if row["status"] == "ok" else "✗"
        suffix = "" if row["required"] else "  (optional)"
        lines.append(f"  {mark} {row['label']}{suffix}")
        if row["detail"]:
            lines.append(f"      {row['detail']}")
    return "\n".join(lines)
```

In `build_parser()`, before `return parser`:

```python
    sub.add_parser("doctor", help="check prerequisites")

    setup = sub.add_parser("setup", help="open the setup wizard")
    setup.add_argument("--port", type=int, default=7788)
    setup.add_argument("--no-browser", action="store_true")
```

In `main()`, before the final `return 1`:

```python
    if args.command == "doctor":
        rows = run_all(build_checks(config, config_path=DEFAULT_CONFIG_PATH))
        print(format_doctor_report(rows))
        return 0 if completion_percent(rows) == 100 else 1

    if args.command == "setup":
        import uvicorn

        from .server import create_app

        url = f"http://127.0.0.1:{args.port}/setup"
        print(f"Setup wizard: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        uvicorn.run(
            create_app(config_path=DEFAULT_CONFIG_PATH),
            host="127.0.0.1", port=args.port, log_level="warning",
        )
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_doctor.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/cli.py tests/test_cli_doctor.py
git commit -m "feat: doctor and setup CLI commands"
```

---

## Task 10: `install.sh`

**Files:**
- Create: `install.sh`
- Test: `tests/test_install_sh.py`

Prefers system Python, falls back to `uv`. The venv probe must *attempt* a venv — a version string does not reveal a missing `python3-venv`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_install_sh.py
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "install.sh"


def _run(args, env=None):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, env=env,
    )


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111


def test_script_passes_shellcheck_if_available():
    if not shutil.which("shellcheck"):
        return
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_script_is_syntactically_valid():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_help_lists_the_no_uv_flag():
    assert "--no-uv" in _run(["--help"]).stdout


def test_dry_run_reports_the_chosen_interpreter():
    out = _run(["--dry-run"]).stdout
    assert "python" in out.lower()


def test_no_uv_with_unusable_python_prints_a_distro_hint(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "python3").write_text("#!/bin/sh\nexit 1\n")
    (fake_bin / "python3").chmod(0o755)
    env = {"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": str(tmp_path)}
    proc = _run(["--no-uv", "--dry-run"], env=env)
    assert proc.returncode != 0
    assert "python3-venv" in proc.stdout + proc.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_install_sh.py -v`
Expected: FAIL — `assert SCRIPT.is_file()`

- [ ] **Step 3: Write minimal implementation**

```bash
#!/usr/bin/env bash
# beyondMeetings installer.
#
# Prefers a usable system Python; falls back to uv, which ships its own
# CPython. The venv probe actually creates one — python3-venv can be missing
# on a perfectly modern Python, and a version check would not notice.
set -euo pipefail

MIN_MAJOR=3
MIN_MINOR=10
PREFIX="${BEYONDMEETINGS_HOME:-$HOME/.local/share/beyondmeetings}"
BIN_DIR="$HOME/.local/bin"
REPO="${BEYONDMEETINGS_REPO:-https://github.com/REPLACE_ME/beyondmeetings}"

USE_UV=1
DRY_RUN=0

usage() {
  cat <<'EOF'
beyondMeetings installer

  --no-uv      Never download uv. If system Python is unusable, print the
               distro-specific fix and exit.
  --dry-run    Report what would be used, then stop.
  --help       Show this message.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --no-uv) USE_UV=0 ;;
    --dry-run) DRY_RUN=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

say() { printf '  %s\n' "$1"; }

python_is_usable() {
  local py="$1"
  command -v "$py" >/dev/null 2>&1 || return 1
  "$py" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_MAJOR,$MIN_MINOR) else 1)" \
    >/dev/null 2>&1 || return 1
  # A version check does not prove venv works — build one and see.
  local probe
  probe="$(mktemp -d)"
  if "$py" -m venv "$probe/v" >/dev/null 2>&1; then
    rm -rf "$probe"; return 0
  fi
  rm -rf "$probe"; return 1
}

venv_hint() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "sudo apt-get install -y python3-venv python3-pip"
  elif command -v dnf >/dev/null 2>&1; then
    echo "sudo dnf install -y python3 python3-pip"
  elif command -v pacman >/dev/null 2>&1; then
    echo "sudo pacman -S --noconfirm python python-pip"
  else
    echo "Install Python ${MIN_MAJOR}.${MIN_MINOR}+ including the venv module."
  fi
}

echo "beyondMeetings installer"
echo

INTERPRETER=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if python_is_usable "$candidate"; then
    INTERPRETER="$candidate"
    say "Using system Python: $($candidate --version 2>&1)"
    break
  fi
done

USING_UV=0
if [ -z "$INTERPRETER" ]; then
  say "No usable Python ${MIN_MAJOR}.${MIN_MINOR}+ with venv support found."
  if [ "$USE_UV" -eq 0 ]; then
    echo
    echo "Fix it with:" >&2
    echo "  $(venv_hint)" >&2
    echo "(python3-venv is a separate package on Debian/Ubuntu.)" >&2
    exit 1
  fi
  say "Falling back to uv, which installs its own Python."
  USING_UV=1
fi

if [ "$DRY_RUN" -eq 1 ]; then
  if [ "$USING_UV" -eq 1 ]; then
    echo "Dry run: would bootstrap uv and use its bundled python."
  else
    echo "Dry run: would use $INTERPRETER at $(command -v "$INTERPRETER")."
  fi
  exit 0
fi

mkdir -p "$PREFIX" "$BIN_DIR"

if [ "$USING_UV" -eq 1 ]; then
  if ! command -v uv >/dev/null 2>&1; then
    say "Downloading uv…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
  uv python install "${MIN_MAJOR}.${MIN_MINOR}"
  uv venv --python "${MIN_MAJOR}.${MIN_MINOR}" "$PREFIX/venv"
else
  "$INTERPRETER" -m venv "$PREFIX/venv"
fi

say "Installing beyondMeetings…"
"$PREFIX/venv/bin/python" -m pip install --quiet --upgrade pip
if [ -f "$(dirname "$0")/pyproject.toml" ]; then
  "$PREFIX/venv/bin/python" -m pip install --quiet "$(dirname "$0")"
else
  "$PREFIX/venv/bin/python" -m pip install --quiet "beyondmeetings @ git+$REPO"
fi

ln -sf "$PREFIX/venv/bin/beyondmeetings" "$BIN_DIR/beyondmeetings"
say "Installed to $BIN_DIR/beyondmeetings"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "Note: $BIN_DIR is not on your PATH — add it to your shell profile." ;;
esac

echo
say "Opening the setup wizard…"
exec "$BIN_DIR/beyondmeetings" setup
```

- [ ] **Step 4: Run test to verify it passes**

```bash
chmod +x install.sh
.venv/bin/python -m pytest tests/test_install_sh.py -v
```
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_install_sh.py
git commit -m "feat: installer with system-python-or-uv bootstrap"
```

---

## Task 11: Project documentation

**Files:**
- Create: `README.md`, `LICENSE`, `CONTRIBUTING.md`
- Test: `tests/test_docs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_docs.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_exists_and_shows_the_install_command():
    text = (ROOT / "README.md").read_text()
    assert "install.sh" in text
    assert "beyondmeetings start" in text


def test_readme_states_the_linux_only_limitation():
    assert "Linux" in (ROOT / "README.md").read_text()


def test_readme_documents_the_providers():
    text = (ROOT / "README.md").read_text()
    for provider in ("Claude", "ChatGPT", "Gemini", "Ollama"):
        assert provider in text


def test_license_is_present_and_not_a_placeholder():
    text = (ROOT / "LICENSE").read_text()
    assert "MIT" in text
    assert "REPLACE" not in text


def test_contributing_documents_the_clone_path_and_tests():
    text = (ROOT / "CONTRIBUTING.md").read_text()
    assert "git clone" in text
    assert "pytest" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_docs.py -v`
Expected: FAIL — `FileNotFoundError: README.md`

- [ ] **Step 3: Write the three documents**

`README.md` covers: what it is, the one-line install, a screenshot placeholder, the Linux-only caveat with a pointer to `audio/base.py` for porters, provider table (Claude recommended; Ollama weaker on code-mixed transcripts), where files land, and a privacy note that audio goes to Groq unless whisper.cpp is chosen. `LICENSE` is the MIT text with the correct year and author. `CONTRIBUTING.md` covers `git clone && ./install.sh`, `pytest`, the fact that `audio/` is manually tested, and how to add a provider by implementing `LLMProvider`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_docs.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add README.md LICENSE CONTRIBUTING.md tests/test_docs.py
git commit -m "docs: README, LICENSE and CONTRIBUTING"
```

---

## Task 12: Full suite and tracker

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — all tests, zero failures

- [ ] **Step 2: Exercise the wizard end-to-end by hand**

```bash
.venv/bin/beyondmeetings doctor
.venv/bin/beyondmeetings setup --no-browser
```
Open `http://127.0.0.1:7788/setup`. Confirm: the ring shows a real percentage; rows reflect this machine; the ffmpeg row shows ✓; entering a bad Groq key is rejected with the API's own message; a good key flips the row to ✓ and the ring advances.

- [ ] **Step 3: Verify `doctor` and the wizard agree**

Run both and confirm identical statuses. They share the check objects, so a disagreement means a caching bug.

- [ ] **Step 4: Update `PROGRESS.md`**

Tick milestone 2 items, set milestone 2 `[x]` and milestone 3 `[~]`, append a session-log line, and record any bugs found during implementation.

- [ ] **Step 5: Commit**

```bash
git add PROGRESS.md
git commit -m "docs: milestone 2 complete"
```

---

## Self-Review

**Spec coverage:** §6 checks 1–7 → Tasks 2, 3, 4, 6. §6 live key validation → Task 3. §6 checklist form with % ring → Task 8. §7 generated rules files → Task 5. §11 curl|bash + Python bootstrap → Task 10. §12 testing → every task.

**Deliberately deferred:** check 8 (MCP registration) and the provider picker UI move to milestone 3, where the other three providers land — a picker offering providers that cannot yet write notes would be a trap. `ProviderKeyCheck` already returns a clear "arrives in milestone 3" message for them. Check 9 (tray autostart) belongs with the tray in milestone 4.

**Placeholder scan:** `REPLACE_ME` in `install.sh`'s `REPO` default is intentional and must be set when the GitHub repo exists — it is listed as a release blocker in `PROGRESS.md`. `test_license_is_present_and_not_a_placeholder` guards the LICENSE.

**Type consistency:** `CheckResult`/`Check`/`InputField` defined in Task 1, used identically in Tasks 2–6. `run_all` returns dicts with the same keys consumed by `server.py` (Task 7), `setup.js` (Task 8) and `format_doctor_report` (Task 9). `build_checks(config, config_path, secret_dir)` signature matches between Tasks 6, 7 and 9.
