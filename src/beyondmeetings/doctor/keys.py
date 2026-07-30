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


def validate_openai_key(api_key: str) -> tuple[bool, str]:
    try:
        response = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return False, f"Could not reach OpenAI: {exc}"
    if response.status_code == 200:
        return True, ""
    return False, _error_detail(response)


def validate_gemini_key(api_key: str) -> tuple[bool, str]:
    try:
        response = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return False, f"Could not reach Gemini: {exc}"
    if response.status_code == 200:
        return True, ""
    return False, _error_detail(response)


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
        available = ", ".join(n for n in names if n) or "none"
        return False, (
            f"Model '{model}' is not pulled. Run `ollama pull {model}`. "
            f"Available: {available}."
        )
    return True, ""


# Ollama is keyless and handled separately in ProviderKeyCheck.
VALIDATORS = {
    "anthropic": validate_anthropic_key,
    "openai": validate_openai_key,
    "gemini": validate_gemini_key,
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
        # Nothing to fix from here for Ollama — the user must start the daemon
        # or pull the model themselves.
        return self.provider != "ollama"

    def _validate(self, api_key: str) -> tuple[bool, str]:
        return VALIDATORS[self.provider](api_key)
