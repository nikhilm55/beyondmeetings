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
        raise ValueError(
            f"{path} could not be parsed as JSON ({exc}). Not touching it."
        ) from exc


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
