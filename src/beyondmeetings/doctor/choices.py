"""Selection rows — provider and transcriber. Never blockers."""
from __future__ import annotations

from pathlib import Path

from ..config import Config, save_config
from .base import Check, CheckResult

# Subscription-based options come first deliberately. An API key needs credits,
# which most people on a Pro/Max/Plus plan do not have — offering only keyed
# providers locked out the majority of likely users.
PROVIDERS = [
    {"value": "claude-cli", "label": "Claude Code", "recommended": True,
     "note": "Uses your Claude subscription. No API key, no credits. "
             "Best summary quality."},
    {"value": "codex-cli", "label": "Codex CLI", "recommended": False,
     "note": "Uses your ChatGPT subscription. No API key."},
    {"value": "gemini-cli", "label": "Gemini CLI", "recommended": False,
     "note": "Uses your Google account. No API key."},
    {"value": "ollama", "label": "Ollama (local)", "recommended": False,
     "note": "Nothing leaves your machine. Weaker on code-mixed speech "
             "such as Hinglish."},
    {"value": "anthropic", "label": "Claude API", "recommended": False,
     "note": "Needs an API key with credits — separate from a Claude subscription."},
    {"value": "openai", "label": "ChatGPT API", "recommended": False,
     "note": "Needs an API key with credits."},
    {"value": "gemini", "label": "Gemini API", "recommended": False,
     "note": "Needs an API key with quota."},
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
        return next((c["label"] for c in self.choices if c["value"] == value), value)

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
