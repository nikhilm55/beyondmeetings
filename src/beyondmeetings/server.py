"""Local web server: the daily app at `/` and the setup wizard at `/setup`.

The same Check objects back both this API and `beyondmeetings doctor`, so the
browser and the terminal can never disagree about what is wrong.

Binds 127.0.0.1 only. There is no authentication, because there is no remote
surface to authenticate.
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
from .history import list_meetings
from .llm.factory import build_provider
from .pipeline import generate_notes
from .session import SessionManager

WEB_DIR = Path(__file__).parent / "web"


class SettingsPatch(BaseModel, extra="forbid"):
    provider: str | None = None
    spoken_language: str | None = None
    notes_language: str | None = None
    projects: list[str] | None = None
    transcriber: str | None = None


class StartRequest(BaseModel, extra="forbid"):
    name: str = ""


class RegenerateRequest(BaseModel, extra="forbid"):
    transcript: str


def create_app(
    config: Config | None = None,
    config_path: Path | None = None,
    checks_factory: Callable[[Config], list[Check]] | None = None,
    session=None,
) -> FastAPI:
    config_path = Path(config_path or DEFAULT_CONFIG_PATH)
    state = {
        "config": config if config is not None else load_config(config_path),
        "session": session,
    }
    factory = checks_factory or (
        lambda cfg: build_checks(cfg, config_path=config_path)
    )

    app = FastAPI(title="beyondMeetings")

    def current_session():
        """Build the real session lazily — tests inject a fake instead."""
        if state["session"] is None:
            from .audio.pipewire import PipeWireRecorder
            from .transcribe.factory import build_transcriber

            cfg = state["config"]
            state["session"] = SessionManager(
                config=cfg,
                recorder=PipeWireRecorder(
                    Path(cfg.data_dir), segment_minutes=cfg.segment_minutes
                ),
                transcriber_factory=build_transcriber,
                provider_factory=build_provider,
            )
        return state["session"]

    # The tray shares the server's session rather than making its own.
    app.state.session_getter = current_session

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

    # ---------- recording ----------

    @app.get("/api/recording")
    def recording_status():
        return current_session().status()

    @app.post("/api/recording/start")
    def recording_start(request: StartRequest):
        try:
            return current_session().start(request.name)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/recording/stop")
    def recording_stop():
        try:
            return current_session().stop()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    # ---------- meetings ----------

    @app.get("/api/meetings")
    def meetings():
        vault = state["config"].vault_path
        return {"meetings": list_meetings(Path(vault)) if vault else []}

    @app.post("/api/regenerate")
    def regenerate(request: RegenerateRequest):
        path = Path(request.transcript).expanduser()
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"No transcript at {path}")
        try:
            written = generate_notes(
                path.read_text(encoding="utf-8"),
                state["config"],
                build_provider(state["config"]),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"note_path": str(written)}

    # ---------- pages ----------

    @app.get("/", response_class=HTMLResponse)
    def app_page():
        return (WEB_DIR / "app.html").read_text(encoding="utf-8")

    @app.get("/setup", response_class=HTMLResponse)
    def setup_page():
        return (WEB_DIR / "setup.html").read_text(encoding="utf-8")

    @app.get("/{asset}.css")
    def css(asset: str):
        path = WEB_DIR / f"{asset}.css"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return Response(path.read_text(encoding="utf-8"), media_type="text/css")

    @app.get("/{asset}.js")
    def js(asset: str):
        path = WEB_DIR / f"{asset}.js"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return Response(
            path.read_text(encoding="utf-8"), media_type="application/javascript"
        )

    return app
