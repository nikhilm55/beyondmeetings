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
            return CheckResult(status="broken", detail=f"{vault} does not exist.")
        if not (vault / "Home.md").is_file():
            return CheckResult(status="missing", detail="Vault not scaffolded yet.")
        return CheckResult(status="ok", detail=str(vault))

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, vault_path: str = "", **kwargs) -> CheckResult:
        if not vault_path and not self.config.vault_path:
            return CheckResult(status="missing", detail="No vault path provided.")

        target = Path(vault_path or self.config.vault_path).expanduser()
        if not target.is_dir():
            return CheckResult(
                status="broken",
                detail=f"{target} does not exist. Create it first, then retry.",
            )

        scaffold_vault(target)
        self.config.vault_path = str(target)
        save_config(self.config, self.config_path)
        return self.detect()
