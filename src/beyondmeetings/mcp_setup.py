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
import os
import shutil
import stat
import subprocess
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
    """Replace a config file without downgrading it, clobbering a symlink, or
    risking a zero-length file on power loss.

    All three were real: temp.write_text() created the replacement with the
    process umask, so a 0600 config came out 0644; os.replace overwrote a
    symlink into a dotfiles repo instead of following it; and rename without
    fsync can land in the journal before the data blocks.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Follow a symlink so a managed dotfile keeps working.
    target = path.resolve() if path.is_symlink() else path

    mode = 0o600
    if target.is_file():
        mode = stat.S_IMODE(target.stat().st_mode)
        backup = target.with_suffix(target.suffix + ".bak")
        # Never overwrite a pristine backup with an already-modified one.
        if not backup.exists():
            shutil.copy2(target, backup)

    temp = target.with_suffix(target.suffix + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(temp, mode)
    os.replace(temp, target)

    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


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


def _register_via_claude_cli(vault_path: str) -> bool:
    """Let Claude Code write its own config when it can.

    ~/.claude.json is live: Claude Code rewrites it from an in-memory copy, so
    our read-merge-rename can lose whatever it wrote in between (and vice
    versa). No amount of atomicity fixes a lost update between two processes
    with no shared locking, so delegate when the CLI exists.
    """
    binary = shutil.which("claude")
    if not binary:
        return False
    result = subprocess.run(
        [binary, "mcp", "add", SERVER_NAME, "--",
         "npx", "-y", "@modelcontextprotocol/server-filesystem", vault_path],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def register_mcp(
    agent: str, vault_path: str, home: Path | None = None, use_cli: bool = True
) -> Path:
    spec = AGENTS.get(agent)
    if spec is None:
        raise ValueError(f"unknown agent: {agent}")
    target = Path(home or Path.home()) / spec["path"]

    if agent == "claude" and use_cli and _register_via_claude_cli(vault_path):
        return target

    return spec["writer"](target, vault_path)
