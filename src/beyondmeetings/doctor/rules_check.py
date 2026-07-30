"""Whether the generated agent rules files are present."""
from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..rules import FILENAMES, write_rules
from .base import Check, CheckResult


class RulesCheck(Check):
    id = "rules"
    label = "Agent rules files"
    description = "CLAUDE.md, AGENTS.md and GEMINI.md so agents can drive the CLI."
    required = False

    def __init__(self, config: Config, target_dir: Path | None = None):
        self.config = config
        self._target_dir = Path(target_dir) if target_dir else None

    @property
    def target_dir(self) -> Path | None:
        """Only ever the vault. Writing these anywhere else is pointless —
        an agent looks in the directory it is run from."""
        if self._target_dir is not None:
            return self._target_dir
        return Path(self.config.vault_path) if self.config.vault_path else None

    def detect(self) -> CheckResult:
        if self.target_dir is None:
            return CheckResult(
                status="missing", detail="Choose a vault first — these belong in it."
            )
        missing = [n for n in FILENAMES if not (self.target_dir / n).is_file()]
        if missing:
            return CheckResult(
                status="missing", detail=f"Not written: {', '.join(missing)}"
            )
        return CheckResult(status="ok", detail=str(self.target_dir))

    @property
    def fixable(self) -> bool:
        return True

    def fix(self, **kwargs) -> CheckResult:
        if self.target_dir is None:
            return CheckResult(
                status="broken", detail="Choose a vault first, then write these."
            )
        write_rules(self.target_dir, self.config.vault_path)
        return self.detect()
