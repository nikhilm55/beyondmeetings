"""Local web server for the setup wizard.

The same Check objects back both this API and `beyondmeetings doctor`, so the
browser and the terminal can never disagree about what is wrong.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from .config import DEFAULT_CONFIG_PATH, Config, load_config, save_config
from .doctor.base import Check, completion_percent, run_all
from .doctor.registry import build_checks

WEB_DIR = Path(__file__).parent / "web"


class SettingsPatch(BaseModel, extra="forbid"):
    provider: str | None = None
    spoken_language: str | None = None
    notes_language: str | None = None
    projects: list[str] | None = None
    transcriber: str | None = None


def create_app(
    config: Config | None = None,
    config_path: Path | None = None,
    checks_factory: Callable[[Config], list[Check]] | None = None,
) -> FastAPI:
    config_path = Path(config_path or DEFAULT_CONFIG_PATH)
    state = {"config": config if config is not None else load_config(config_path)}
    factory = checks_factory or (
        lambda cfg: build_checks(cfg, config_path=config_path)
    )

    app = FastAPI(title="beyondMeetings setup")

    def snapshot() -> dict:
        rows = run_all(factory(state["config"]))
        return {
            "percent": completion_percent(rows),
            "checks": rows,
            "config": state["config"].model_dump(),
        }

    @app.get("/api/status")
    def status():
        return snapshot()

    @app.post("/api/fix/{check_id}")
    def fix(check_id: str, payload: dict | None = None):
        check = next((c for c in factory(state["config"]) if c.id == check_id), None)
        if check is None:
            raise HTTPException(status_code=404, detail=f"no such check: {check_id}")
        result = check.fix(**(payload or {}))
        # Rebuild config from disk — a fix may have written to it (e.g. vault).
        state["config"] = load_config(config_path)
        return {"result": result.model_dump(), **snapshot()}

    @app.post("/api/settings")
    def settings(patch: SettingsPatch):
        updated = state["config"].model_copy(
            update={k: v for k, v in patch.model_dump().items() if v is not None}
        )
        save_config(updated, config_path)
        state["config"] = updated
        return {"config": updated.model_dump()}

    @app.get("/", response_class=HTMLResponse)
    @app.get("/setup", response_class=HTMLResponse)
    def page():
        return (WEB_DIR / "setup.html").read_text(encoding="utf-8")

    @app.get("/setup.css")
    def css():
        return Response(
            (WEB_DIR / "setup.css").read_text(encoding="utf-8"), media_type="text/css"
        )

    @app.get("/setup.js")
    def js():
        return Response(
            (WEB_DIR / "setup.js").read_text(encoding="utf-8"),
            media_type="application/javascript",
        )

    return app
