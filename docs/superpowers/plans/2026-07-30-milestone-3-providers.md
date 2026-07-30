# beyondMeetings Milestone 3 — Providers, whisper.cpp and MCP

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provider choice becomes real — ChatGPT, Gemini and Ollama write notes as reliably as Claude; whisper.cpp offers fully-local transcription; and the wizard registers an Obsidian MCP into whichever agent CLI the user actually has.

**Architecture:** Three new `LLMProvider` implementations behind the existing interface, plus factories so `cli.py` stops hard-coding Anthropic. Every provider requests JSON natively where its API supports it, then routes through the existing `parse_meeting_note()`. MCP registration writes each agent's own config format, merging rather than replacing.

**Tech Stack:** Existing httpx/pydantic. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-30-beyondmeetings-setup-design.md` §6 (check 8), §1 (provider scope)
**Tracker:** `PROGRESS.md`

---

## Reconnaissance findings that shape this plan

Checked on the dev machine before planning:

| Finding | Consequence |
|---|---|
| `~/.claude.json` is **79 KB of real user config** | MCP registration must merge and write atomically with a backup. Clobbering it would destroy the user's entire Claude Code setup. |
| `codex` and `gemini` CLIs are **absent** | The "agent not installed, skipping" path is real and testable here, not hypothetical. |
| `npx` and `node` are present | `@modelcontextprotocol/server-filesystem` is a viable MCP with no plugin and no second API key. |
| `whisper-cli` exists but is **not on `PATH`** | Detection must search configured path → `PATH` → known build locations. |

**MCP choice:** `npx -y @modelcontextprotocol/server-filesystem <vault>`. The popular `mcp-obsidian` alternative requires installing Obsidian's Local REST API community plugin *and* copying a second key out of it — three more failure points for a bonus feature. The filesystem server scoped to the vault gives an agent read/write over the notes with zero extra setup.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/beyondmeetings/llm/openai.py` | ChatGPT adapter |
| `src/beyondmeetings/llm/gemini.py` | Gemini adapter |
| `src/beyondmeetings/llm/ollama.py` | Local Ollama adapter |
| `src/beyondmeetings/llm/factory.py` | `build_provider(config)` — replaces hardcoded Anthropic |
| `src/beyondmeetings/transcribe/whispercpp.py` | Local transcription + model download |
| `src/beyondmeetings/transcribe/factory.py` | `build_transcriber(config)` |
| `src/beyondmeetings/mcp_setup.py` | Write Obsidian MCP into each agent's config |
| `src/beyondmeetings/doctor/mcp.py` | MCP registration check |
| `src/beyondmeetings/doctor/choices.py` | Provider + transcriber picker checks |
| `src/beyondmeetings/web/setup.js` | Render radio-style choice rows |

---

## Task 1: Provider factory

**Files:**
- Create: `src/beyondmeetings/llm/factory.py`
- Modify: `src/beyondmeetings/cli.py` (replace `_provider`)
- Test: `tests/test_llm_factory.py`

`cli.py` currently hardcodes `AnthropicProvider`. Nothing else can work until that changes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_factory.py
import pytest

from beyondmeetings.config import Config
from beyondmeetings.llm.anthropic import AnthropicProvider
from beyondmeetings.llm.factory import MissingKeyError, build_provider


def test_builds_anthropic_by_default(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: "sk-x")
    assert isinstance(build_provider(Config()), AnthropicProvider)


def test_builds_each_supported_provider(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: "key")
    for name in ("anthropic", "openai", "gemini"):
        provider = build_provider(Config(provider=name))
        assert provider.__class__.__name__.lower().startswith(name[:4])


def test_ollama_needs_no_key(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: None)
    assert build_provider(Config(provider="ollama")) is not None


def test_missing_key_raises_with_actionable_message(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: None)
    with pytest.raises(MissingKeyError, match="beyondmeetings setup"):
        build_provider(Config(provider="anthropic"))


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: "k")
    with pytest.raises(ValueError, match="unknown provider"):
        build_provider(Config(provider="nope"))


def test_configured_model_overrides_the_default(monkeypatch):
    monkeypatch.setattr("beyondmeetings.llm.factory.get_secret", lambda *a, **k: "k")
    provider = build_provider(Config(provider="anthropic", model="claude-sonnet-5"))
    assert provider.model == "claude-sonnet-5"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beyondmeetings.llm.factory'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/llm/factory.py
"""Build the configured note-writing provider."""
from __future__ import annotations

from ..config import Config
from ..labels import provider_label
from ..secrets import get_secret
from .anthropic import AnthropicProvider
from .base import LLMProvider
from .gemini import GeminiProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider


class MissingKeyError(RuntimeError):
    """No API key stored for the configured provider."""


# Ollama runs locally and needs no key.
KEYED = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}


def build_provider(config: Config) -> LLMProvider:
    name = config.provider

    if name == "ollama":
        return OllamaProvider(model=config.model, host=config.ollama_host)

    cls = KEYED.get(name)
    if cls is None:
        raise ValueError(f"unknown provider: {name}")

    key = get_secret(f"{name}_api_key")
    if not key:
        raise MissingKeyError(
            f"No {provider_label(name)} API key stored. "
            "Run `beyondmeetings setup` to add one."
        )
    return cls(api_key=key, model=config.model)
```

Add `ollama_host: str = "http://localhost:11434"` to `Config` in `config.py`.

Replace `_provider()` in `cli.py`:

```python
def _provider(config):
    from .llm.factory import MissingKeyError, build_provider

    try:
        return build_provider(config)
    except (MissingKeyError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
```

Remove the now-unused `AnthropicProvider` and `get_secret` imports from `cli.py` if nothing else uses them (`get_secret` is still used for the Groq key).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_llm_factory.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/llm/factory.py src/beyondmeetings/config.py src/beyondmeetings/cli.py tests/test_llm_factory.py
git commit -m "feat: provider factory replacing hardcoded Anthropic"
```

---

## Task 2: OpenAI adapter

**Files:**
- Create: `src/beyondmeetings/llm/openai.py`
- Test: `tests/test_llm_openai.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_openai.py
import json

import pytest

from beyondmeetings.llm.base import ResponseParseError
from beyondmeetings.llm.openai import OpenAIProvider

NOTE_JSON = ('{"title": "Standup", "date": "2026-07-30", '
             '"executive_summary": "We synced."}')
BODY = {"choices": [{"message": {"content": NOTE_JSON}}]}


def test_returns_parsed_note(httpx_mock):
    httpx_mock.add_response(json=BODY)
    assert OpenAIProvider(api_key="sk-t").analyse("prompt").title == "Standup"


def test_sends_bearer_authorization(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OpenAIProvider(api_key="sk-t").analyse("prompt")
    assert httpx_mock.get_requests()[0].headers["authorization"] == "Bearer sk-t"


def test_requests_json_object_response_format(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OpenAIProvider(api_key="sk-t").analyse("prompt")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["response_format"] == {"type": "json_object"}


def test_sends_prompt_as_user_message(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OpenAIProvider(api_key="sk-t").analyse("analyse this")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["messages"][-1]["content"] == "analyse this"


def test_http_error_surfaces_the_api_message(httpx_mock):
    httpx_mock.add_response(status_code=401, json={"error": {"message": "bad key"}})
    with pytest.raises(RuntimeError, match="bad key"):
        OpenAIProvider(api_key="sk-bad").analyse("prompt")


def test_unparseable_content_raises_parse_error(httpx_mock):
    httpx_mock.add_response(json={"choices": [{"message": {"content": "sorry"}}]})
    with pytest.raises(ResponseParseError):
        OpenAIProvider(api_key="sk-t").analyse("prompt")


def test_candidate_ids_are_enforced(httpx_mock):
    raw = NOTE_JSON[:-1] + ', "follow_up_of": "2020-01-01/Invented"}'
    httpx_mock.add_response(json={"choices": [{"message": {"content": raw}}]})
    note = OpenAIProvider(api_key="sk-t").analyse("p", valid_candidate_ids=[])
    assert note.follow_up_of is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_openai.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/llm/openai.py
"""ChatGPT adapter.

Uses the chat-completions API with native JSON mode, which removes most of
the fence-and-prose repair the parser would otherwise have to do.
"""
from __future__ import annotations

import httpx

from ..models import MeetingNote
from .base import LLMProvider, parse_meeting_note

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o"
TIMEOUT = 300.0

SYSTEM = "You analyse meeting transcripts and reply with a single JSON object."


class OpenAIProvider(LLMProvider):
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
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_completion_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        if response.status_code != 200:
            detail = response.json().get("error", {}).get("message", response.text)
            raise RuntimeError(f"OpenAI API error {response.status_code}: {detail}")

        choices = response.json().get("choices", [])
        text = choices[0]["message"]["content"] if choices else ""
        return parse_meeting_note(text, valid_candidate_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_llm_openai.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/llm/openai.py tests/test_llm_openai.py
git commit -m "feat: OpenAI provider adapter"
```

---

## Task 3: Gemini adapter

**Files:**
- Create: `src/beyondmeetings/llm/gemini.py`
- Test: `tests/test_llm_gemini.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_gemini.py
import json

import pytest

from beyondmeetings.llm.base import ResponseParseError
from beyondmeetings.llm.gemini import GeminiProvider

NOTE_JSON = ('{"title": "Standup", "date": "2026-07-30", '
             '"executive_summary": "We synced."}')
BODY = {"candidates": [{"content": {"parts": [{"text": NOTE_JSON}]}}]}


def test_returns_parsed_note(httpx_mock):
    httpx_mock.add_response(json=BODY)
    assert GeminiProvider(api_key="k").analyse("prompt").title == "Standup"


def test_sends_key_as_header_not_query_string(httpx_mock):
    """A key in the URL leaks into logs and proxies."""
    httpx_mock.add_response(json=BODY)
    GeminiProvider(api_key="secret-key").analyse("prompt")
    request = httpx_mock.get_requests()[0]
    assert request.headers["x-goog-api-key"] == "secret-key"
    assert "secret-key" not in str(request.url)


def test_requests_json_response_mime_type(httpx_mock):
    httpx_mock.add_response(json=BODY)
    GeminiProvider(api_key="k").analyse("prompt")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


def test_sends_prompt_text(httpx_mock):
    httpx_mock.add_response(json=BODY)
    GeminiProvider(api_key="k").analyse("analyse this")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["contents"][0]["parts"][0]["text"] == "analyse this"


def test_http_error_surfaces_the_api_message(httpx_mock):
    httpx_mock.add_response(status_code=400, json={"error": {"message": "bad key"}})
    with pytest.raises(RuntimeError, match="bad key"):
        GeminiProvider(api_key="bad").analyse("prompt")


def test_joins_multiple_parts(httpx_mock):
    half, rest = NOTE_JSON[:20], NOTE_JSON[20:]
    httpx_mock.add_response(json={"candidates": [
        {"content": {"parts": [{"text": half}, {"text": rest}]}}]})
    assert GeminiProvider(api_key="k").analyse("p").title == "Standup"


def test_empty_candidates_raises_parse_error(httpx_mock):
    httpx_mock.add_response(json={"candidates": []})
    with pytest.raises(ResponseParseError):
        GeminiProvider(api_key="k").analyse("prompt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_gemini.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/llm/gemini.py
"""Gemini adapter.

The key travels in a header, never the query string — URLs end up in access
logs and proxy caches.
"""
from __future__ import annotations

import httpx

from ..models import MeetingNote
from .base import LLMProvider, parse_meeting_note

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.0-flash"
TIMEOUT = 300.0


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "", max_tokens: int = 8000):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.max_tokens = max_tokens

    def analyse(
        self, prompt: str, valid_candidate_ids: list[str] | None = None
    ) -> MeetingNote:
        response = httpx.post(
            f"{BASE_URL}/{self.model}:generateContent",
            timeout=TIMEOUT,
            headers={
                "x-goog-api-key": self.api_key,
                "content-type": "application/json",
            },
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "maxOutputTokens": self.max_tokens,
                },
            },
        )
        if response.status_code != 200:
            detail = response.json().get("error", {}).get("message", response.text)
            raise RuntimeError(f"Gemini API error {response.status_code}: {detail}")

        candidates = response.json().get("candidates", [])
        parts = candidates[0]["content"]["parts"] if candidates else []
        text = "".join(p.get("text", "") for p in parts)
        return parse_meeting_note(text, valid_candidate_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_llm_gemini.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/llm/gemini.py tests/test_llm_gemini.py
git commit -m "feat: Gemini provider adapter"
```

---

## Task 4: Ollama adapter

**Files:**
- Create: `src/beyondmeetings/llm/ollama.py`
- Test: `tests/test_llm_ollama.py`

Fully local, no key. Its failure modes are different: the daemon may not be running, or the model may not be pulled.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_ollama.py
import json

import httpx
import pytest

from beyondmeetings.llm.base import ResponseParseError
from beyondmeetings.llm.ollama import OllamaProvider

NOTE_JSON = ('{"title": "Standup", "date": "2026-07-30", '
             '"executive_summary": "We synced."}')
BODY = {"message": {"content": NOTE_JSON}}


def test_returns_parsed_note(httpx_mock):
    httpx_mock.add_response(json=BODY)
    assert OllamaProvider().analyse("prompt").title == "Standup"


def test_posts_to_the_configured_host(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OllamaProvider(host="http://box:1234").analyse("prompt")
    assert str(httpx_mock.get_requests()[0].url).startswith("http://box:1234")


def test_requests_json_format_and_disables_streaming(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OllamaProvider().analyse("prompt")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["format"] == "json"
    assert payload["stream"] is False


def test_daemon_not_running_gives_an_actionable_error(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    with pytest.raises(RuntimeError, match="ollama serve"):
        OllamaProvider().analyse("prompt")


def test_missing_model_error_suggests_pulling_it(httpx_mock):
    httpx_mock.add_response(status_code=404, json={"error": "model not found"})
    with pytest.raises(RuntimeError, match="ollama pull"):
        OllamaProvider(model="qwen2.5:14b").analyse("prompt")


def test_unparseable_content_raises_parse_error(httpx_mock):
    httpx_mock.add_response(json={"message": {"content": "I cannot"}})
    with pytest.raises(ResponseParseError):
        OllamaProvider().analyse("prompt")


def test_default_model_is_reported_on_the_instance():
    assert OllamaProvider().model
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_ollama.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/llm/ollama.py
"""Local Ollama adapter.

No API key and nothing leaves the machine. Its failure modes are a stopped
daemon or an un-pulled model, so both get an actionable message rather than a
bare HTTP error.
"""
from __future__ import annotations

import httpx

from ..models import MeetingNote
from .base import LLMProvider, parse_meeting_note

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:14b"
TIMEOUT = 900.0  # local inference on CPU is slow


class OllamaProvider(LLMProvider):
    def __init__(self, model: str = "", host: str = DEFAULT_HOST):
        self.model = model or DEFAULT_MODEL
        self.host = (host or DEFAULT_HOST).rstrip("/")

    def analyse(
        self, prompt: str, valid_candidate_ids: list[str] | None = None
    ) -> MeetingNote:
        try:
            response = httpx.post(
                f"{self.host}/api/chat",
                timeout=TIMEOUT,
                json={
                    "model": self.model,
                    "format": "json",
                    "stream": False,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.host} ({exc}). "
                "Start it with `ollama serve`."
            ) from exc

        if response.status_code == 404:
            raise RuntimeError(
                f"Ollama does not have model '{self.model}'. "
                f"Pull it with `ollama pull {self.model}`."
            )
        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama error {response.status_code}: {response.text[:200]}"
            )

        text = response.json().get("message", {}).get("content", "")
        return parse_meeting_note(text, valid_candidate_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_llm_ollama.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/llm/ollama.py tests/test_llm_ollama.py
git commit -m "feat: Ollama provider adapter"
```

---

## Task 5: Key validators for the new providers

**Files:**
- Modify: `src/beyondmeetings/doctor/keys.py`
- Test: `tests/test_doctor_keys_providers.py`

`VALIDATORS` currently has `None` for the three new providers, returning "arrives in milestone 3". Time to fill them in.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_keys_providers.py
import httpx

from beyondmeetings.doctor.keys import (
    ProviderKeyCheck, validate_gemini_key, validate_ollama, validate_openai_key,
)


class _BrokenKeyring:
    def set_password(self, *a): raise RuntimeError("no backend")
    def get_password(self, *a): raise RuntimeError("no backend")


def test_openai_accepts_a_working_key(httpx_mock):
    httpx_mock.add_response(json={"data": []})
    assert validate_openai_key("sk-good") == (True, "")


def test_openai_rejects_a_bad_key(httpx_mock):
    httpx_mock.add_response(status_code=401, json={"error": {"message": "nope"}})
    ok, detail = validate_openai_key("sk-bad")
    assert ok is False and "nope" in detail


def test_gemini_accepts_a_working_key(httpx_mock):
    httpx_mock.add_response(json={"models": []})
    assert validate_gemini_key("good") == (True, "")


def test_gemini_sends_the_key_in_a_header(httpx_mock):
    httpx_mock.add_response(json={"models": []})
    validate_gemini_key("secret")
    request = httpx_mock.get_requests()[0]
    assert request.headers["x-goog-api-key"] == "secret"
    assert "secret" not in str(request.url)


def test_ollama_ok_when_daemon_responds(httpx_mock):
    httpx_mock.add_response(json={"models": [{"name": "qwen2.5:14b"}]})
    assert validate_ollama("http://localhost:11434", "qwen2.5:14b") == (True, "")


def test_ollama_reports_a_stopped_daemon(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    ok, detail = validate_ollama("http://localhost:11434", "qwen2.5:14b")
    assert ok is False and "ollama serve" in detail


def test_ollama_reports_a_model_that_is_not_pulled(httpx_mock):
    httpx_mock.add_response(json={"models": [{"name": "llama3:8b"}]})
    ok, detail = validate_ollama("http://localhost:11434", "qwen2.5:14b")
    assert ok is False and "ollama pull qwen2.5:14b" in detail


def test_ollama_provider_check_needs_no_key_input(tmp_path):
    check = ProviderKeyCheck(provider="ollama", secret_dir=tmp_path)
    assert check.inputs == []


def test_ollama_check_ok_without_any_stored_secret(tmp_path, httpx_mock, monkeypatch):
    from beyondmeetings import secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", _BrokenKeyring())
    httpx_mock.add_response(json={"models": [{"name": "qwen2.5:14b"}]})
    check = ProviderKeyCheck(provider="ollama", secret_dir=tmp_path)
    assert check.detect().status == "ok"


def test_openai_check_stores_a_validated_key(tmp_path, httpx_mock, monkeypatch):
    from beyondmeetings import secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", _BrokenKeyring())
    httpx_mock.add_response(json={"data": []})
    httpx_mock.add_response(json={"data": []})
    check = ProviderKeyCheck(provider="openai", secret_dir=tmp_path)
    assert check.fix(api_key="sk-new").status == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_doctor_keys_providers.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_openai_key'`

- [ ] **Step 3: Write minimal implementation**

In `doctor/keys.py`, add the validators, replace the `VALIDATORS` table, and special-case Ollama in `ProviderKeyCheck` (it has no key to store):

```python
def validate_openai_key(api_key: str) -> tuple[bool, str]:
    try:
        response = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return False, f"Could not reach OpenAI: {exc}"
    return (True, "") if response.status_code == 200 else (False, _error_detail(response))


def validate_gemini_key(api_key: str) -> tuple[bool, str]:
    try:
        response = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return False, f"Could not reach Gemini: {exc}"
    return (True, "") if response.status_code == 200 else (False, _error_detail(response))


def validate_ollama(host: str, model: str) -> tuple[bool, str]:
    """Ollama has no key — check the daemon is up and the model is pulled."""
    try:
        response = httpx.get(f"{host.rstrip('/')}/api/tags", timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        return False, (
            f"Could not reach Ollama at {host} ({exc}). Start it with `ollama serve`."
        )
    if response.status_code != 200:
        return False, _error_detail(response)

    names = [m.get("name", "") for m in response.json().get("models", [])]
    if model not in names:
        available = ", ".join(names) or "none"
        return False, (
            f"Model '{model}' is not pulled. Run `ollama pull {model}`. "
            f"Available: {available}."
        )
    return True, ""


VALIDATORS = {
    "anthropic": validate_anthropic_key,
    "openai": validate_openai_key,
    "gemini": validate_gemini_key,
    "ollama": None,  # handled separately — no key to store
}
```

Rework `ProviderKeyCheck` so Ollama takes a different path:

```python
class ProviderKeyCheck(_KeyCheck):
    id = "provider_key"
    description = "Writes your meeting notes."

    def __init__(
        self,
        provider: str,
        secret_dir: Path | None = None,
        ollama_host: str = "http://localhost:11434",
        model: str = "",
    ):
        if provider not in VALIDATORS:
            raise ValueError(f"unknown provider: {provider}")
        super().__init__(secret_dir)
        self.provider = provider
        self.secret_name = f"{provider}_api_key"
        self.ollama_host = ollama_host
        self.model = model

        if provider == "ollama":
            self.label = "Ollama (local)"
            self.description = "Runs on your machine. No API key needed."
            self.inputs = []
        else:
            self.label = f"{provider_label(provider)} API key"
            self.inputs = [
                InputField(
                    name="api_key",
                    label=f"{provider_label(provider)} API key",
                    placeholder="sk-…",
                    secret=True,
                )
            ]

    def _ollama_model(self) -> str:
        from ..llm.ollama import DEFAULT_MODEL

        return self.model or DEFAULT_MODEL

    def detect(self) -> CheckResult:
        if self.provider == "ollama":
            ok, detail = validate_ollama(self.ollama_host, self._ollama_model())
            if ok:
                return CheckResult(
                    status="ok", detail=f"{self._ollama_model()} available locally"
                )
            return CheckResult(status="missing", detail=detail)
        return super().detect()

    @property
    def fixable(self) -> bool:
        # Nothing to fix for Ollama from here — the user must start it or pull.
        return self.provider != "ollama"

    def _validate(self, api_key: str) -> tuple[bool, str]:
        return VALIDATORS[self.provider](api_key)
```

Update `doctor/registry.py` to pass the extra arguments:

```python
        ProviderKeyCheck(
            provider=config.provider,
            secret_dir=secret_dir,
            ollama_host=config.ollama_host,
            model=config.model,
        ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_doctor_keys_providers.py tests/test_doctor_keys.py -v`
Expected: PASS — all passed. The old `test_unsupported_provider_explains_it_arrives_later` test must be **updated**, since OpenAI is now supported; replace it with a test that a valid OpenAI key is accepted.

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/doctor tests/test_doctor_keys_providers.py tests/test_doctor_keys.py
git commit -m "feat: key validation for OpenAI, Gemini and Ollama"
```

---

## Task 6: whisper.cpp transcriber

**Files:**
- Create: `src/beyondmeetings/transcribe/whispercpp.py`
- Test: `tests/test_transcribe_whispercpp.py`

Detection must search a configured path, then `PATH`, then known build locations — on the dev machine the binary exists but is not on `PATH`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transcribe_whispercpp.py
import pytest

from beyondmeetings.transcribe.whispercpp import (
    MODEL_URL, WhisperCppTranscriber, resolve_whisper_binary,
)


def test_prefers_an_explicitly_configured_binary(tmp_path):
    binary = tmp_path / "whisper-cli"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    assert resolve_whisper_binary(str(binary)) == str(binary)


def test_falls_back_to_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/whisper-cli")
    assert resolve_whisper_binary("") == "/usr/bin/whisper-cli"


def test_searches_known_build_locations(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda n: None)
    built = tmp_path / "whispercpp" / "whisper.cpp" / "build" / "bin"
    built.mkdir(parents=True)
    binary = built / "whisper-cli"
    binary.write_text("")
    binary.chmod(0o755)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert resolve_whisper_binary("") == str(binary)


def test_raises_with_build_instructions_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda n: None)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    with pytest.raises(FileNotFoundError, match="whisper.cpp"):
        resolve_whisper_binary("")


def test_configured_path_that_does_not_exist_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/whisper-cli")
    assert resolve_whisper_binary("/nope/whisper-cli") == "/usr/bin/whisper-cli"


def test_model_url_is_derived_from_the_model_name():
    assert "ggml-medium.en.bin" in MODEL_URL.format(model="medium.en")


def test_transcribe_invokes_the_binary_with_the_model(tmp_path):
    calls = []

    def runner(args):
        calls.append(args)
        # whisper-cli writes <output>.txt
        out = args[args.index("--output-file") + 1]
        open(f"{out}.txt", "w").write("the transcript")
        return 0

    binary = tmp_path / "whisper-cli"
    binary.write_text("")
    binary.chmod(0o755)
    model = tmp_path / "ggml-medium.en.bin"
    model.write_bytes(b"x")
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")

    t = WhisperCppTranscriber(binary=str(binary), model_path=str(model), runner=runner)
    assert t.transcribe_file(audio) == "the transcript"
    assert str(model) in calls[0]


def test_transcribe_raises_when_the_binary_fails(tmp_path):
    binary = tmp_path / "whisper-cli"
    binary.write_text("")
    binary.chmod(0o755)
    model = tmp_path / "m.bin"
    model.write_bytes(b"x")
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    t = WhisperCppTranscriber(
        binary=str(binary), model_path=str(model), runner=lambda a: 1
    )
    with pytest.raises(RuntimeError, match="whisper.cpp failed"):
        t.transcribe_file(audio)


def test_language_flag_omitted_when_auto(tmp_path):
    calls = []

    def runner(args):
        calls.append(args)
        open(f"{args[args.index('--output-file') + 1]}.txt", "w").write("t")
        return 0

    for name in ("whisper-cli", "m.bin", "a.wav"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "whisper-cli").chmod(0o755)

    t = WhisperCppTranscriber(
        binary=str(tmp_path / "whisper-cli"),
        model_path=str(tmp_path / "m.bin"),
        language="auto",
        runner=runner,
    )
    t.transcribe_file(tmp_path / "a.wav")
    assert "--language" not in calls[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_transcribe_whispercpp.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/transcribe/whispercpp.py
"""Local transcription via whisper.cpp.

Nothing leaves the machine. The binary has to be built by the user — that
needs a compiler and is not something an installer should attempt silently —
but the model file can be downloaded automatically.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import httpx

from .base import Transcriber

MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin"
)
DEFAULT_MODEL_NAME = "medium.en"

# whisper.cpp is usually built from source rather than packaged.
KNOWN_LOCATIONS = (
    "whispercpp/whisper.cpp/build/bin/whisper-cli",
    "whisper.cpp/build/bin/whisper-cli",
    ".local/share/beyondmeetings/whisper.cpp/build/bin/whisper-cli",
)

BUILD_HINT = (
    "whisper.cpp not found. Build it:\n"
    "  git clone https://github.com/ggerganov/whisper.cpp\n"
    "  cd whisper.cpp && cmake -B build && cmake --build build -j\n"
    "Then set whisper_binary in ~/.config/beyondmeetings/config.toml."
)


def resolve_whisper_binary(configured: str = "") -> str:
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    found = shutil.which("whisper-cli") or shutil.which("main")
    if found:
        return found

    for relative in KNOWN_LOCATIONS:
        candidate = Path.home() / relative
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise FileNotFoundError(BUILD_HINT)


def default_model_path(model: str = DEFAULT_MODEL_NAME) -> Path:
    return (
        Path.home() / ".local" / "share" / "beyondmeetings" / "models"
        / f"ggml-{model}.bin"
    )


def download_model(
    model: str = DEFAULT_MODEL_NAME,
    dest: Path | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Fetch a ggml model. ~1.5 GB for medium.en, so progress is reported."""
    dest = Path(dest or default_model_path(model))
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    partial = dest.with_suffix(".partial")
    with httpx.stream(
        "GET", MODEL_URL.format(model=model), follow_redirects=True, timeout=None
    ) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        done = 0
        with partial.open("wb") as fh:
            for chunk in response.iter_bytes(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
    partial.replace(dest)
    return dest


def _run(args: list[str]) -> int:
    return subprocess.run(args, capture_output=True, text=True).returncode


class WhisperCppTranscriber(Transcriber):
    def __init__(
        self,
        binary: str = "",
        model_path: str = "",
        language: str = "auto",
        threads: int = 0,
        runner: Callable[[list[str]], int] | None = None,
    ):
        self.binary = binary or resolve_whisper_binary()
        self.model_path = model_path or str(default_model_path())
        self.language = language
        self.threads = threads or (os.cpu_count() or 4)
        self.runner = runner or _run

    def transcribe_file(self, audio: Path) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            stem = str(Path(tmp) / "out")
            args = [
                self.binary,
                "--model", self.model_path,
                "--file", str(audio),
                "--output-txt",
                "--output-file", stem,
                "--threads", str(self.threads),
                "--no-prints",
            ]
            if self.language and self.language != "auto":
                args += ["--language", self.language]

            if self.runner(args) != 0:
                raise RuntimeError(
                    f"whisper.cpp failed on {audio.name}. "
                    f"Check the model at {self.model_path}."
                )

            produced = Path(f"{stem}.txt")
            if not produced.is_file():
                raise RuntimeError(
                    f"whisper.cpp produced no transcript for {audio.name}."
                )
            return produced.read_text(encoding="utf-8", errors="replace").strip()
```

Add to `Config`: `whisper_binary: str = ""`, `whisper_model: str = "medium.en"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_transcribe_whispercpp.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/transcribe/whispercpp.py src/beyondmeetings/config.py tests/test_transcribe_whispercpp.py
git commit -m "feat: local whisper.cpp transcription"
```

---

## Task 7: Transcriber factory and check

**Files:**
- Create: `src/beyondmeetings/transcribe/factory.py`
- Modify: `src/beyondmeetings/cli.py`, `src/beyondmeetings/doctor/registry.py`
- Create: `src/beyondmeetings/doctor/transcriber.py`
- Test: `tests/test_transcribe_factory.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transcribe_factory.py
import pytest

from beyondmeetings.config import Config
from beyondmeetings.doctor.transcriber import WhisperModelCheck
from beyondmeetings.transcribe.factory import build_transcriber
from beyondmeetings.transcribe.groq import GroqTranscriber


def test_builds_groq_by_default(monkeypatch):
    monkeypatch.setattr(
        "beyondmeetings.transcribe.factory.get_secret", lambda *a, **k: "gsk"
    )
    assert isinstance(build_transcriber(Config()), GroqTranscriber)


def test_groq_without_a_key_raises_actionably(monkeypatch):
    monkeypatch.setattr(
        "beyondmeetings.transcribe.factory.get_secret", lambda *a, **k: None
    )
    with pytest.raises(RuntimeError, match="beyondmeetings setup"):
        build_transcriber(Config(transcriber="groq"))


def test_builds_whispercpp_when_configured(tmp_path, monkeypatch):
    binary = tmp_path / "whisper-cli"
    binary.write_text("")
    binary.chmod(0o755)
    cfg = Config(transcriber="whispercpp", whisper_binary=str(binary))
    assert build_transcriber(cfg).binary == str(binary)


def test_unknown_transcriber_raises():
    with pytest.raises(ValueError, match="unknown transcriber"):
        build_transcriber(Config(transcriber="nope"))


def test_spoken_language_is_passed_through(monkeypatch):
    monkeypatch.setattr(
        "beyondmeetings.transcribe.factory.get_secret", lambda *a, **k: "gsk"
    )
    assert build_transcriber(Config(spoken_language="hi")).language == "hi"


def test_model_check_is_skipped_when_using_groq(tmp_path):
    check = WhisperModelCheck(Config(transcriber="groq"))
    assert check.detect().status == "ok"
    assert check.required is False


def test_model_check_missing_when_model_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    check = WhisperModelCheck(Config(transcriber="whispercpp"))
    assert check.detect().status == "missing"


def test_model_check_ok_when_model_present(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    model = tmp_path / ".local" / "share" / "beyondmeetings" / "models"
    model.mkdir(parents=True)
    (model / "ggml-medium.en.bin").write_bytes(b"x" * 10)
    assert WhisperModelCheck(Config(transcriber="whispercpp")).detect().status == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_transcribe_factory.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/transcribe/factory.py
"""Build the configured transcriber."""
from __future__ import annotations

from ..config import Config
from ..secrets import get_secret
from .base import Transcriber
from .groq import GroqTranscriber
from .whispercpp import WhisperCppTranscriber


def build_transcriber(config: Config) -> Transcriber:
    if config.transcriber == "groq":
        key = get_secret("groq_api_key")
        if not key:
            raise RuntimeError(
                "No Groq API key stored. Run `beyondmeetings setup` to add one, "
                "or switch to local transcription."
            )
        return GroqTranscriber(api_key=key, language=config.spoken_language)

    if config.transcriber == "whispercpp":
        return WhisperCppTranscriber(
            binary=config.whisper_binary,
            language=config.spoken_language,
        )

    raise ValueError(f"unknown transcriber: {config.transcriber}")
```

```python
# src/beyondmeetings/doctor/transcriber.py
"""Whisper model presence — only relevant for local transcription."""
from __future__ import annotations

from ..config import Config
from ..transcribe.whispercpp import default_model_path
from .base import Check, CheckResult


class WhisperModelCheck(Check):
    id = "whisper_model"
    label = "Local speech model"
    description = "The whisper.cpp model file used for offline transcription."
    required = False

    def __init__(self, config: Config):
        self.config = config

    def detect(self) -> CheckResult:
        if self.config.transcriber != "whispercpp":
            return CheckResult(status="ok", detail="Not needed — using Groq.")

        path = default_model_path(self.config.whisper_model)
        if path.is_file() and path.stat().st_size > 0:
            return CheckResult(status="ok", detail=str(path))
        return CheckResult(
            status="missing",
            detail=f"Model {self.config.whisper_model} not downloaded (~1.5 GB).",
        )

    @property
    def fixable(self) -> bool:
        return self.config.transcriber == "whispercpp"

    def fix(self, **kwargs) -> CheckResult:
        from ..transcribe.whispercpp import download_model

        download_model(self.config.whisper_model)
        return self.detect()
```

In `cli.py`, replace the inline Groq construction in the `stop` branch with:

```python
        from .transcribe.factory import build_transcriber

        try:
            transcriber = build_transcriber(config)
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            raise SystemExit(str(exc)) from exc
```

and drop the now-unused `get_secret`/`GroqTranscriber` imports (keep `compress_for_upload`).

Add `WhisperModelCheck(config)` to `build_checks()` after the provider check.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_transcribe_factory.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/transcribe/factory.py src/beyondmeetings/doctor/transcriber.py src/beyondmeetings/cli.py src/beyondmeetings/doctor/registry.py tests/test_transcribe_factory.py
git commit -m "feat: transcriber factory and local model check"
```

---

## Task 8: MCP registration

**Files:**
- Create: `src/beyondmeetings/mcp_setup.py`
- Test: `tests/test_mcp_setup.py`

**Safety requirement:** `~/.claude.json` on the dev machine is 79 KB of real configuration. Registration must merge, back up, and write atomically. A test asserts unrelated keys survive.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_setup.py
import json

import pytest

from beyondmeetings.mcp_setup import (
    AGENTS, detect_agents, register_mcp, server_definition,
)


def test_server_definition_scopes_the_filesystem_server_to_the_vault():
    spec = server_definition("/home/x/Vault")
    assert spec["command"] == "npx"
    assert "/home/x/Vault" in spec["args"]


def test_detect_reports_only_installed_agents(monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda n: "/usr/bin/claude" if n == "claude" else None
    )
    assert detect_agents() == ["claude"]


def test_claude_registration_creates_config_when_absent(tmp_path):
    target = tmp_path / ".claude.json"
    register_mcp("claude", "/v", home=tmp_path)
    assert "beyondmeetings-vault" in json.loads(target.read_text())["mcpServers"]


def test_claude_registration_preserves_unrelated_keys(tmp_path):
    target = tmp_path / ".claude.json"
    target.write_text(json.dumps({
        "numStartups": 42,
        "projects": {"/some/path": {"history": ["a", "b"]}},
        "mcpServers": {"existing": {"command": "foo"}},
    }))
    register_mcp("claude", "/v", home=tmp_path)
    data = json.loads(target.read_text())
    assert data["numStartups"] == 42
    assert data["projects"]["/some/path"]["history"] == ["a", "b"]
    assert "existing" in data["mcpServers"]
    assert "beyondmeetings-vault" in data["mcpServers"]


def test_claude_registration_writes_a_backup(tmp_path):
    target = tmp_path / ".claude.json"
    target.write_text('{"numStartups": 7}')
    register_mcp("claude", "/v", home=tmp_path)
    assert json.loads((tmp_path / ".claude.json.bak").read_text())["numStartups"] == 7


def test_registration_is_idempotent(tmp_path):
    register_mcp("claude", "/v", home=tmp_path)
    register_mcp("claude", "/v", home=tmp_path)
    servers = json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]
    assert len(servers) == 1


def test_corrupt_existing_config_is_refused_not_overwritten(tmp_path):
    target = tmp_path / ".claude.json"
    target.write_text("{ this is not json")
    with pytest.raises(ValueError, match="could not be parsed"):
        register_mcp("claude", "/v", home=tmp_path)
    assert target.read_text() == "{ this is not json"


def test_gemini_registration_uses_its_settings_file(tmp_path):
    register_mcp("gemini", "/v", home=tmp_path)
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
    assert "beyondmeetings-vault" in data["mcpServers"]


def test_codex_registration_uses_toml(tmp_path):
    register_mcp("codex", "/v", home=tmp_path)
    text = (tmp_path / ".codex" / "config.toml").read_text()
    assert "mcp_servers.beyondmeetings-vault" in text
    assert "/v" in text


def test_codex_registration_preserves_existing_toml(tmp_path):
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('model = "o3"\n')
    register_mcp("codex", "/v", home=tmp_path)
    assert 'model = "o3"' in config.read_text()


def test_unknown_agent_raises():
    with pytest.raises(ValueError, match="unknown agent"):
        register_mcp("emacs", "/v")


def test_every_declared_agent_has_a_writer():
    for name in AGENTS:
        assert AGENTS[name]["writer"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mcp_setup.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/beyondmeetings/mcp_setup.py
"""Register an Obsidian MCP server into whichever agent CLI is installed.

The server is `@modelcontextprotocol/server-filesystem` scoped to the vault:
no Obsidian plugin, no second API key. The popular mcp-obsidian alternative
needs the Local REST API plugin installed and its key copied out, which is
three more ways for setup to fail.

Every writer merges into the existing config, keeps a `.bak`, and writes
atomically. These files hold the user's entire agent setup — a clobber would
be far worse than a failed registration.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import tomli_w

SERVER_NAME = "beyondmeetings-vault"


def server_definition(vault_path: str) -> dict:
    return {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", vault_path],
    }


def _load_json(path: Path) -> dict:
    if not path.is_file() or not path.read_text().strip():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} could not be parsed as JSON ({exc}). Not touching it.")


def _write_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def _write_json_config(path: Path, vault_path: str) -> Path:
    data = _load_json(path)
    data.setdefault("mcpServers", {})[SERVER_NAME] = server_definition(vault_path)
    _write_atomically(path, json.dumps(data, indent=2) + "\n")
    return path


def _write_toml_config(path: Path, vault_path: str) -> Path:
    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        # Drop a previous block so repeated runs do not stack duplicates.
        marker = f"[mcp_servers.{SERVER_NAME}]"
        if marker in existing:
            existing = existing.split(marker)[0].rstrip() + "\n"

    block = tomli_w.dumps({"mcp_servers": {SERVER_NAME: server_definition(vault_path)}})
    _write_atomically(path, (existing.rstrip() + "\n\n" + block).lstrip())
    return path


AGENTS = {
    "claude": {
        "binary": "claude",
        "label": "Claude Code",
        "path": ".claude.json",
        "writer": _write_json_config,
    },
    "codex": {
        "binary": "codex",
        "label": "Codex CLI",
        "path": ".codex/config.toml",
        "writer": _write_toml_config,
    },
    "gemini": {
        "binary": "gemini",
        "label": "Gemini CLI",
        "path": ".gemini/settings.json",
        "writer": _write_json_config,
    },
}


def detect_agents() -> list[str]:
    return [name for name, spec in AGENTS.items() if shutil.which(spec["binary"])]


def register_mcp(agent: str, vault_path: str, home: Path | None = None) -> Path:
    spec = AGENTS.get(agent)
    if spec is None:
        raise ValueError(f"unknown agent: {agent}")
    target = Path(home or Path.home()) / spec["path"]
    return spec["writer"](target, vault_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mcp_setup.py -v`
Expected: PASS — 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/mcp_setup.py tests/test_mcp_setup.py
git commit -m "feat: Obsidian MCP registration with merge-and-backup"
```

---

## Task 9: MCP check and choice pickers

**Files:**
- Create: `src/beyondmeetings/doctor/mcp.py`, `src/beyondmeetings/doctor/choices.py`
- Modify: `src/beyondmeetings/doctor/base.py` (add `choices` to the row), `doctor/registry.py`
- Test: `tests/test_doctor_choices.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor_choices.py
import json

from beyondmeetings.config import Config
from beyondmeetings.doctor.base import run_all
from beyondmeetings.doctor.choices import ProviderChoice, TranscriberChoice
from beyondmeetings.doctor.mcp import McpCheck


def test_provider_choice_offers_all_four():
    options = {o["value"] for o in ProviderChoice(Config()).choices}
    assert options == {"anthropic", "openai", "gemini", "ollama"}


def test_claude_is_marked_recommended():
    claude = next(
        o for o in ProviderChoice(Config()).choices if o["value"] == "anthropic"
    )
    assert claude["recommended"] is True


def test_ollama_option_warns_about_code_mixed_speech():
    ollama = next(
        o for o in ProviderChoice(Config()).choices if o["value"] == "ollama"
    )
    assert "Hinglish" in ollama["note"]


def test_provider_choice_is_always_ok():
    """A choice is never a blocker — a default is always selected."""
    assert ProviderChoice(Config()).detect().status == "ok"


def test_provider_choice_reports_the_current_selection():
    assert "Claude" in ProviderChoice(Config(provider="anthropic")).detect().detail


def test_provider_fix_persists_the_selection(tmp_path):
    cfg = Config()
    choice = ProviderChoice(cfg, config_path=tmp_path / "c.toml")
    choice.fix(value="gemini")
    from beyondmeetings.config import load_config
    assert load_config(tmp_path / "c.toml").provider == "gemini"


def test_provider_fix_rejects_an_unknown_value(tmp_path):
    choice = ProviderChoice(Config(), config_path=tmp_path / "c.toml")
    assert choice.fix(value="nope").status == "broken"


def test_transcriber_choice_offers_both():
    values = {o["value"] for o in TranscriberChoice(Config()).choices}
    assert values == {"groq", "whispercpp"}


def test_choices_are_exposed_on_the_row():
    row = run_all([ProviderChoice(Config())])[0]
    assert len(row["choices"]) == 4


def test_rows_without_choices_expose_an_empty_list():
    from beyondmeetings.doctor.system import FfmpegCheck
    assert run_all([FfmpegCheck()])[0]["choices"] == []


def test_mcp_check_ok_when_no_agent_cli_installed(monkeypatch, tmp_path):
    monkeypatch.setattr("beyondmeetings.doctor.mcp.detect_agents", lambda: [])
    check = McpCheck(Config(vault_path=str(tmp_path)), home=tmp_path)
    result = check.detect()
    assert result.status == "ok"
    assert "No agent CLI" in result.detail


def test_mcp_check_missing_when_agent_present_but_unregistered(monkeypatch, tmp_path):
    monkeypatch.setattr("beyondmeetings.doctor.mcp.detect_agents", lambda: ["claude"])
    check = McpCheck(Config(vault_path=str(tmp_path)), home=tmp_path)
    assert check.detect().status == "missing"


def test_mcp_fix_registers_into_each_detected_agent(monkeypatch, tmp_path):
    monkeypatch.setattr("beyondmeetings.doctor.mcp.detect_agents", lambda: ["claude"])
    check = McpCheck(Config(vault_path=str(tmp_path)), home=tmp_path)
    assert check.fix().status == "ok"
    data = json.loads((tmp_path / ".claude.json").read_text())
    assert "beyondmeetings-vault" in data["mcpServers"]


def test_mcp_is_not_required(tmp_path):
    assert McpCheck(Config(), home=tmp_path).required is False


def test_mcp_fix_without_a_vault_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr("beyondmeetings.doctor.mcp.detect_agents", lambda: ["claude"])
    assert McpCheck(Config(), home=tmp_path).fix().status == "broken"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_doctor_choices.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

In `doctor/base.py`, add `choices: list[dict] = []` to `Check` and `"choices": check.choices` to the row dict in `run_all()`.

```python
# src/beyondmeetings/doctor/choices.py
"""Selection rows — provider and transcriber. Never blockers."""
from __future__ import annotations

from pathlib import Path

from ..config import Config, save_config
from ..labels import provider_label, transcriber_label
from .base import Check, CheckResult

PROVIDERS = [
    {"value": "anthropic", "label": "Claude", "recommended": True,
     "note": "Best summary quality and follow-up detection."},
    {"value": "openai", "label": "ChatGPT", "recommended": False, "note": ""},
    {"value": "gemini", "label": "Gemini", "recommended": False, "note": ""},
    {"value": "ollama", "label": "Ollama (local)", "recommended": False,
     "note": "Nothing leaves your machine. Weaker on code-mixed speech "
             "such as Hinglish."},
]

TRANSCRIBERS = [
    {"value": "groq", "label": "Groq Whisper", "recommended": True,
     "note": "Fast, free tier, no download."},
    {"value": "whispercpp", "label": "whisper.cpp (local)", "recommended": False,
     "note": "Fully offline. Needs a ~1.5 GB model and a built binary."},
]


class _ChoiceCheck(Check):
    required = False
    field: str
    choices: list[dict]

    def __init__(self, config: Config, config_path: Path | None = None):
        self.config = config
        self.config_path = config_path

    def _label_for(self, value: str) -> str:
        return next(
            (c["label"] for c in self.choices if c["value"] == value), value
        )

    def detect(self) -> CheckResult:
        current = getattr(self.config, self.field)
        return CheckResult(status="ok", detail=f"Using {self._label_for(current)}.")

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, value: str = "", **kwargs) -> CheckResult:
        if value not in {c["value"] for c in self.choices}:
            return CheckResult(status="broken", detail=f"Unknown option: {value!r}")
        setattr(self.config, self.field, value)
        save_config(self.config, self.config_path)
        return self.detect()


class ProviderChoice(_ChoiceCheck):
    id = "provider_choice"
    label = "Note writer"
    description = "Which AI turns your transcript into notes."
    field = "provider"
    choices = PROVIDERS


class TranscriberChoice(_ChoiceCheck):
    id = "transcriber_choice"
    label = "Transcription"
    description = "How your audio becomes text."
    field = "transcriber"
    choices = TRANSCRIBERS
```

```python
# src/beyondmeetings/doctor/mcp.py
"""Obsidian MCP registration into installed agent CLIs."""
from __future__ import annotations

import json
from pathlib import Path

from ..config import Config
from ..mcp_setup import AGENTS, SERVER_NAME, detect_agents
from .base import Check, CheckResult


class McpCheck(Check):
    id = "mcp"
    label = "Vault access for your AI agent"
    description = (
        "Lets Claude Code, Codex or Gemini CLI read and search your meeting notes."
    )
    required = False

    def __init__(self, config: Config, home: Path | None = None):
        self.config = config
        self.home = Path(home or Path.home())

    def _registered(self, agent: str) -> bool:
        path = self.home / AGENTS[agent]["path"]
        if not path.is_file():
            return False
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".json":
            try:
                return SERVER_NAME in json.loads(text).get("mcpServers", {})
            except json.JSONDecodeError:
                return False
        return SERVER_NAME in text

    def detect(self) -> CheckResult:
        agents = detect_agents()
        if not agents:
            return CheckResult(
                status="ok",
                detail="No agent CLI found — nothing to register. This is optional.",
            )

        pending = [a for a in agents if not self._registered(a)]
        labels = ", ".join(AGENTS[a]["label"] for a in agents)
        if not pending:
            return CheckResult(status="ok", detail=f"Registered in {labels}.")
        return CheckResult(
            status="missing",
            detail=f"Found {labels}. Not registered yet.",
        )

    @property
    def fixable(self) -> bool:
        return bool(detect_agents())

    def fix(self, **kwargs) -> CheckResult:
        if not self.config.vault_path:
            return CheckResult(
                status="broken", detail="Choose a vault first, then register."
            )
        from ..mcp_setup import register_mcp

        for agent in detect_agents():
            register_mcp(agent, self.config.vault_path, home=self.home)
        return self.detect()
```

Add `ProviderChoice`, `TranscriberChoice`, `WhisperModelCheck` and `McpCheck` to `build_checks()`. Order: choices first (they change what later rows mean), then system, keys, Obsidian, vault, rules, MCP.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_doctor_choices.py -v`
Expected: PASS — 15 passed

- [ ] **Step 5: Commit**

```bash
git add src/beyondmeetings/doctor tests/test_doctor_choices.py
git commit -m "feat: MCP check plus provider and transcriber pickers"
```

---

## Task 10: Choice rows in the wizard UI

**Files:**
- Modify: `src/beyondmeetings/web/setup.js`, `src/beyondmeetings/web/setup.css`

- [ ] **Step 1: Add choice rendering to `setup.js`**

Insert before `renderPanel`, and call it from `renderRow` when `check.choices.length`:

```javascript
function renderChoices(check) {
  const wrap = document.createElement("div");
  wrap.className = "choices";
  wrap.setAttribute("role", "radiogroup");
  wrap.setAttribute("aria-label", check.label);

  for (const option of check.choices) {
    const btn = document.createElement("button");
    btn.className = "choice";
    btn.type = "button";
    btn.setAttribute("role", "radio");
    const selected = check.detail.includes(option.label);
    btn.setAttribute("aria-checked", String(selected));
    if (selected) btn.classList.add("selected");

    const title = document.createElement("span");
    title.className = "choiceLabel";
    title.textContent = option.label;
    if (option.recommended) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = "recommended";
      title.append(badge);
    }
    btn.append(title);

    if (option.note) {
      const note = document.createElement("span");
      note.className = "choiceNote";
      note.textContent = option.note;
      btn.append(note);
    }

    btn.onclick = () => runFix(check.id, { value: option.value }, btn);
    wrap.append(btn);
  }
  return wrap;
}
```

In `renderRow`, replace the input-panel branch with:

```javascript
  if (check.choices && check.choices.length) meta.append(renderChoices(check));
  else if (!ok && check.inputs.length) meta.append(renderPanel(check));
```

A choice row is always `ok`, so it must render its options regardless of status.

- [ ] **Step 2: Add styles to `setup.css`**

```css
.choices { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.choice {
  font: inherit; text-align: left; cursor: pointer;
  display: flex; flex-direction: column; gap: 3px;
  padding: 9px 12px; border-radius: 8px; min-width: 150px; flex: 1;
  border: 1px solid var(--line); background: transparent; color: var(--fg);
}
.choice:hover { border-color: var(--accent); }
.choice.selected {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
}
.choiceLabel { font-size: 13px; font-weight: 600; }
.badge {
  font-size: 9.5px; text-transform: uppercase; letter-spacing: .06em;
  background: var(--accent); color: #fff; border-radius: 20px;
  padding: 1px 6px; margin-left: 6px; vertical-align: 1px;
}
.choiceNote { font-size: 11.5px; color: var(--muted); line-height: 1.4; }
```

- [ ] **Step 3: Verify by driving the API**

```bash
.venv/bin/python -m pytest tests/test_server.py -v
```
Expected: PASS. Then boot the wizard and confirm the two choice rows render with Claude badged, and that clicking Gemini persists to config and re-renders.

- [ ] **Step 4: Commit**

```bash
git add src/beyondmeetings/web
git commit -m "feat: provider and transcriber choice rows in the wizard"
```

---

## Task 11: Docs, suite and tracker

**Files:**
- Modify: `README.md`, `CONTRIBUTING.md`, `PROGRESS.md`

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — zero failures

- [ ] **Step 2: Verify `doctor` end to end**

```bash
.venv/bin/beyondmeetings doctor
```
Expected: the two new choice rows appear, the MCP row detects Claude Code (present on this machine) and reports it unregistered, and `whisper_model` reports "Not needed — using Groq."

- [ ] **Step 3: Verify MCP registration against a sandbox home**

```bash
.venv/bin/python -c "
import json, pathlib, tempfile
from beyondmeetings.mcp_setup import register_mcp
h = pathlib.Path(tempfile.mkdtemp())
(h/'.claude.json').write_text(json.dumps({'numStartups': 99}))
register_mcp('claude', '/tmp/vault', home=h)
d = json.loads((h/'.claude.json').read_text())
print('preserved:', d['numStartups'] == 99)
print('registered:', 'beyondmeetings-vault' in d['mcpServers'])
print('backup:', (h/'.claude.json.bak').is_file())
"
```
Expected: all three `True`. **Do not run this against the real `~/.claude.json`** except through the wizard, which backs it up.

- [ ] **Step 4: Update the docs**

`README.md`: mark all four providers as working, add the model-override note (`model` in config), document `whisper.cpp` setup and the MCP feature. `CONTRIBUTING.md`: note that adding a provider now also needs a `VALIDATORS` entry and a `PROVIDERS` choice entry.

- [ ] **Step 5: Update `PROGRESS.md` and commit**

Tick milestone 3, set milestone 4 `[~]`, append a session-log line, record any bugs found.

```bash
git add README.md CONTRIBUTING.md PROGRESS.md
git commit -m "docs: milestone 3 complete"
```

---

## Self-Review

**Spec coverage:** §1 provider scope → Tasks 2, 3, 4, 5. §1 whisper.cpp opt-in → Tasks 6, 7. §6 check 8 (MCP) → Tasks 8, 9. §6 provider picker with Claude recommended → Tasks 9, 10.

**Model defaults are a known soft spot.** `gpt-4o`, `gemini-2.0-flash` and `qwen2.5:14b` are the defaults; all are overridable via `model` in config, and a wrong value produces a clear API error rather than silent misbehaviour. These should be reviewed before release — model names churn faster than this code will.

**Deferred to milestone 4:** the tray, the daily app page, autostart, and the segment-rollover timer that finally closes B2.

**Existing test to update, not just add:** `tests/test_doctor_keys.py::test_unsupported_provider_explains_it_arrives_later` asserts OpenAI is unsupported. Task 5 makes that false; the plan replaces it rather than leaving a contradiction.

**Type consistency:** `LLMProvider.analyse(prompt, valid_candidate_ids)` matches across all four adapters and `factory.py`. `Transcriber.transcribe_file(audio)` matches `groq.py` and `whispercpp.py`. `Check.choices` added in Task 9 is consumed by `run_all()` and `setup.js` in Task 10. `register_mcp(agent, vault_path, home)` matches between Tasks 8 and 9.
