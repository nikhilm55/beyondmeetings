"""Note writers that shell out to an already-installed agent CLI.

The point of this module: **no API key**. Anyone on a Claude Pro/Max, ChatGPT
or Gemini subscription already has working inference on their machine, but no
API credits — and an API-key-only design locks them out entirely. That is most
people who would want this tool.

The prompt goes in over stdin rather than as an argument: an hour-long
transcript is tens of thousands of characters and argv has limits.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..models import MeetingNote
from .base import LLMProvider, parse_meeting_note

# Verified working: `echo "<prompt>" | claude -p` returns the completion on
# stdout using the local subscription. Gemini and Codex follow the same shape
# but are unverified here (neither CLI is installed on the dev machine), so
# `agent_command` in config can override any of these without a code change.
AGENT_COMMANDS = {
    "claude-cli": ["claude", "-p"],
    "gemini-cli": ["gemini", "-p"],
    # Desktop launchers do not reliably start inside a Git repository. Codex
    # rejects non-interactive runs there unless this documented opt-in is set.
    "codex-cli": ["codex", "exec", "--skip-git-repo-check", "-"],
}

TIMEOUT = 900.0  # an agent CLI on a long transcript is not fast


class AgentCliError(RuntimeError):
    """The agent CLI is missing, unauthenticated, or failed."""


def agent_binary(provider: str) -> str:
    return AGENT_COMMANDS[provider][0]


def _fallback_agent_binaries(binary: str) -> list[Path]:
    """Return user-installed CLIs that a desktop session may not have on PATH.

    Linux application launchers commonly get only the system PATH. Agent CLIs,
    however, are often installed in a user bin directory, an npm version
    manager, or bundled with an editor extension. Shells add those locations to
    PATH, which is why the same command can work in a terminal while appearing
    missing in the desktop app.
    """
    home = Path.home()
    names = [binary]
    if os.name == "nt" and not Path(binary).suffix:
        names = [f"{binary}.exe", f"{binary}.cmd", binary]

    directories = [
        home / ".local" / "bin",
        home / "bin",
        home / ".npm-global" / "bin",
        home / ".volta" / "bin",
        home / ".bun" / "bin",
        home / ".local" / "share" / "pnpm",
        home / ".local" / "share" / "mise" / "shims",
        home / ".asdf" / "shims",
        home / ".codex" / "bin",
    ]
    candidates = [directory / name for directory in directories for name in names]

    # npm installations managed by nvm are versioned and are deliberately not
    # exposed to freedesktop launchers.
    for name in names:
        candidates.extend((home / ".nvm" / "versions" / "node").glob(f"*/bin/{name}"))

    # The official OpenAI editor extension includes a native Codex CLI. Reuse
    # it when the standalone installer has not put `codex` on the desktop PATH.
    if binary == "codex":
        extension_roots = [
            home / ".vscode" / "extensions",
            home / ".vscode-insiders" / "extensions",
            home / ".cursor" / "extensions",
            home / ".windsurf" / "extensions",
        ]
        extension_candidates: list[Path] = []
        for root in extension_roots:
            for name in names:
                extension_candidates.extend(
                    root.glob(f"openai.chatgpt-*/bin/*/{name}")
                )
        # Multiple extension versions can coexist briefly after an update.
        extension_candidates.sort(
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )
        candidates.extend(extension_candidates)

    return candidates


def resolve_agent_binary(binary: str) -> str | None:
    """Locate an agent CLI from both shell and desktop-session locations."""
    found = shutil.which(binary)
    if found:
        return found

    for candidate in _fallback_agent_binaries(binary):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def agent_available(provider: str) -> bool:
    return bool(resolve_agent_binary(agent_binary(provider)))


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
        on_path = shutil.which(binary)
        resolved = on_path or resolve_agent_binary(binary)
        if not resolved:
            raise AgentCliError(
                f"{binary} is not installed or discoverable by the desktop app. "
                "Install it, or choose a provider that uses an API key."
            )

        command = self.command
        if not on_path:
            command = [resolved, *self.command[1:]]

        try:
            result = subprocess.run(
                command,
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
