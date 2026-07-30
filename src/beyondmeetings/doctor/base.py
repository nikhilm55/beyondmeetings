"""Prerequisite checks.

One object per prerequisite, driving both the wizard and `doctor`. A check
that raises during detection is reported as broken rather than crashing the
page — a wizard that dies on a weird machine is worse than one that says so.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel

Status = Literal["ok", "missing", "broken"]


class CheckResult(BaseModel):
    status: Status
    detail: str = ""


class InputField(BaseModel):
    name: str
    label: str
    placeholder: str = ""
    secret: bool = False


class Check(ABC):
    id: str
    label: str
    description: str = ""
    required: bool = True
    inputs: list[InputField] = []
    choices: list[dict] = []

    @abstractmethod
    def detect(self) -> CheckResult:
        ...

    @property
    def fixable(self) -> bool:
        return False

    def fix(self, **kwargs) -> CheckResult:
        raise NotImplementedError(f"{self.id} cannot be fixed automatically")


def run_all(checks: list[Check]) -> list[dict]:
    rows = []
    for check in checks:
        try:
            result = check.detect()
        except Exception as exc:  # a broken probe must not break the page
            result = CheckResult(status="broken", detail=str(exc))
        rows.append(
            {
                "id": check.id,
                "label": check.label,
                "description": check.description,
                "status": result.status,
                "detail": result.detail,
                "required": check.required,
                "fixable": check.fixable,
                "inputs": [i.model_dump() for i in check.inputs],
                "choices": list(check.choices),
            }
        )
    return rows


def run_fix(check: Check, payload: dict | None = None) -> CheckResult:
    """Apply a fix, containing failures the way run_all contains detect().

    An unguarded fix() gave the wizard a 500 and a traceback instead of a red
    row — e.g. a read-only home while registering MCP for a second agent.
    """
    try:
        return check.fix(**(payload or {}))
    except NotImplementedError:
        return CheckResult(
            status="broken", detail=f"{check.id} cannot be fixed automatically."
        )
    except Exception as exc:
        return CheckResult(status="broken", detail=f"Could not fix this: {exc}")


def completion_percent(rows: list[dict]) -> int:
    required = [r for r in rows if r["required"]]
    if not required:
        return 100
    passing = sum(1 for r in required if r["status"] == "ok")
    return round(100 * passing / len(required))
