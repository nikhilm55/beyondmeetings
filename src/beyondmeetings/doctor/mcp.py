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
            status="missing", detail=f"Found {labels}. Not registered yet."
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
