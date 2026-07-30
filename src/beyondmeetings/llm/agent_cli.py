"""Note writers that shell out to an already-installed agent CLI.

The point of this module: **no API key**. Anyone on a Claude Pro/Max, ChatGPT
or Gemini subscription already has working inference on their machine, but no
API credits — and an API-key-only design locks them out entirely. That is most
people who would want this tool.

The prompt goes in over stdin rather than as an argument: an hour-long
transcript is tens of thousands of characters and argv has limits.
"""
from __future__ import annotations

import shutil
import subprocess

from ..models import MeetingNote
from .base import LLMProvider, parse_meeting_note

# Verified working: `echo "<prompt>" | claude -p` returns the completion on
# stdout using the local subscription. Gemini and Codex follow the same shape
# but are unverified here (neither CLI is installed on the dev machine), so
# `agent_command` in config can override any of these without a code change.
AGENT_COMMANDS = {
    "claude-cli": ["claude", "-p"],
    "gemini-cli": ["gemini", "-p"],
    "codex-cli": ["codex", "exec", "-"],
}

TIMEOUT = 900.0  # an agent CLI on a long transcript is not fast


class AgentCliError(RuntimeError):
    """The agent CLI is missing, unauthenticated, or failed."""


def agent_binary(provider: str) -> str:
    return AGENT_COMMANDS[provider][0]


def agent_available(provider: str) -> bool:
    return bool(shutil.which(agent_binary(provider)))


class AgentCliProvider(LLMProvider):
    def __init__(self, provider: str, command: list[str] | None = None):
        if provider not in AGENT_COMMANDS:
            raise ValueError(f"unknown agent CLI: {provider}")
        self.provider = provider
        self.command = list(command) if command else list(AGENT_COMMANDS[provider])
        self.model = ""  # the CLI picks; not ours to set

    def analyse(
        self, prompt: str, valid_candidate_ids: list[str] | None = None
    ) -> MeetingNote:
        binary = self.command[0]
        if not shutil.which(binary):
            raise AgentCliError(
                f"{binary} is not on your PATH. Install it, or choose a provider "
                "that uses an API key."
            )

        try:
            result = subprocess.run(
                self.command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentCliError(
                f"{binary} did not finish within {int(TIMEOUT)}s."
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:300]
            raise AgentCliError(
                f"{binary} exited {result.returncode}: {detail or 'no output'}. "
                f"Check you are logged in — try running `{binary}` once by hand."
            )

        if not (result.stdout or "").strip():
            raise AgentCliError(
                f"{binary} produced no output. Check you are logged in."
            )

        return parse_meeting_note(result.stdout, valid_candidate_ids)
