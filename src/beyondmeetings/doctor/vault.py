"""App-owned local notes library setup and legacy-vault migration."""
from __future__ import annotations

from pathlib import Path

from ..config import Config, save_config
from ..vault.scaffold import scaffold_vault
from .base import Check, CheckResult


class StorageCheck(Check):
    id = "storage"
    label = "Local notes library"
    description = "Stores meetings, tasks and the dashboard on this computer."
    required = True
    inputs = []

    def __init__(self, config: Config, config_path: Path | None = None):
        self.config = config
        self.config_path = config_path

    def detect(self) -> CheckResult:
        vault = Path(self.config.notes_path)
        if not vault.is_dir():
            return CheckResult(status="missing", detail=f"Create local library at {vault}.")
        if not (vault / "Home.md").is_file():
            return CheckResult(status="missing", detail="Local library needs initialization.")
        return CheckResult(status="ok", detail=str(vault))

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, library_path: str = "", vault_path: str = "", **kwargs) -> CheckResult:
        target = Path(library_path or vault_path or self.config.notes_path).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        scaffold_vault(target)
        self.config.library_path = str(target)
        # Once migrated, Obsidian has no role in choosing or owning the data.
        self.config.vault_path = ""
        save_config(self.config, self.config_path)
        return self.detect()


# Import compatibility for integrations built against the old module name.
VaultCheck = StorageCheck
