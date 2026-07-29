# beyondMeetings Milestone 1 — Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `beyondmeetings start "name"` then `beyondmeetings stop` records a meeting, transcribes it, and writes a correct Obsidian note, Task Board entries, and Home.md update — no UI, no wizard, Claude only.

**Architecture:** The LLM does judgment only and returns a single JSON object conforming to `MeetingNote`. Every file write is deterministic Python in `vault/`. Audio capture, transcription, and note generation sit behind interfaces (`Recorder`, `Transcriber`, `LLMProvider`) so milestones 3–4 add files rather than edit them.

**Tech Stack:** Python 3.10+, pydantic v2 (schema + validation), httpx (HTTP), keyring (secrets), pytest. Audio via PipeWire CLI tools (`pactl`, `pw-record`) and `ffmpeg`, both invoked as subprocesses.

**Spec:** `docs/superpowers/specs/2026-07-30-beyondmeetings-setup-design.md`
**Tracker:** update `PROGRESS.md` checkboxes as tasks complete.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/beyondmeetings/config.py` | Load/save TOML config; get/set secrets via keyring |
| `src/beyondmeetings/models.py` | `MeetingNote`, `ActionItem`, `Section`, `MeetingRef` — the data contract |
| `src/beyondmeetings/llm/base.py` | `LLMProvider` interface + `parse_meeting_note()` JSON repair |
| `src/beyondmeetings/llm/anthropic.py` | Claude adapter |
| `src/beyondmeetings/prompts.py` | Analysis prompt assembly (ports every CLAUDE.md rule) |
| `src/beyondmeetings/vault/paths.py` | Filename sanitising, wikilink construction, vault path resolution |
| `src/beyondmeetings/vault/scaffold.py` | Idempotent creation of `Home.md`, `Tasks/Task Board.md`, `Meetings/` |
| `src/beyondmeetings/vault/note.py` | Render a `MeetingNote` to markdown |
| `src/beyondmeetings/vault/taskboard.py` | Insert tasks, recompute counters |
| `src/beyondmeetings/vault/home.py` | Prepend Recent entry, sync counters, bump `updated:` |
| `src/beyondmeetings/vault/followup.py` | Gather candidates; write frontmatter, callout, back-link |
| `src/beyondmeetings/transcribe/base.py` | `Transcriber` interface |
| `src/beyondmeetings/transcribe/groq.py` | Groq Whisper adapter, chunking + backoff |
| `src/beyondmeetings/audio/base.py` | `Recorder` interface + `RecordingState` |
| `src/beyondmeetings/audio/pipewire.py` | Linux capture: null-sink mix, segment rollover |
| `src/beyondmeetings/pipeline.py` | Orchestrates stop → transcribe → analyse → write |
| `src/beyondmeetings/cli.py` | `start` / `stop` / `notes` |

**Vault formats are load-bearing.** They were read from the live vault, not from CLAUDE.md — which is out of date. Note in particular that Task Board entries use **nested** blockquotes (`> >`), and that note titles are sanitised for filenames (`—` → `-`).

---

## Task 1: Project skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/beyondmeetings/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smoke.py
import beyondmeetings


def test_package_exposes_version():
    assert beyondmeetings.__version__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings'`

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[project]
name = "beyondmeetings"
version = "0.1.0"
description = "Local meeting recorder, transcriber and note generator for Obsidian"
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2.0",
    "httpx>=0.27",
    "keyring>=24.0",
    "tomli-w>=1.0",
]

[project.scripts]
beyondmeetings = "beyondmeetings.cli:main"

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-httpx>=0.30"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/beyondmeetings"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```python
# src/beyondmeetings/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
.venv/bin/python -m pytest tests/test_smoke.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/beyondmeetings/__init__.py tests/test_smoke.py
git commit -m "feat: project skeleton"
```

---

## Task 2: Data contract (`models.py`)

**Files:**
- Create: `src/beyondmeetings/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
import pytest
from pydantic import ValidationError

from beyondmeetings.models import ActionItem, MeetingNote, MeetingRef


def test_meeting_note_minimal_defaults():
    note = MeetingNote(title="Standup", date="2026-07-30", executive_summary="Short.")
    assert note.tags == []
    assert note.action_items == []
    assert note.is_informal is False
    assert note.follow_up_of is None


def test_action_item_priority_defaults_to_medium():
    item = ActionItem(task="Ship it")
    assert item.priority == "MEDIUM"
    assert item.owner is None


def test_action_item_rejects_unknown_priority():
    with pytest.raises(ValidationError):
        ActionItem(task="Ship it", priority="URGENT")


def test_meeting_ref_round_trips_through_id():
    ref = MeetingRef(date="2026-07-29", title="Design QA Review")
    assert ref.id == "2026-07-29/Design QA Review"
    assert MeetingRef.from_id(ref.id) == ref


def test_meeting_ref_from_id_rejects_malformed():
    with pytest.raises(ValueError):
        MeetingRef.from_id("no-slash-here")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.models'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/models.py
"""The data contract between the LLM and the vault writers.

The LLM returns exactly one MeetingNote as JSON. Everything downstream is
deterministic Python that reads this object — no model output ever reaches
the filesystem unvalidated.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Priority = Literal["HIGH", "MEDIUM", "LOW"]


class MeetingRef(BaseModel):
    """Identifies a meeting note by its date folder and display title."""

    date: str
    title: str

    @property
    def id(self) -> str:
        return f"{self.date}/{self.title}"

    @classmethod
    def from_id(cls, value: str) -> "MeetingRef":
        date, sep, title = value.partition("/")
        if not sep or not title:
            raise ValueError(f"malformed meeting id: {value!r}")
        return cls(date=date, title=title)


class ActionItem(BaseModel):
    task: str
    owner: str | None = None
    due: str | None = None
    project: str | None = None
    priority: Priority = "MEDIUM"


class Section(BaseModel):
    """Free-form narrative content only.

    Decisions, open questions, risks and action items are typed fields on
    MeetingNote and must never be duplicated here — each is rendered under
    its own heading by vault/note.py.
    """

    heading: str
    bullets: list[str] = Field(default_factory=list)


class MeetingNote(BaseModel):
    title: str
    date: str
    tags: list[str] = Field(default_factory=list)
    attendees: list[str] = Field(default_factory=list)
    executive_summary: str
    sections: list[Section] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    transcription_note: str | None = None
    is_informal: bool = False
    follow_up_of: str | None = None
    one_line_summary: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/models.py tests/test_models.py
git commit -m "feat: MeetingNote data contract"
```

---

## Task 3: Config file

**Files:**
- Create: `src/beyondmeetings/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from beyondmeetings.config import Config, load_config, save_config


def test_load_returns_defaults_when_file_absent(tmp_path):
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.provider == "anthropic"
    assert cfg.spoken_language == "auto"
    assert cfg.notes_language == "English"
    assert cfg.projects == []
    assert cfg.segment_minutes == 50


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(vault_path="/home/x/Vault", projects=["Acme", "Zenith"])
    save_config(cfg, path)
    assert load_config(path) == cfg


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deep" / "config.toml"
    save_config(Config(), path)
    assert path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/config.py
"""Non-secret configuration. Secrets live in the OS keyring — see secrets.py."""
from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "beyondmeetings" / "config.toml"
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "beyondmeetings"


class Config(BaseModel):
    vault_path: str = ""
    provider: str = "anthropic"
    model: str = ""
    transcriber: str = "groq"
    spoken_language: str = "auto"
    notes_language: str = "English"
    projects: list[str] = Field(default_factory=list)
    segment_minutes: int = 50
    data_dir: str = str(DEFAULT_DATA_DIR)


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return Config()
    with path.open("rb") as fh:
        return Config(**tomllib.load(fh))


def save_config(config: Config, path: Path | None = None) -> None:
    path = path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        tomli_w.dump(config.model_dump(), fh)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS — 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/config.py tests/test_config.py
git commit -m "feat: TOML config with defaults"
```

---

## Task 4: Secret storage (fixes bug B3)

**Files:**
- Create: `src/beyondmeetings/secrets.py`
- Test: `tests/test_secrets.py`

Replaces the current `GROQ_API_KEY` shell environment variable.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_secrets.py
import stat

import pytest

from beyondmeetings import secrets as secrets_mod


class FakeKeyring:
    """Stands in for the OS keyring; records calls."""

    def __init__(self, working=True):
        self.working = working
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service, name, value):
        if not self.working:
            raise RuntimeError("no keyring backend")
        self.store[(service, name)] = value

    def get_password(self, service, name):
        if not self.working:
            raise RuntimeError("no keyring backend")
        return self.store.get((service, name))


def test_uses_keyring_when_available(monkeypatch, tmp_path):
    fake = FakeKeyring()
    monkeypatch.setattr(secrets_mod, "keyring", fake)
    secrets_mod.set_secret("groq_api_key", "gsk_live", fallback_dir=tmp_path)
    assert secrets_mod.get_secret("groq_api_key", fallback_dir=tmp_path) == "gsk_live"
    assert not (tmp_path / "secrets.toml").exists()


def test_falls_back_to_file_when_keyring_broken(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring(working=False))
    secrets_mod.set_secret("groq_api_key", "gsk_fallback", fallback_dir=tmp_path)
    assert secrets_mod.get_secret("groq_api_key", fallback_dir=tmp_path) == "gsk_fallback"


def test_fallback_file_is_owner_only(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring(working=False))
    secrets_mod.set_secret("groq_api_key", "gsk_fallback", fallback_dir=tmp_path)
    mode = (tmp_path / "secrets.toml").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_missing_secret_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets_mod, "keyring", FakeKeyring())
    assert secrets_mod.get_secret("absent", fallback_dir=tmp_path) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_secrets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.secrets'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/secrets.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_secrets.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/secrets.py tests/test_secrets.py
git commit -m "feat: keyring-backed secret storage (fixes B3)"
```

---

## Task 5: LLM response parsing

**Files:**
- Create: `src/beyondmeetings/llm/__init__.py`
- Create: `src/beyondmeetings/llm/base.py`
- Test: `tests/test_llm_base.py`

Models return JSON wrapped in prose, fenced in markdown, or with trailing commentary. This is where that gets repaired — every provider adapter routes through it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_base.py
import pytest

from beyondmeetings.llm.base import ResponseParseError, parse_meeting_note

VALID = """
{"title": "Standup", "date": "2026-07-30",
 "executive_summary": "We synced.", "is_informal": false}
"""


def test_parses_bare_json():
    note = parse_meeting_note(VALID)
    assert note.title == "Standup"


def test_parses_json_in_markdown_fence():
    note = parse_meeting_note(f"```json\n{VALID}\n```")
    assert note.title == "Standup"


def test_parses_json_surrounded_by_prose():
    note = parse_meeting_note(f"Here is the note:\n{VALID}\nHope that helps!")
    assert note.title == "Standup"


def test_rejects_follow_up_of_not_in_candidates():
    raw = VALID.replace('"is_informal": false', '"is_informal": false, '
                        '"follow_up_of": "2026-01-01/Invented Meeting"')
    note = parse_meeting_note(raw, valid_candidate_ids=["2026-07-29/Real Meeting"])
    assert note.follow_up_of is None


def test_keeps_follow_up_of_when_in_candidates():
    raw = VALID.replace('"is_informal": false', '"is_informal": false, '
                        '"follow_up_of": "2026-07-29/Real Meeting"')
    note = parse_meeting_note(raw, valid_candidate_ids=["2026-07-29/Real Meeting"])
    assert note.follow_up_of == "2026-07-29/Real Meeting"


def test_raises_when_no_json_present():
    with pytest.raises(ResponseParseError):
        parse_meeting_note("I could not analyse that transcript.")


def test_raises_when_required_field_missing():
    with pytest.raises(ResponseParseError):
        parse_meeting_note('{"title": "No summary or date"}')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.llm'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/llm/__init__.py
```

```python
# src/beyondmeetings/llm/base.py
"""Provider interface and response parsing.

Providers vary in how faithfully they honour "return only JSON". Repair
lives here so every adapter benefits and none reimplements it.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod

from pydantic import ValidationError

from ..models import MeetingNote


class ResponseParseError(RuntimeError):
    """The model's output could not be coerced into a MeetingNote."""


def _extract_json_object(raw: str) -> str:
    text = raw.strip()
    if "```" in text:
        blocks = text.split("```")
        for block in blocks[1::2]:
            candidate = block.split("\n", 1)[-1] if block.startswith("json") else block
            if "{" in candidate:
                text = candidate
                break
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ResponseParseError(f"no JSON object found in model output: {raw[:200]!r}")
    return text[start : end + 1]


def parse_meeting_note(
    raw: str, valid_candidate_ids: list[str] | None = None
) -> MeetingNote:
    """Parse model output into a MeetingNote.

    `follow_up_of` is cleared unless it names one of the candidates that were
    supplied in the prompt — the model cannot invent a link to a note that
    does not exist.
    """
    payload = _extract_json_object(raw)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ResponseParseError(f"invalid JSON from model: {exc}") from exc

    try:
        note = MeetingNote(**data)
    except ValidationError as exc:
        raise ResponseParseError(f"model output failed validation: {exc}") from exc

    if note.follow_up_of and valid_candidate_ids is not None:
        if note.follow_up_of not in valid_candidate_ids:
            note.follow_up_of = None
    return note


class LLMProvider(ABC):
    """One call in, one MeetingNote out."""

    @abstractmethod
    def analyse(
        self, prompt: str, valid_candidate_ids: list[str] | None = None
    ) -> MeetingNote:
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_llm_base.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/llm tests/test_llm_base.py
git commit -m "feat: LLM response parsing with JSON repair"
```

---

## Task 6: Vault paths and links

**Files:**
- Create: `src/beyondmeetings/vault/__init__.py`
- Create: `src/beyondmeetings/vault/paths.py`
- Test: `tests/test_vault_paths.py`

The live vault shows titles containing `—` and `&` rendered as `-` and `&` in filenames. This module owns that translation so every writer agrees.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_paths.py
from pathlib import Path

from beyondmeetings.models import MeetingRef
from beyondmeetings.vault.paths import (
    meeting_wikilink,
    note_path,
    safe_filename,
)


def test_safe_filename_replaces_em_dash_with_hyphen():
    assert safe_filename("Phase 4 — Resourcing Plan") == "Phase 4 - Resourcing Plan"


def test_safe_filename_strips_path_separators():
    assert safe_filename("Q3/Q4 Planning") == "Q3-Q4 Planning"


def test_safe_filename_strips_illegal_characters():
    assert safe_filename('Review: "scope" <draft>?') == "Review - scope draft"


def test_safe_filename_collapses_whitespace():
    assert safe_filename("Too    many   spaces") == "Too many spaces"


def test_safe_filename_never_returns_empty():
    assert safe_filename("///") == "Untitled Meeting"


def test_note_path_uses_date_folder_and_bare_filename():
    path = note_path(Path("/vault"), MeetingRef(date="2026-07-30", title="Standup"))
    assert path == Path("/vault/Meetings/2026-07-30/Standup.md")


def test_meeting_wikilink_is_full_path_without_extension():
    ref = MeetingRef(date="2026-07-30", title="Standup")
    assert meeting_wikilink(ref) == "[[Meetings/2026-07-30/Standup]]"


def test_meeting_wikilink_with_display_title_uses_pipe():
    ref = MeetingRef(date="2026-07-30", title="Phase 4 - Plan")
    link = meeting_wikilink(ref, display="Phase 4 — Plan")
    assert link == "[[Meetings/2026-07-30/Phase 4 - Plan|Phase 4 — Plan]]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vault_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.vault'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/vault/__init__.py
```

```python
# src/beyondmeetings/vault/paths.py
"""Filename sanitising and wikilink construction.

Obsidian note filenames drop the date prefix — the date is the folder — and
links are always full-path: [[Meetings/YYYY-MM-DD/Title]].
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import MeetingRef

_ILLEGAL = r'[:"<>?*|\\]'
_FALLBACK = "Untitled Meeting"


def safe_filename(title: str) -> str:
    name = title.replace("—", "-").replace("–", "-")
    name = name.replace("/", "-")
    name = re.sub(_ILLEGAL, "", name)
    name = re.sub(r"\s+", " ", name).strip(" .-")
    return name or _FALLBACK


def meetings_dir(vault: Path) -> Path:
    return vault / "Meetings"


def note_path(vault: Path, ref: MeetingRef) -> Path:
    return meetings_dir(vault) / ref.date / f"{safe_filename(ref.title)}.md"


def meeting_wikilink(ref: MeetingRef, display: str | None = None) -> str:
    target = f"Meetings/{ref.date}/{safe_filename(ref.title)}"
    if display and display != safe_filename(ref.title):
        return f"[[{target}|{display}]]"
    return f"[[{target}]]"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_vault_paths.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/vault tests/test_vault_paths.py
git commit -m "feat: vault path and wikilink helpers"
```

---

## Task 7: Note rendering

**Files:**
- Create: `src/beyondmeetings/vault/note.py`
- Test: `tests/test_vault_note.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_note.py
from beyondmeetings.models import ActionItem, MeetingNote, Section
from beyondmeetings.vault.note import render_note


def _note(**overrides):
    base = dict(
        title="Phase 4 — Plan",
        date="2026-07-30",
        tags=["meeting", "Acme"],
        attendees=["Jordan", "Sam"],
        executive_summary="We planned phase 4.",
        decisions=["Buy two licences."],
        action_items=[ActionItem(task="Procure licences", owner="Sam",
                                 due="2026-08-01", priority="HIGH")],
    )
    base.update(overrides)
    return MeetingNote(**base)


def test_frontmatter_lists_tags_and_attendees_as_yaml_blocks():
    out = render_note(_note())
    assert out.startswith("---\n")
    assert "tags:\n  - meeting\n  - Acme\n" in out
    assert "attendees:\n  - Jordan\n  - Sam\n" in out
    assert "date: 2026-07-30\n" in out


def test_h1_uses_the_display_title_with_em_dash():
    assert "\n# Phase 4 — Plan\n" in render_note(_note())


def test_follow_up_frontmatter_and_callout_present_when_linked():
    out = render_note(_note(follow_up_of="2026-07-29/Design QA Review"))
    assert 'follow_up_of: "[[Meetings/2026-07-29/Design QA Review]]"' in out
    assert "> [!note]- Follow-up to\n> [[Meetings/2026-07-29/Design QA Review]]" in out


def test_no_follow_up_key_when_standalone():
    out = render_note(_note())
    assert "follow_up_of" not in out
    assert "Follow-up to" not in out


def test_action_items_render_as_checkboxes_with_owner_and_due():
    out = render_note(_note())
    assert ("- [ ] **Procure licences** — **Sam** · Due: 2026-08-01" in out)


def test_decisions_render_under_their_heading():
    out = render_note(_note())
    assert "## Decisions Made\n- Buy two licences." in out


def test_empty_decisions_says_none_recorded():
    out = render_note(_note(decisions=[]))
    assert "## Decisions Made\nNone recorded." in out


def test_transcription_note_renders_as_warning_callout():
    out = render_note(_note(transcription_note="Heavy garbling around numbers."))
    assert "> [!warning]\n> **Transcription quality:** Heavy garbling" in out


def test_free_form_sections_render_after_typed_ones():
    out = render_note(_note(sections=[Section(heading="Key Discussion Points",
                                              bullets=["Costing gap."])]))
    assert "## Key Discussion Points\n- Costing gap." in out


def test_footer_credits_configured_tools():
    out = render_note(_note(), transcriber="Groq Whisper", provider="Claude")
    assert out.rstrip().endswith(
        "*Transcribed with Groq Whisper · Generated by beyondMeetings (Claude)*"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vault_note.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.vault.note'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/vault/note.py
"""Render a MeetingNote to Obsidian markdown.

Format mirrors the notes already in the live vault: YAML block sequences in
frontmatter, an em-dash display title in the H1, typed sections under fixed
headings, then free-form sections.
"""
from __future__ import annotations

from ..models import MeetingNote, MeetingRef
from .paths import meeting_wikilink


def _yaml_list(key: str, values: list[str]) -> str:
    if not values:
        return ""
    lines = "\n".join(f"  - {v}" for v in values)
    return f"{key}:\n{lines}\n"


def _bullets(items: list[str], empty: str | None = None) -> str:
    if not items:
        return f"{empty}\n" if empty else ""
    return "\n".join(f"- {i}" for i in items) + "\n"


def render_note(
    note: MeetingNote,
    transcriber: str = "Groq Whisper",
    provider: str = "Claude",
) -> str:
    parts: list[str] = ["---\n"]
    parts.append(_yaml_list("tags", note.tags))
    parts.append(f"date: {note.date}\n")
    parts.append(_yaml_list("attendees", note.attendees))

    prev_link = None
    if note.follow_up_of:
        prev_link = meeting_wikilink(MeetingRef.from_id(note.follow_up_of))
        parts.append(f'follow_up_of: "{prev_link}"\n')
    parts.append("---\n\n")

    parts.append(f"# {note.title}\n\n")
    if prev_link:
        parts.append(f"> [!note]- Follow-up to\n> {prev_link}\n\n")
    if note.transcription_note:
        parts.append(
            f"> [!warning]\n> **Transcription quality:** {note.transcription_note}\n\n"
        )

    parts.append(f"## Executive Summary\n{note.executive_summary}\n\n")
    parts.append("## Decisions Made\n" + _bullets(note.decisions, "None recorded."))
    parts.append("\n## Action Items\n")
    if note.action_items:
        for item in note.action_items:
            line = f"- [ ] **{item.task}**"
            if item.owner:
                line += f" — **{item.owner}**"
            if item.due:
                line += f" · Due: {item.due}"
            parts.append(line + "\n")
    else:
        parts.append("None recorded.\n")

    for heading, values in (
        ("Open Questions", note.open_questions),
        ("Key Discussion Points", None),
        ("Risks / Concerns", note.risks),
        ("Follow-ups", note.follow_ups),
    ):
        if values is None:
            continue
        if values:
            parts.append(f"\n## {heading}\n" + _bullets(values))

    for section in note.sections:
        parts.append(f"\n## {section.heading}\n" + _bullets(section.bullets))

    parts.append(
        f"\n---\n*Transcribed with {transcriber} · "
        f"Generated by beyondMeetings ({provider})*\n"
    )
    return "".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_vault_note.py -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/vault/note.py tests/test_vault_note.py
git commit -m "feat: render meeting notes to Obsidian markdown"
```

---

## Task 8: Vault scaffold

**Files:**
- Create: `src/beyondmeetings/vault/scaffold.py`
- Test: `tests/test_vault_scaffold.py`

Idempotency matters — the wizard runs this against vaults that already contain 205 tasks.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_scaffold.py
from beyondmeetings.vault.scaffold import scaffold_vault


def test_creates_expected_structure(tmp_path):
    scaffold_vault(tmp_path)
    assert (tmp_path / "Meetings").is_dir()
    assert (tmp_path / "Tasks" / "Task Board.md").is_file()
    assert (tmp_path / "Home.md").is_file()


def test_new_task_board_has_zeroed_counters(tmp_path):
    scaffold_vault(tmp_path)
    text = (tmp_path / "Tasks" / "Task Board.md").read_text()
    assert "> [!todo]+ Pending — 0" in text
    assert "`0 pending`" in text


def test_new_home_has_recent_callout(tmp_path):
    scaffold_vault(tmp_path)
    assert "> [!example]+ Recent" in (tmp_path / "Home.md").read_text()


def test_never_overwrites_existing_files(tmp_path):
    (tmp_path / "Tasks").mkdir()
    (tmp_path / "Tasks" / "Task Board.md").write_text("MY 205 REAL TASKS")
    (tmp_path / "Home.md").write_text("MY REAL HOME")
    scaffold_vault(tmp_path)
    assert (tmp_path / "Tasks" / "Task Board.md").read_text() == "MY 205 REAL TASKS"
    assert (tmp_path / "Home.md").read_text() == "MY REAL HOME"


def test_is_safely_repeatable(tmp_path):
    scaffold_vault(tmp_path)
    first = (tmp_path / "Home.md").read_text()
    scaffold_vault(tmp_path)
    assert (tmp_path / "Home.md").read_text() == first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vault_scaffold.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.vault.scaffold'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/vault/scaffold.py
"""Create the vault structure. Never overwrites existing content."""
from __future__ import annotations

from datetime import date
from pathlib import Path

TASK_BOARD_TEMPLATE = """---
tags: [tasks]
updated: {today}
---

# Task Board

← [[Home]]

---

> [!abstract] Board at a Glance
> `0 pending` · `0 in discussion` · `0 blocked` · `0 done`

---

> [!danger]+ Blocked — 0
> No blocked tasks right now.

> [!todo]+ Pending — 0

> [!success]- Done — 0
"""

HOME_TEMPLATE = """---
tags: [home, dashboard]
updated: {today}
---

# Workspace

---

## Tasks

> [!abstract] Board at a Glance
> `0 pending` · `0 in discussion` · `0 blocked` · `0 done`

> [!danger]+ Blocked — 0
> No blocked tasks right now.

> [!todo]+ Pending — 0
>
> → [[Tasks/Task Board|See all tasks]]

→ [[Tasks/Task Board|Full task board]]

---

## Meetings

> [!example]+ Recent
"""


def scaffold_vault(vault: Path) -> None:
    today = date.today().isoformat()
    (vault / "Meetings").mkdir(parents=True, exist_ok=True)
    (vault / "Tasks").mkdir(parents=True, exist_ok=True)

    board = vault / "Tasks" / "Task Board.md"
    if not board.exists():
        board.write_text(TASK_BOARD_TEMPLATE.format(today=today))

    home = vault / "Home.md"
    if not home.exists():
        home.write_text(HOME_TEMPLATE.format(today=today))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_vault_scaffold.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/vault/scaffold.py tests/test_vault_scaffold.py
git commit -m "feat: idempotent vault scaffold"
```

---

## Task 9: Task Board writer

**Files:**
- Create: `src/beyondmeetings/vault/taskboard.py`
- Test: `tests/test_vault_taskboard.py`

**Format note:** entries in the live board are **nested** blockquotes (`> >`) inside the `> [!todo]+ Pending — N` callout, separated by a `> >` spacer line. New tasks are prepended immediately after the header.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_taskboard.py
import pytest

from beyondmeetings.models import ActionItem, MeetingRef
from beyondmeetings.vault.taskboard import add_tasks, count_pending, update_counters

BOARD = """---
tags: [tasks]
updated: 2026-07-01
---

# Task Board

> [!abstract] Board at a Glance
> `2 pending` · `0 in discussion` · `0 blocked` · `1 done`

> [!todo]+ Pending — 2
> > **==Existing One==** · `Zenith` · `LOW`
> > Already here. — **Sam** · [[Meetings/2026-07-01/Old]]
> >
> > **==Existing Two==** · `LOW`
> > Also here. · [[Meetings/2026-07-01/Old]]
> >

> [!success]- Done — 1
"""

REF = MeetingRef(date="2026-07-30", title="Phase 4 - Plan")


def test_count_pending_reads_the_header():
    assert count_pending(BOARD) == 2


def test_add_tasks_prepends_new_entries_after_header():
    out = add_tasks(BOARD, [ActionItem(task="Procure licences", owner="Sam",
                                       project="Acme", priority="HIGH",
                                       due="2026-08-01")], REF, "Buy two licences.")
    body = out.split("> [!todo]+ Pending — 3\n", 1)[1]
    assert body.startswith("> > **==Procure licences==** · `Acme` · `HIGH`\n")


def test_added_task_line_has_owner_due_and_meeting_link():
    out = add_tasks(BOARD, [ActionItem(task="Procure licences", owner="Sam",
                                       project="Acme", priority="HIGH",
                                       due="2026-08-01")], REF, "Buy two licences.")
    assert ("> > Buy two licences. — **Sam** · Due: 2026-08-01 · "
            "[[Meetings/2026-07-30/Phase 4 - Plan]]\n") in out


def test_project_omitted_when_absent():
    out = add_tasks(BOARD, [ActionItem(task="No project", priority="LOW")],
                    REF, "Do it.")
    assert "> > **==No project==** · `LOW`\n" in out


def test_counters_increase_by_number_of_tasks():
    out = add_tasks(BOARD, [ActionItem(task="A"), ActionItem(task="B")], REF, "d")
    assert "> [!todo]+ Pending — 4" in out
    assert "`4 pending`" in out


def test_existing_tasks_are_preserved():
    out = add_tasks(BOARD, [ActionItem(task="A")], REF, "d")
    assert "**==Existing One==**" in out
    assert "**==Existing Two==**" in out


def test_adding_empty_list_is_a_no_op():
    assert add_tasks(BOARD, [], REF, "d") == BOARD


def test_update_counters_rewrites_both_places():
    out = update_counters(BOARD, pending=99)
    assert "`99 pending`" in out
    assert "> [!todo]+ Pending — 99" in out
    assert "`1 done`" in out


def test_add_tasks_raises_when_pending_callout_missing():
    with pytest.raises(ValueError):
        add_tasks("# Empty board\n", [ActionItem(task="A")], REF, "d")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vault_taskboard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.vault.taskboard'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/vault/taskboard.py
"""Insert tasks into the Task Board and keep its counters correct.

Counter arithmetic is code, not a model's job — this is the single largest
source of drift in the prose-driven pipeline this replaces.
"""
from __future__ import annotations

import re

from ..models import ActionItem, MeetingRef
from .paths import meeting_wikilink

PENDING_HEADER = re.compile(r"^> \[!todo\]\+ Pending — (\d+)\s*$", re.MULTILINE)
GLANCE_PENDING = re.compile(r"`(\d+) pending`")


def count_pending(text: str) -> int:
    match = PENDING_HEADER.search(text)
    if not match:
        raise ValueError("Task Board has no '> [!todo]+ Pending — N' callout")
    return int(match.group(1))


def update_counters(text: str, pending: int) -> str:
    text = PENDING_HEADER.sub(f"> [!todo]+ Pending — {pending}", text, count=1)
    return GLANCE_PENDING.sub(f"`{pending} pending`", text, count=1)


def _render_entry(item: ActionItem, ref: MeetingRef, description: str) -> str:
    tags = f"`{item.project}` · " if item.project else ""
    head = f"> > **=={item.task}==** · {tags}`{item.priority}`"

    detail = f"> > {description}"
    if item.owner:
        detail += f" — **{item.owner}**"
    if item.due:
        detail += f" · Due: {item.due}"
    detail += f" · {meeting_wikilink(ref)}"

    return f"{head}\n{detail}\n> >\n"


def add_tasks(
    text: str,
    items: list[ActionItem],
    ref: MeetingRef,
    description: str,
) -> str:
    if not items:
        return text

    current = count_pending(text)
    match = PENDING_HEADER.search(text)
    insert_at = match.end() + 1

    block = "".join(_render_entry(i, ref, description) for i in items)
    text = text[:insert_at] + block + text[insert_at:]
    return update_counters(text, current + len(items))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_vault_taskboard.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/vault/taskboard.py tests/test_vault_taskboard.py
git commit -m "feat: Task Board writer with deterministic counters"
```

---

## Task 10: Home.md writer

**Files:**
- Create: `src/beyondmeetings/vault/home.py`
- Test: `tests/test_vault_home.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_home.py
from beyondmeetings.models import MeetingRef
from beyondmeetings.vault.home import add_recent_meeting, sync_counters, touch_updated

HOME = """---
tags: [home, dashboard]
updated: 2026-07-01
---

# Workspace

## Tasks

> [!abstract] Board at a Glance
> `2 pending` · `0 in discussion` · `0 blocked` · `1 done`

> [!todo]+ Pending — 2
>
> → [[Tasks/Task Board|See all tasks]]

## Meetings

> [!example]+ Recent
> **[[Meetings/2026-07-01/Old|Old Meeting]]** · Zenith · Something older
"""

REF = MeetingRef(date="2026-07-30", title="Phase 4 - Plan")


def test_new_meeting_is_prepended_above_older_ones():
    out = add_recent_meeting(HOME, REF, "Phase 4 — Plan", "Acme",
                             "Licences approved")
    body = out.split("> [!example]+ Recent\n", 1)[1]
    assert body.splitlines()[0].startswith(
        "> **[[Meetings/2026-07-30/Phase 4 - Plan|Phase 4 — Plan]]**"
    )
    assert "Old Meeting" in out


def test_entry_contains_project_and_description():
    out = add_recent_meeting(HOME, REF, "Phase 4 — Plan", "Acme",
                             "Licences approved")
    assert "· Acme · Licences approved" in out


def test_follow_up_marker_is_appended_when_linked():
    prev = MeetingRef(date="2026-07-29", title="Design QA Review")
    out = add_recent_meeting(HOME, REF, "Phase 4 — Plan", "Acme",
                             "Licences approved", previous=prev,
                             previous_display="Design QA Review")
    assert ("· ↳ follow-up to [[Meetings/2026-07-29/Design QA Review]]"
            in out)


def test_no_follow_up_marker_when_standalone():
    out = add_recent_meeting(HOME, REF, "Phase 4 — Plan", "Acme", "x")
    assert "follow-up to" not in out


def test_project_omitted_cleanly_when_unknown():
    out = add_recent_meeting(HOME, REF, "Phase 4 — Plan", None, "Licences approved")
    assert "**[[Meetings/2026-07-30/Phase 4 - Plan|Phase 4 — Plan]]** · Licences" in out


def test_sync_counters_matches_task_board():
    out = sync_counters(HOME, pending=7)
    assert "`7 pending`" in out
    assert "> [!todo]+ Pending — 7" in out


def test_touch_updated_rewrites_frontmatter_date():
    out = touch_updated(HOME, "2026-07-30")
    assert "updated: 2026-07-30" in out
    assert "updated: 2026-07-01" not in out


def test_missing_recent_callout_raises():
    import pytest
    with pytest.raises(ValueError):
        add_recent_meeting("# Home\n", REF, "T", "P", "d")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vault_home.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.vault.home'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/vault/home.py
"""Home.md is the dashboard linking both meetings and tasks.

It must never drift from Task Board.md — sync_counters() is called in the
same pass as every task insert.
"""
from __future__ import annotations

import re

from ..models import MeetingRef
from .paths import meeting_wikilink

RECENT_HEADER = re.compile(r"^> \[!example\]\+ Recent\s*$", re.MULTILINE)
PENDING_HEADER = re.compile(r"^> \[!todo\]\+ Pending — (\d+)\s*$", re.MULTILINE)
GLANCE_PENDING = re.compile(r"`(\d+) pending`")
UPDATED = re.compile(r"^updated: .*$", re.MULTILINE)


def sync_counters(text: str, pending: int) -> str:
    text = PENDING_HEADER.sub(f"> [!todo]+ Pending — {pending}", text, count=1)
    return GLANCE_PENDING.sub(f"`{pending} pending`", text, count=1)


def touch_updated(text: str, today: str) -> str:
    return UPDATED.sub(f"updated: {today}", text, count=1)


def add_recent_meeting(
    text: str,
    ref: MeetingRef,
    display: str,
    project: str | None,
    description: str,
    previous: MeetingRef | None = None,
    previous_display: str | None = None,
) -> str:
    match = RECENT_HEADER.search(text)
    if not match:
        raise ValueError("Home.md has no '> [!example]+ Recent' callout")

    line = f"> **{meeting_wikilink(ref, display)}**"
    if project:
        line += f" · {project}"
    line += f" · {description}"
    if previous:
        line += f" · ↳ follow-up to {meeting_wikilink(previous, previous_display)}"
    line += "\n"

    insert_at = match.end() + 1
    return text[:insert_at] + line + text[insert_at:]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_vault_home.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/vault/home.py tests/test_vault_home.py
git commit -m "feat: Home.md dashboard writer"
```

---

## Task 11: Follow-up candidates and back-linking

**Files:**
- Create: `src/beyondmeetings/vault/followup.py`
- Test: `tests/test_vault_followup.py`

Python guarantees the candidate set; the model only picks from it. This is what makes follow-up detection reliable across providers.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_followup.py
from datetime import date, timedelta

from beyondmeetings.models import MeetingRef
from beyondmeetings.vault.followup import (
    append_followup_backlink,
    gather_candidates,
)


def _write(vault, day, title, summary="A summary.", tags="  - Acme"):
    folder = vault / "Meetings" / day
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{title}.md").write_text(
        f"---\ntags:\n  - meeting\n{tags}\ndate: {day}\n---\n\n"
        f"# {title}\n\n## Executive Summary\n{summary}\n\n## Decisions Made\n- x\n"
    )


def test_gathers_notes_within_the_window(tmp_path):
    recent = (date.today() - timedelta(days=3)).isoformat()
    _write(tmp_path, recent, "Recent Meeting")
    found = gather_candidates(tmp_path, days=30)
    assert [c.ref.id for c in found] == [f"{recent}/Recent Meeting"]


def test_ignores_notes_outside_the_window(tmp_path):
    old = (date.today() - timedelta(days=90)).isoformat()
    _write(tmp_path, old, "Ancient Meeting")
    assert gather_candidates(tmp_path, days=30) == []


def test_extracts_executive_summary_and_tags(tmp_path):
    day = (date.today() - timedelta(days=1)).isoformat()
    _write(tmp_path, day, "Yesterday", summary="We agreed the plan.")
    candidate = gather_candidates(tmp_path, days=30)[0]
    assert candidate.executive_summary == "We agreed the plan."
    assert "Acme" in candidate.tags


def test_results_are_newest_first(tmp_path):
    for offset in (1, 5, 3):
        day = (date.today() - timedelta(days=offset)).isoformat()
        _write(tmp_path, day, f"Meeting {offset}")
    dates = [c.ref.date for c in gather_candidates(tmp_path, days=30)]
    assert dates == sorted(dates, reverse=True)


def test_respects_the_limit(tmp_path):
    for offset in range(1, 12):
        day = (date.today() - timedelta(days=offset)).isoformat()
        _write(tmp_path, day, f"Meeting {offset}")
    assert len(gather_candidates(tmp_path, days=30, limit=5)) == 5


def test_missing_meetings_dir_returns_empty(tmp_path):
    assert gather_candidates(tmp_path, days=30) == []


def test_backlink_appends_to_existing_followups_section(tmp_path):
    _write(tmp_path, "2026-07-29", "Prev")
    path = tmp_path / "Meetings" / "2026-07-29" / "Prev.md"
    path.write_text(path.read_text() + "\n## Follow-ups\n- Something earlier.\n\n---\n")
    append_followup_backlink(
        path, MeetingRef(date="2026-07-30", title="Next Meeting")
    )
    text = path.read_text()
    assert "- Something earlier." in text
    assert "- Followed up in: [[Meetings/2026-07-30/Next Meeting]]" in text


def test_backlink_creates_followups_section_when_absent(tmp_path):
    _write(tmp_path, "2026-07-29", "Prev")
    path = tmp_path / "Meetings" / "2026-07-29" / "Prev.md"
    append_followup_backlink(
        path, MeetingRef(date="2026-07-30", title="Next Meeting")
    )
    text = path.read_text()
    assert "## Follow-ups" in text
    assert "- Followed up in: [[Meetings/2026-07-30/Next Meeting]]" in text


def test_backlink_is_not_duplicated_on_repeat(tmp_path):
    _write(tmp_path, "2026-07-29", "Prev")
    path = tmp_path / "Meetings" / "2026-07-29" / "Prev.md"
    ref = MeetingRef(date="2026-07-30", title="Next Meeting")
    append_followup_backlink(path, ref)
    append_followup_backlink(path, ref)
    assert path.read_text().count("Followed up in:") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vault_followup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.vault.followup'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/vault/followup.py
"""Follow-up candidate gathering and reciprocal linking.

The LLM never browses the vault. Python collects candidates from the last N
days and passes them in the prompt; the model returns one id or null.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel

from ..models import MeetingRef
from .paths import meeting_wikilink, meetings_dir

DATE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SUMMARY = re.compile(r"^## Executive Summary\s*\n(.+?)(?=\n##|\n---|\Z)", re.DOTALL | re.MULTILINE)
TAG_LINE = re.compile(r"^\s+- (.+)$", re.MULTILINE)


class Candidate(BaseModel):
    ref: MeetingRef
    tags: list[str] = []
    executive_summary: str = ""


def _parse(path: Path, folder: str) -> Candidate:
    text = path.read_text(encoding="utf-8", errors="replace")
    front = text.split("---", 2)[1] if text.startswith("---") else ""
    tags = [t.strip() for t in TAG_LINE.findall(front) if t.strip() != "meeting"]
    match = SUMMARY.search(text)
    summary = match.group(1).strip() if match else ""
    return Candidate(
        ref=MeetingRef(date=folder, title=path.stem),
        tags=tags,
        executive_summary=summary,
    )


def gather_candidates(vault: Path, days: int = 30, limit: int = 12) -> list[Candidate]:
    root = meetings_dir(vault)
    if not root.is_dir():
        return []

    cutoff = date.today() - timedelta(days=days)
    found: list[Candidate] = []
    for folder in sorted(root.iterdir(), reverse=True):
        if not folder.is_dir() or not DATE_FOLDER.match(folder.name):
            continue
        try:
            if date.fromisoformat(folder.name) < cutoff:
                continue
        except ValueError:
            continue
        for note in sorted(folder.glob("*.md")):
            found.append(_parse(note, folder.name))
            if len(found) >= limit:
                return found
    return found


def append_followup_backlink(previous_note: Path, new: MeetingRef) -> None:
    """Record the forward link in the previous meeting's note."""
    text = previous_note.read_text(encoding="utf-8")
    line = f"- Followed up in: {meeting_wikilink(new)}"
    if line in text:
        return

    if "## Follow-ups" in text:
        head, _, tail = text.partition("## Follow-ups\n")
        body, sep, rest = tail.partition("\n---")
        text = head + "## Follow-ups\n" + body.rstrip("\n") + "\n" + line + "\n" + sep + rest
    else:
        body, sep, rest = text.rpartition("\n---")
        if sep:
            text = body.rstrip("\n") + f"\n\n## Follow-ups\n{line}\n" + sep + rest
        else:
            text = text.rstrip("\n") + f"\n\n## Follow-ups\n{line}\n"

    previous_note.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_vault_followup.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/vault/followup.py tests/test_vault_followup.py
git commit -m "feat: follow-up candidates and reciprocal linking"
```

---

## Task 12: Analysis prompt

**Files:**
- Create: `src/beyondmeetings/prompts.py`
- Test: `tests/test_prompts.py`

This is where every rule from the current `CLAUDE.md` lands. Spec §5 is the checklist.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompts.py
from beyondmeetings.models import MeetingRef
from beyondmeetings.prompts import build_analysis_prompt
from beyondmeetings.vault.followup import Candidate

CANDIDATES = [
    Candidate(ref=MeetingRef(date="2026-07-29", title="Design QA Review"),
              tags=["Acme"], executive_summary="We reviewed the designs.")
]


def test_transcript_is_included():
    prompt = build_analysis_prompt("We discussed the roadmap.", "2026-07-30", [], [])
    assert "We discussed the roadmap." in prompt


def test_candidate_ids_are_listed_verbatim():
    prompt = build_analysis_prompt("t", "2026-07-30", CANDIDATES, [])
    assert "2026-07-29/Design QA Review" in prompt
    assert "We reviewed the designs." in prompt


def test_states_the_strong_evidence_bar_for_follow_ups():
    prompt = build_analysis_prompt("t", "2026-07-30", CANDIDATES, [])
    assert "same specific work-thread" in prompt
    assert "most recent" in prompt


def test_instructs_standalone_when_unsure():
    prompt = build_analysis_prompt("t", "2026-07-30", CANDIDATES, [])
    assert "null" in prompt


def test_no_candidates_states_it_must_be_standalone():
    prompt = build_analysis_prompt("t", "2026-07-30", [], [])
    assert "no candidate meetings" in prompt.lower()


def test_informal_rule_is_present():
    prompt = build_analysis_prompt("t", "2026-07-30", [], [])
    assert "is_informal" in prompt
    assert "show-and-tell" in prompt


def test_implied_work_rule_is_present():
    prompt = build_analysis_prompt("t", "2026-07-30", [], [])
    assert "not just explicitly stated action items" in prompt


def test_configured_projects_are_offered_as_tags():
    prompt = build_analysis_prompt("t", "2026-07-30", [], ["Acme", "Zenith"])
    assert "Acme" in prompt and "Zenith" in prompt


def test_notes_language_is_honoured():
    prompt = build_analysis_prompt("t", "2026-07-30", [], [], notes_language="English")
    assert "in English" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.prompts'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/prompts.py
"""Analysis prompt assembly.

Every behavioural rule from the original CLAUDE.md pipeline lives here, so
it runs on every provider rather than depending on an agent reading a file.
"""
from __future__ import annotations

from .vault.followup import Candidate

SCHEMA = """{
  "title": string,
  "date": "YYYY-MM-DD",
  "tags": [string],
  "attendees": [string],
  "executive_summary": string,
  "one_line_summary": string,
  "sections": [{"heading": string, "bullets": [string]}],
  "decisions": [string],
  "open_questions": [string],
  "risks": [string],
  "follow_ups": [string],
  "action_items": [{"task": string, "owner": string|null, "due": string|null,
                    "project": string|null, "priority": "HIGH"|"MEDIUM"|"LOW"}],
  "transcription_note": string|null,
  "is_informal": boolean,
  "follow_up_of": string|null
}"""

RULES = """
Rules:

1. TASKS — Extract every task, not just explicitly stated action items. Anything
   discussed that implies work counts: decisions requiring follow-up, things
   flagged for review, confirmations needed, work assigned to anyone. If it was
   discussed as a next step, it is a task. Infer `priority` from the urgency in
   the discussion.

2. INFORMAL CALLS — Set `is_informal` to true when this is a peer show-and-tell
   or demo, a casual catch-up or social chat, or a conversation dominated by
   personal projects, tooling, hobbies or home setup rather than client/project
   work with assigned deliverables. Signals: no clear ownership or deadlines,
   content is mostly demonstrating already-built things, or it is a 1:1 catch-up
   with no project agenda. When genuinely ambiguous, prefer true. When
   `is_informal` is true, still fill in `action_items` if any were stated — the
   caller decides what to do with them.

3. TITLE — Derive a specific, descriptive title from the content. Never use a
   placeholder such as "recording-14-30".

4. TRANSCRIPTION_NOTE — If the transcript is visibly garbled, machine-translated
   or has systematically mangled names or numbers, describe the problem and list
   the substitutions you inferred. Otherwise null.

5. SECTIONS — `sections` is for free-form narrative only. Never duplicate
   decisions, open questions, risks, follow-ups or action items there.

6. ONE_LINE_SUMMARY — One sentence, no trailing full stop, for the dashboard.
"""


def _followup_rules(candidates: list[Candidate]) -> str:
    if not candidates:
        return (
            "\n7. FOLLOW-UP — There are no candidate meetings. "
            "Set `follow_up_of` to null.\n"
        )

    listing = "\n".join(
        f'  - id: "{c.ref.id}"\n'
        f"    tags: {', '.join(c.tags) or 'none'}\n"
        f"    summary: {c.executive_summary}"
        for c in candidates
    )
    return f"""
7. FOLLOW-UP — Decide whether this meeting continues one of the meetings below.
   Judge from the transcript content only, never from the meeting's name.

   Declare a follow-up only on strong evidence. BOTH must hold:
     (a) the same project AND the same specific work-thread — not merely the
         same project or the same client; and
     (b) at least one strong continuity signal: an explicit back-reference in
         the transcript ("yesterday", "last time", "continue", "as we
         discussed"), the same screens / tickets / documents / artifacts named
         again, OR the same people actively working the very task the prior
         meeting was about.

   If several qualify, pick the most recent, so a chain links to its latest
   link rather than the original. If nothing clears the bar, or you are
   genuinely unsure, set `follow_up_of` to null.

   Set `follow_up_of` to exactly one of these ids, or null:
{listing}
"""


def build_analysis_prompt(
    transcript: str,
    meeting_date: str,
    candidates: list[Candidate],
    projects: list[str],
    notes_language: str = "English",
) -> str:
    project_rule = (
        f"\n8. PROJECT TAGS — Use one of these when it clearly applies, else omit: "
        f"{', '.join(projects)}.\n"
        if projects
        else "\n8. PROJECT TAGS — No configured projects; omit `project`.\n"
    )

    return f"""You are analysing a meeting transcript recorded on {meeting_date}.

Return ONLY a single JSON object matching this schema. No prose, no markdown
fence, no commentary before or after.

{SCHEMA}

Write all output in {notes_language}, regardless of the language spoken in the
transcript.
{RULES}{_followup_rules(candidates)}{project_rule}
--- TRANSCRIPT ---
{transcript}
--- END TRANSCRIPT ---
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_prompts.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/prompts.py tests/test_prompts.py
git commit -m "feat: analysis prompt carrying all pipeline rules"
```

---

## Task 13: Anthropic provider

**Files:**
- Create: `src/beyondmeetings/llm/anthropic.py`
- Test: `tests/test_llm_anthropic.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_anthropic.py
import httpx
import pytest

from beyondmeetings.llm.anthropic import AnthropicProvider
from beyondmeetings.llm.base import ResponseParseError

BODY = {"content": [{"type": "text", "text":
        '{"title": "Standup", "date": "2026-07-30", '
        '"executive_summary": "We synced."}'}]}


def test_returns_parsed_note(httpx_mock):
    httpx_mock.add_response(json=BODY)
    note = AnthropicProvider(api_key="sk-test").analyse("prompt")
    assert note.title == "Standup"


def test_sends_api_key_and_version_headers(httpx_mock):
    httpx_mock.add_response(json=BODY)
    AnthropicProvider(api_key="sk-test").analyse("prompt")
    request = httpx_mock.get_requests()[0]
    assert request.headers["x-api-key"] == "sk-test"
    assert request.headers["anthropic-version"] == "2023-06-01"


def test_sends_prompt_as_user_message(httpx_mock):
    httpx_mock.add_response(json=BODY)
    AnthropicProvider(api_key="sk-test").analyse("analyse this")
    import json
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["messages"][0]["content"] == "analyse this"
    assert payload["model"]


def test_http_error_raises_runtime_error(httpx_mock):
    httpx_mock.add_response(status_code=401, json={"error": {"message": "bad key"}})
    with pytest.raises(RuntimeError, match="bad key"):
        AnthropicProvider(api_key="sk-bad").analyse("prompt")


def test_unparseable_content_raises_parse_error(httpx_mock):
    httpx_mock.add_response(json={"content": [{"type": "text", "text": "sorry"}]})
    with pytest.raises(ResponseParseError):
        AnthropicProvider(api_key="sk-test").analyse("prompt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_anthropic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.llm.anthropic'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/llm/anthropic.py
"""Claude adapter."""
from __future__ import annotations

import httpx

from ..models import MeetingNote
from .base import LLMProvider, parse_meeting_note

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-opus-5"
TIMEOUT = 300.0


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "", max_tokens: int = 8000):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.max_tokens = max_tokens

    def analyse(
        self, prompt: str, valid_candidate_ids: list[str] | None = None
    ) -> MeetingNote:
        response = httpx.post(
            API_URL,
            timeout=TIMEOUT,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        if response.status_code != 200:
            detail = response.json().get("error", {}).get("message", response.text)
            raise RuntimeError(f"Anthropic API error {response.status_code}: {detail}")

        blocks = response.json().get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return parse_meeting_note(text, valid_candidate_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_llm_anthropic.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/llm/anthropic.py tests/test_llm_anthropic.py
git commit -m "feat: Anthropic provider adapter"
```

---

## Task 14: Groq transcription (fixes bugs B1 and B5)

**Files:**
- Create: `src/beyondmeetings/transcribe/__init__.py`
- Create: `src/beyondmeetings/transcribe/base.py`
- Create: `src/beyondmeetings/transcribe/groq.py`
- Test: `tests/test_transcribe_groq.py`

Two bugs die here: the hardcoded `node_modules` ffmpeg path, and the forced `language=en` that translates Hinglish instead of transcribing it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transcribe_groq.py
import pytest

from beyondmeetings.transcribe.groq import GroqTranscriber, resolve_ffmpeg


def test_resolve_ffmpeg_finds_binary_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    assert resolve_ffmpeg() == "/usr/bin/ffmpeg"


def test_resolve_ffmpeg_raises_with_actionable_message(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="ffmpeg"):
        resolve_ffmpeg()


def test_language_omitted_when_auto(httpx_mock, tmp_path):
    httpx_mock.add_response(text="hello world")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    GroqTranscriber(api_key="gsk", language="auto").transcribe_file(audio)
    body = httpx_mock.get_requests()[0].content
    assert b'name="language"' not in body


def test_language_sent_when_explicit(httpx_mock, tmp_path):
    httpx_mock.add_response(text="hello world")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    GroqTranscriber(api_key="gsk", language="hi").transcribe_file(audio)
    assert b'name="language"' in httpx_mock.get_requests()[0].content


def test_returns_transcript_text(httpx_mock, tmp_path):
    httpx_mock.add_response(text="the transcript")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    assert GroqTranscriber(api_key="gsk").transcribe_file(audio) == "the transcript"


def test_falls_back_to_second_model_on_failure(httpx_mock, tmp_path):
    httpx_mock.add_response(status_code=500, text="boom")
    httpx_mock.add_response(text="recovered")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    result = GroqTranscriber(api_key="gsk", max_attempts=1,
                             backoff_base=0).transcribe_file(audio)
    assert result == "recovered"


def test_rate_limit_waits_then_retries(httpx_mock, tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr("time.sleep", slept.append)
    httpx_mock.add_response(status_code=429, headers={"retry-after": "7"}, text="slow")
    httpx_mock.add_response(text="ok")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    assert GroqTranscriber(api_key="gsk").transcribe_file(audio) == "ok"
    assert 7 in slept


def test_raises_after_all_models_exhausted(httpx_mock, tmp_path):
    for _ in range(4):
        httpx_mock.add_response(status_code=500, text="boom")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    with pytest.raises(RuntimeError, match="transcription failed"):
        GroqTranscriber(api_key="gsk", max_attempts=2,
                        backoff_base=0).transcribe_file(audio)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_transcribe_groq.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.transcribe'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/transcribe/__init__.py
```

```python
# src/beyondmeetings/transcribe/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Transcriber(ABC):
    @abstractmethod
    def transcribe_file(self, audio: Path) -> str:
        """Return the transcript text for a single audio file."""
```

```python
# src/beyondmeetings/transcribe/groq.py
"""Groq Whisper adapter.

Fixes two bugs from the original shell pipeline: ffmpeg is resolved from PATH
rather than a hardcoded personal node_modules path, and the language is
configurable — forcing "en" made Whisper translate code-mixed speech instead
of transcribing it.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import httpx

from .base import Transcriber

API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODELS = ("whisper-large-v3", "whisper-large-v3-turbo")
TIMEOUT = 600.0


def resolve_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise FileNotFoundError(
            "ffmpeg not found on PATH. Install it with your package manager "
            "(apt install ffmpeg / dnf install ffmpeg / pacman -S ffmpeg)."
        )
    return found


def compress_for_upload(source: Path, dest: Path) -> Path:
    """Mono 16 kHz 32 kbps MP3 — small enough to upload, ample for speech."""
    subprocess.run(
        [resolve_ffmpeg(), "-i", str(source), "-ac", "1", "-ar", "16000",
         "-b:a", "32k", str(dest), "-y", "-loglevel", "error"],
        check=True,
    )
    return dest


class GroqTranscriber(Transcriber):
    def __init__(
        self,
        api_key: str,
        language: str = "auto",
        max_attempts: int = 3,
        backoff_base: float = 3.0,
    ):
        self.api_key = api_key
        self.language = language
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base

    def _post(self, audio: Path, model: str) -> httpx.Response:
        data = {"model": model, "response_format": "text"}
        if self.language and self.language != "auto":
            data["language"] = self.language
        with audio.open("rb") as fh:
            return httpx.post(
                API_URL,
                timeout=TIMEOUT,
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": (audio.name, fh, "audio/mpeg")},
                data=data,
            )

    def transcribe_file(self, audio: Path) -> str:
        last = ""
        for model in MODELS:
            for attempt in range(1, self.max_attempts + 1):
                response = self._post(audio, model)
                if response.status_code == 200:
                    return response.text.strip()

                last = f"HTTP {response.status_code}: {response.text[:200]}"
                if response.status_code == 429:
                    wait = float(response.headers.get("retry-after", 30))
                    time.sleep(wait)
                    continue
                time.sleep(self.backoff_base * attempt)

        raise RuntimeError(f"Groq transcription failed after all retries — {last}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_transcribe_groq.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/transcribe tests/test_transcribe_groq.py
git commit -m "feat: Groq transcriber (fixes B1 hardcoded ffmpeg, B5 forced language)"
```

---

## Task 15: Recording state (fixes bug B4)

**Files:**
- Create: `src/beyondmeetings/audio/__init__.py`
- Create: `src/beyondmeetings/audio/base.py`
- Test: `tests/test_audio_state.py`

Replaces six loose dotfiles in `~/meetings/` with one JSON state file.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audio_state.py
import pytest

from beyondmeetings.audio.base import RecordingState, clear_state, load_state, save_state


def _state():
    return RecordingState(
        name="standup", filename_base="2026-07-30_14-30_standup",
        date="2026-07-30", pid=4242, module_ids=[101, 102],
        segments=["/data/recordings/2026-07-30/seg_000.wav"],
        started_at="2026-07-30T14:30:00",
    )


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "state.json"
    save_state(_state(), path)
    assert load_state(path) == _state()


def test_load_returns_none_when_absent(tmp_path):
    assert load_state(tmp_path / "state.json") is None


def test_clear_removes_the_file(tmp_path):
    path = tmp_path / "state.json"
    save_state(_state(), path)
    clear_state(path)
    assert not path.exists()


def test_clear_is_safe_when_already_absent(tmp_path):
    clear_state(tmp_path / "state.json")


def test_load_raises_on_corrupt_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    with pytest.raises(ValueError):
        load_state(path)


def test_segment_paths_accumulate(tmp_path):
    path = tmp_path / "state.json"
    state = _state()
    state.segments.append("/data/recordings/2026-07-30/seg_001.wav")
    save_state(state, path)
    assert len(load_state(path).segments) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_audio_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.audio'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/audio/__init__.py
```

```python
# src/beyondmeetings/audio/base.py
"""Recorder interface and recording state.

One JSON file replaces the six dotfiles the shell pipeline scattered through
the home directory (.record_pid, .current_recording, .current_name,
.current_filename, .mix_modules, .current_followup).

macOS/Windows support means adding a sibling of pipewire.py implementing
Recorder — nothing else changes.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field


class RecordingState(BaseModel):
    name: str
    filename_base: str
    date: str
    pid: int
    module_ids: list[int] = Field(default_factory=list)
    segments: list[str] = Field(default_factory=list)
    started_at: str


def save_state(state: RecordingState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2))


def load_state(path: Path) -> RecordingState | None:
    if not path.exists():
        return None
    try:
        return RecordingState(**json.loads(path.read_text()))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"corrupt recording state at {path}: {exc}") from exc


def clear_state(path: Path) -> None:
    path.unlink(missing_ok=True)


class Recorder(ABC):
    @abstractmethod
    def start(self, name: str) -> RecordingState:
        ...

    @abstractmethod
    def stop(self) -> RecordingState:
        ...

    @abstractmethod
    def status(self) -> RecordingState | None:
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_audio_state.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/audio tests/test_audio_state.py
git commit -m "feat: unified recording state (fixes B4)"
```

---

## Task 16: PipeWire capture with segment rollover (fixes bug B2)

**Files:**
- Create: `src/beyondmeetings/audio/pipewire.py`
- Test: `tests/test_audio_pipewire.py`

The rollover the old `CLAUDE.md` documented but never implemented. Subprocess calls are injected so this is testable without a sound server.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audio_pipewire.py
from beyondmeetings.audio.pipewire import PipeWireRecorder, build_filename_base


class FakeRunner:
    """Records commands; returns canned stdout per command shape."""

    def __init__(self):
        self.commands = []
        self.next_module_id = 100

    def run(self, args) -> str:
        self.commands.append(args)
        if args[:2] == ["pactl", "load-module"]:
            self.next_module_id += 1
            return str(self.next_module_id)
        if args[:3] == ["pactl", "list", "sources"]:
            return "1\talsa_output.pci.monitor\n2\tmeeting_mix.monitor\n"
        if args[:2] == ["pactl", "info"]:
            return "Default Source: alsa_input.pci\n"
        return ""

    def spawn(self, args) -> int:
        self.commands.append(args)
        return 4242


def test_filename_base_is_slugified_with_timestamp():
    base = build_filename_base("Client Kickoff!", "2026-07-30", "14-30")
    assert base == "2026-07-30_14-30_client-kickoff"


def test_filename_base_falls_back_when_name_has_no_safe_chars():
    assert build_filename_base("!!!", "2026-07-30", "14-30") == "2026-07-30_14-30_meeting"


def test_start_creates_null_sink_first(tmp_path):
    runner = FakeRunner()
    PipeWireRecorder(data_dir=tmp_path, runner=runner).start("Standup")
    assert runner.commands[0][:3] == ["pactl", "load-module", "module-null-sink"]


def test_start_loops_monitors_excluding_the_mix_itself(tmp_path):
    runner = FakeRunner()
    PipeWireRecorder(data_dir=tmp_path, runner=runner).start("Standup")
    loopbacks = [c for c in runner.commands if "module-loopback" in c]
    sources = " ".join(" ".join(c) for c in loopbacks)
    assert "alsa_output.pci.monitor" in sources
    assert "source=meeting_mix.monitor" not in sources


def test_start_also_loops_the_default_microphone(tmp_path):
    runner = FakeRunner()
    PipeWireRecorder(data_dir=tmp_path, runner=runner).start("Standup")
    sources = " ".join(" ".join(c) for c in runner.commands)
    assert "alsa_input.pci" in sources


def test_start_records_module_ids_into_state(tmp_path):
    runner = FakeRunner()
    state = PipeWireRecorder(data_dir=tmp_path, runner=runner).start("Standup")
    assert len(state.module_ids) >= 2
    assert state.pid == 4242


def test_start_writes_first_segment_path(tmp_path):
    runner = FakeRunner()
    state = PipeWireRecorder(data_dir=tmp_path, runner=runner).start("Standup")
    assert state.segments[0].endswith("_seg000.wav")


def test_status_reflects_persisted_state(tmp_path):
    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    recorder.start("Standup")
    assert recorder.status().name == "Standup"


def test_stop_unloads_every_module(tmp_path):
    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    state = recorder.start("Standup")
    runner.commands.clear()
    recorder.stop()
    unloaded = [c[-1] for c in runner.commands if c[:2] == ["pactl", "unload-module"]]
    assert unloaded == [str(m) for m in state.module_ids]


def test_stop_clears_state(tmp_path):
    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    recorder.start("Standup")
    recorder.stop()
    assert recorder.status() is None


def test_stop_without_start_raises(tmp_path):
    import pytest
    with pytest.raises(RuntimeError, match="no active recording"):
        PipeWireRecorder(data_dir=tmp_path, runner=FakeRunner()).stop()


def test_roll_segment_appends_a_new_file_and_returns_the_finished_one(tmp_path):
    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    recorder.start("Standup")
    finished = recorder.roll_segment()
    state = recorder.status()
    assert finished.endswith("_seg000.wav")
    assert len(state.segments) == 2
    assert state.segments[1].endswith("_seg001.wav")


def test_stale_modules_are_cleaned_before_a_new_start(tmp_path):
    runner = FakeRunner()
    recorder = PipeWireRecorder(data_dir=tmp_path, runner=runner)
    recorder.start("First")
    runner.commands.clear()
    recorder.start("Second")
    assert any(c[:2] == ["pactl", "unload-module"] for c in runner.commands)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_audio_pipewire.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.audio.pipewire'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/audio/pipewire.py
"""Linux capture via a PipeWire null sink.

Every sink monitor plus the default microphone is looped into one mixing bus,
so no participant is missed regardless of which output device the call app
uses. Long meetings roll over into fresh segments so each can be transcribed
while the next records — this is what keeps a multi-hour meeting under Groq's
hourly audio-seconds cap.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from .base import Recorder, RecordingState, clear_state, load_state, save_state

MIX_SINK = "meeting_mix"


class SubprocessRunner:
    def run(self, args: list[str]) -> str:
        return subprocess.run(
            args, capture_output=True, text=True, check=False
        ).stdout.strip()

    def spawn(self, args: list[str]) -> int:
        return subprocess.Popen(args).pid


def build_filename_base(name: str, day: str, clock: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-")).strip("-")
    return f"{day}_{clock}_{slug or 'meeting'}"


class PipeWireRecorder(Recorder):
    def __init__(self, data_dir: Path, runner=None, segment_minutes: int = 50):
        self.data_dir = Path(data_dir)
        self.runner = runner or SubprocessRunner()
        self.segment_minutes = segment_minutes
        self.state_path = self.data_dir / "recording-state.json"

    # ---------- helpers ----------

    def _segment_path(self, state: RecordingState, index: int) -> Path:
        folder = self.data_dir / "recordings" / state.date
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{state.filename_base}_seg{index:03d}.wav"

    def _spawn_capture(self, target: Path) -> int:
        return self.runner.spawn(
            ["pw-record", "--target", f"{MIX_SINK}.monitor", str(target)]
        )

    def _teardown_modules(self, module_ids: list[int]) -> None:
        for module_id in reversed(module_ids):
            self.runner.run(["pactl", "unload-module", str(module_id)])

    # ---------- Recorder ----------

    def start(self, name: str) -> RecordingState:
        stale = load_state(self.state_path)
        if stale:
            self._teardown_modules(stale.module_ids)
            clear_state(self.state_path)

        now = datetime.now()
        day = now.strftime("%Y-%m-%d")
        base = build_filename_base(name, day, now.strftime("%H-%M"))

        module_ids: list[int] = []
        null_sink = self.runner.run(
            ["pactl", "load-module", "module-null-sink",
             f"sink_name={MIX_SINK}",
             f"sink_properties=device.description=MeetingMix"]
        )
        module_ids.append(int(null_sink))

        listing = self.runner.run(["pactl", "list", "sources", "short"])
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            source = parts[1]
            if not source.endswith(".monitor") or source.startswith(MIX_SINK):
                continue
            module_ids.append(int(self.runner.run(
                ["pactl", "load-module", "module-loopback",
                 f"source={source}", f"sink={MIX_SINK}"]
            )))

        info = self.runner.run(["pactl", "info"])
        match = re.search(r"^Default Source: (.+)$", info, re.MULTILINE)
        if match:
            module_ids.append(int(self.runner.run(
                ["pactl", "load-module", "module-loopback",
                 f"source={match.group(1).strip()}", f"sink={MIX_SINK}"]
            )))

        state = RecordingState(
            name=name, filename_base=base, date=day, pid=0,
            module_ids=module_ids, segments=[],
            started_at=now.isoformat(timespec="seconds"),
        )
        first = self._segment_path(state, 0)
        state.segments.append(str(first))
        state.pid = self._spawn_capture(first)

        save_state(state, self.state_path)
        return state

    def roll_segment(self) -> str:
        """End the current segment, start the next. Returns the finished path."""
        state = self.status()
        if not state:
            raise RuntimeError("no active recording")

        self.runner.run(["kill", str(state.pid)])
        finished = state.segments[-1]

        nxt = self._segment_path(state, len(state.segments))
        state.segments.append(str(nxt))
        state.pid = self._spawn_capture(nxt)
        save_state(state, self.state_path)
        return finished

    def stop(self) -> RecordingState:
        state = self.status()
        if not state:
            raise RuntimeError("no active recording")

        self.runner.run(["kill", str(state.pid)])
        self._teardown_modules(state.module_ids)
        clear_state(self.state_path)
        return state

    def status(self) -> RecordingState | None:
        return load_state(self.state_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_audio_pipewire.py -v`
Expected: PASS — 13 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/audio/pipewire.py tests/test_audio_pipewire.py
git commit -m "feat: PipeWire capture with segment rollover (fixes B2)"
```

---

## Task 17: Pipeline orchestration

**Files:**
- Create: `src/beyondmeetings/pipeline.py`
- Test: `tests/test_pipeline.py`

Ties everything together and enforces the informal-call rule.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
from pathlib import Path

from beyondmeetings.config import Config
from beyondmeetings.models import ActionItem, MeetingNote
from beyondmeetings.pipeline import generate_notes
from beyondmeetings.vault.scaffold import scaffold_vault


class StubProvider:
    def __init__(self, note):
        self.note = note
        self.prompts = []

    def analyse(self, prompt, valid_candidate_ids=None):
        self.prompts.append(prompt)
        return self.note


def _note(**overrides):
    base = dict(title="Phase 4 — Plan", date="2026-07-30",
                tags=["meeting", "Acme"],
                executive_summary="We planned.",
                one_line_summary="Licences approved",
                action_items=[ActionItem(task="Procure licences", owner="Sam",
                                         project="Acme", priority="HIGH")])
    base.update(overrides)
    return MeetingNote(**base)


def _setup(tmp_path, note):
    scaffold_vault(tmp_path)
    cfg = Config(vault_path=str(tmp_path), projects=["Acme"])
    return cfg, StubProvider(note)


def test_writes_note_at_dated_path_with_bare_filename(tmp_path):
    cfg, provider = _setup(tmp_path, _note())
    generate_notes("transcript text", cfg, provider)
    assert (tmp_path / "Meetings" / "2026-07-30" / "Phase 4 - Plan.md").is_file()


def test_adds_tasks_to_the_board(tmp_path):
    cfg, provider = _setup(tmp_path, _note())
    generate_notes("transcript text", cfg, provider)
    board = (tmp_path / "Tasks" / "Task Board.md").read_text()
    assert "**==Procure licences==**" in board
    assert "> [!todo]+ Pending — 1" in board


def test_informal_meeting_adds_no_tasks(tmp_path):
    cfg, provider = _setup(tmp_path, _note(is_informal=True))
    generate_notes("transcript text", cfg, provider)
    board = (tmp_path / "Tasks" / "Task Board.md").read_text()
    assert "**==Procure licences==**" not in board
    assert "> [!todo]+ Pending — 0" in board


def test_informal_meeting_still_writes_the_note(tmp_path):
    cfg, provider = _setup(tmp_path, _note(is_informal=True))
    generate_notes("transcript text", cfg, provider)
    assert (tmp_path / "Meetings" / "2026-07-30" / "Phase 4 - Plan.md").is_file()


def test_informal_meeting_still_appears_in_home_recent(tmp_path):
    cfg, provider = _setup(tmp_path, _note(is_informal=True))
    generate_notes("transcript text", cfg, provider)
    assert "Phase 4 - Plan" in (tmp_path / "Home.md").read_text()


def test_home_counters_match_the_board(tmp_path):
    cfg, provider = _setup(tmp_path, _note())
    generate_notes("transcript text", cfg, provider)
    assert "> [!todo]+ Pending — 1" in (tmp_path / "Home.md").read_text()


def test_follow_up_writes_backlink_into_previous_note(tmp_path):
    scaffold_vault(tmp_path)
    prev_dir = tmp_path / "Meetings" / "2026-07-29"
    prev_dir.mkdir(parents=True)
    (prev_dir / "Design QA Review.md").write_text(
        "---\ntags:\n  - meeting\ndate: 2026-07-29\n---\n\n"
        "# Design QA Review\n\n## Executive Summary\nReviewed designs.\n\n---\n"
    )
    cfg = Config(vault_path=str(tmp_path))
    provider = StubProvider(_note(follow_up_of="2026-07-29/Design QA Review"))
    generate_notes("transcript text", cfg, provider)
    prev = (prev_dir / "Design QA Review.md").read_text()
    assert "- Followed up in: [[Meetings/2026-07-30/Phase 4 - Plan]]" in prev


def test_follow_up_marker_appears_in_home(tmp_path):
    scaffold_vault(tmp_path)
    prev_dir = tmp_path / "Meetings" / "2026-07-29"
    prev_dir.mkdir(parents=True)
    (prev_dir / "Design QA Review.md").write_text(
        "---\ntags:\n  - meeting\ndate: 2026-07-29\n---\n\n"
        "# Design QA Review\n\n## Executive Summary\nReviewed designs.\n\n---\n"
    )
    cfg = Config(vault_path=str(tmp_path))
    provider = StubProvider(_note(follow_up_of="2026-07-29/Design QA Review"))
    generate_notes("transcript text", cfg, provider)
    assert "↳ follow-up to" in (tmp_path / "Home.md").read_text()


def test_candidates_are_passed_to_the_prompt(tmp_path):
    scaffold_vault(tmp_path)
    prev_dir = tmp_path / "Meetings" / "2026-07-29"
    prev_dir.mkdir(parents=True)
    (prev_dir / "Design QA Review.md").write_text(
        "---\ntags:\n  - meeting\ndate: 2026-07-29\n---\n\n"
        "# Design QA Review\n\n## Executive Summary\nReviewed designs.\n\n---\n"
    )
    cfg = Config(vault_path=str(tmp_path))
    provider = StubProvider(_note())
    generate_notes("transcript text", cfg, provider)
    assert "2026-07-29/Design QA Review" in provider.prompts[0]


def test_returns_the_written_note_path(tmp_path):
    cfg, provider = _setup(tmp_path, _note())
    result = generate_notes("transcript text", cfg, provider)
    assert result == tmp_path / "Meetings" / "2026-07-30" / "Phase 4 - Plan.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.pipeline'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/pipeline.py
"""Transcript in, vault updated.

Every write is deterministic. The provider's only influence is the content of
the MeetingNote it returns.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .config import Config
from .llm.base import LLMProvider
from .models import MeetingRef
from .prompts import build_analysis_prompt
from .vault import followup, home, note as note_render, taskboard
from .vault.paths import note_path


def generate_notes(
    transcript: str,
    config: Config,
    provider: LLMProvider,
    meeting_date: str | None = None,
) -> Path:
    vault = Path(config.vault_path)
    meeting_date = meeting_date or date.today().isoformat()

    candidates = followup.gather_candidates(vault)
    prompt = build_analysis_prompt(
        transcript, meeting_date, candidates, config.projects, config.notes_language
    )
    result = provider.analyse(prompt, [c.ref.id for c in candidates])

    ref = MeetingRef(date=result.date or meeting_date, title=result.title)

    # 1. The meeting note itself.
    path = note_path(vault, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        note_render.render_note(
            result, transcriber=config.transcriber, provider=config.provider
        ),
        encoding="utf-8",
    )

    # 2. Reciprocal follow-up link in the previous note.
    previous = None
    if result.follow_up_of:
        previous = MeetingRef.from_id(result.follow_up_of)
        prev_path = note_path(vault, previous)
        if prev_path.exists():
            followup.append_followup_backlink(prev_path, ref)
        else:
            previous = None

    # 3. Task Board — skipped entirely for informal/personal calls.
    board_path = vault / "Tasks" / "Task Board.md"
    board = board_path.read_text(encoding="utf-8")
    if result.action_items and not result.is_informal:
        board = taskboard.add_tasks(
            board, result.action_items, ref, result.one_line_summary or result.title
        )
        board_path.write_text(board, encoding="utf-8")
    pending = taskboard.count_pending(board)

    # 4. Home.md — always updated, counters kept in step with the board.
    home_path = vault / "Home.md"
    text = home_path.read_text(encoding="utf-8")
    project = next((t for t in result.tags if t.lower() != "meeting"), None)
    text = home.add_recent_meeting(
        text, ref, result.title, project,
        result.one_line_summary or result.executive_summary,
        previous=previous,
        previous_display=previous.title if previous else None,
    )
    text = home.sync_counters(text, pending)
    text = home.touch_updated(text, date.today().isoformat())
    home_path.write_text(text, encoding="utf-8")

    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline orchestration with informal-call rule"
```

---

## Task 18: CLI

**Files:**
- Create: `src/beyondmeetings/cli.py`
- Test: `tests/test_cli.py`

`start` with no name must never prompt — a meeting is already beginning.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import re

from beyondmeetings.cli import build_parser, placeholder_name


def test_start_accepts_a_name():
    args = build_parser().parse_args(["start", "Client Kickoff"])
    assert args.command == "start"
    assert args.name == "Client Kickoff"


def test_start_name_is_optional():
    args = build_parser().parse_args(["start"])
    assert args.name is None


def test_placeholder_name_uses_the_clock():
    assert re.fullmatch(r"recording-\d{2}-\d{2}", placeholder_name())


def test_stop_takes_no_arguments():
    assert build_parser().parse_args(["stop"]).command == "stop"


def test_notes_accepts_a_transcript_path():
    args = build_parser().parse_args(["notes", "/tmp/t.txt"])
    assert args.command == "notes"
    assert args.transcript == "/tmp/t.txt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/cli.py
"""Command-line entry point.

`start` never prompts for a name — a meeting is already under way, and every
second spent asking is audio lost. Unnamed recordings get a timestamp
placeholder and are retitled from the transcript at notes time.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .audio.pipewire import PipeWireRecorder
from .config import load_config
from .llm.anthropic import AnthropicProvider
from .pipeline import generate_notes
from .secrets import get_secret
from .transcribe.groq import GroqTranscriber, compress_for_upload


def placeholder_name() -> str:
    return datetime.now().strftime("recording-%H-%M")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beyondmeetings")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start recording")
    start.add_argument("name", nargs="?", default=None)

    sub.add_parser("stop", help="stop, transcribe and write notes")

    notes = sub.add_parser("notes", help="regenerate notes from a transcript")
    notes.add_argument("transcript")

    return parser


def _provider(config):
    key = get_secret("anthropic_api_key")
    if not key:
        raise SystemExit("No Anthropic API key stored. Run `beyondmeetings setup`.")
    return AnthropicProvider(api_key=key, model=config.model)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    data_dir = Path(config.data_dir)

    if args.command == "start":
        name = args.name or placeholder_name()
        recorder = PipeWireRecorder(data_dir, segment_minutes=config.segment_minutes)
        state = recorder.start(name)
        print(f"Recording started: {state.name}")
        return 0

    if args.command == "stop":
        recorder = PipeWireRecorder(data_dir, segment_minutes=config.segment_minutes)
        state = recorder.stop()

        key = get_secret("groq_api_key")
        if not key:
            raise SystemExit("No Groq API key stored. Run `beyondmeetings setup`.")
        transcriber = GroqTranscriber(api_key=key, language=config.spoken_language)

        parts = []
        for segment in state.segments:
            source = Path(segment)
            if not source.exists():
                continue
            mp3 = source.with_suffix(".mp3")
            compress_for_upload(source, mp3)
            parts.append(transcriber.transcribe_file(mp3))

        transcript = "\n".join(parts)
        folder = data_dir / "transcripts" / state.date
        folder.mkdir(parents=True, exist_ok=True)
        transcript_path = folder / f"{state.filename_base}.txt"
        transcript_path.write_text(transcript, encoding="utf-8")
        print(f"Transcript: {transcript_path}")

        path = generate_notes(transcript, config, _provider(config), state.date)
        print(f"Note written: {path}")
        return 0

    if args.command == "notes":
        transcript = Path(args.transcript).read_text(encoding="utf-8")
        path = generate_notes(transcript, config, _provider(config))
        print(f"Note written: {path}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/cli.py tests/test_cli.py
git commit -m "feat: CLI with non-blocking start"
```

---

## Task 19: Full suite green and manual verification

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/python -m pytest -v`
Expected: PASS — all tests across 14 files, zero failures

- [ ] **Step 2: Store keys and configure**

```bash
.venv/bin/python -c "
from beyondmeetings.secrets import set_secret
set_secret('groq_api_key', input('Groq key: ').strip())
set_secret('anthropic_api_key', input('Anthropic key: ').strip())
"
.venv/bin/python -c "
from beyondmeetings.config import Config, save_config
save_config(Config(vault_path='/home/you/Documents/Obsidian Vault',
                   projects=['Acme', 'Zenith']))
"
```

- [ ] **Step 3: Record a short real meeting**

```bash
.venv/bin/beyondmeetings start "Engine Smoke Test"
# speak for ~60 seconds, then:
.venv/bin/beyondmeetings stop
```

Expected: a transcript path and a note path are printed, both files exist.

- [ ] **Step 4: Verify vault output by hand**

Confirm each: note exists at `Meetings/YYYY-MM-DD/<Title>.md` with a real derived title (not `recording-HH-MM`); tasks appear in `Tasks/Task Board.md` as `> >` entries; the Pending counter matches in both `Task Board.md` and `Home.md`; the meeting appears at the top of Home's Recent callout.

- [ ] **Step 5: Update the tracker and commit**

Tick every milestone-1 box in `PROGRESS.md`, tick B1–B5, set milestone 1 to `[x]` and milestone 2 to `[~]`, and append a session-log line.

```bash
git add PROGRESS.md
git commit -m "docs: milestone 1 complete"
```

---

## Self-Review

**Spec coverage:** §2 architecture → Tasks 5–17. §4 data contract → Task 2. §5 preserved behaviour → Tasks 7, 9, 10, 11, 12, 17. §8 language handling → Tasks 3, 12, 14. §9 bugs B1–B5 → Tasks 14 (B1, B5), 16 (B2), 4 (B3), 15 (B4). §12 testing → every task. Milestone-1 items in `PROGRESS.md` all map to a task.

**Deferred to later milestones, by design:** `doctor/`, `server.py`, `web/`, `rules.py`, `mcp_setup.py`, `install.sh` (milestone 2); the other three providers and `whispercpp.py` (milestone 3); `tray.py` (milestone 4). `cli.py setup` is referenced in error messages and lands in milestone 2.

**Known gap accepted for milestone 1:** segment rollover is implemented and unit-tested (`roll_segment`), but nothing calls it on a timer yet — the scheduler belongs with the server's background loop in milestone 4. A meeting over 50 minutes still transcribes correctly as one segment via chunking; it simply does not yet get the rate-limit spreading benefit. Milestone 4 wires the timer.

**Type consistency checked:** `MeetingRef.id` / `from_id` used identically in Tasks 5, 11, 17. `count_pending` / `update_counters` / `add_tasks` signatures match between Tasks 9 and 17. `sync_counters` / `add_recent_meeting` / `touch_updated` match between Tasks 10 and 17. `Candidate` defined in Task 11, consumed in Tasks 12 and 17. `LLMProvider.analyse(prompt, valid_candidate_ids)` consistent across Tasks 5, 13, 17.
