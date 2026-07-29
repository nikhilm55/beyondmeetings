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

    def __init__(self, config: Config, target_dir: Path):
        self.config = config
        self.target_dir = Path(target_dir)

    def detect(self) -> CheckResult:
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
        write_rules(self.target_dir, self.config.vault_path or "(vault not set)")
        return self.detect()
