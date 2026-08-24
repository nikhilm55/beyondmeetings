"""Local web server: the daily app at `/` and the setup wizard at `/setup`.

The same Check objects back both this API and `beyondmeetings doctor`, so the
browser and the terminal can never disagree about what is wrong.

Binds 127.0.0.1 only. There is no authentication, because there is no remote
surface to authenticate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from .config import DEFAULT_CONFIG_PATH, Config, load_config, save_config
from .doctor.base import Check, completion_percent, run_all, run_fix
from .doctor.registry import build_checks
from .discussion import (
    SUMMARY_LANGUAGES,
    DiscussionCache,
    discussion_pdf_markdown,
    generate_discussion_summary,
)
from .history import list_meetings, search_meetings
from .library import list_tasks, open_library_folder, resolve_markdown
from .llm.factory import build_provider
from .pdf_export import (
    default_pdf_export_dir,
    export_meeting_pdf,
    reveal_pdf_for_sharing,
)
from .pipeline import generate_notes
from .session import SessionManager
from .translation import (
    TranslationCache,
    parse_translation_turns,
    resolve_meeting_transcript,
    translate_transcript,
    translation_pdf_markdown,
)

WEB_DIR = Path(__file__).parent / "web"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1", "testserver"}


class HostGuardMiddleware:
    """Pure ASGI host guard, avoiding BaseHTTPMiddleware stream edge cases."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        raw = headers.get(b"host", b"").decode("latin-1")
        if raw.startswith("["):
            host = raw.partition("]")[0].lower() + "]"
        elif raw.count(":") == 1:
            host = raw.split(":", 1)[0].lower()
        else:
            host = raw.lower()
        if host and host not in ALLOWED_HOSTS:
            response = JSONResponse(
                status_code=421,
                content={"detail": f"Unexpected Host header: {host!r}"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


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


class NoteRequest(BaseModel, extra="forbid"):
    path: str
    view: Literal["minutes", "discussion", "translation"] = "minutes"
    language: str = Field(default="English", min_length=1, max_length=30)


class DiscussionRequest(BaseModel, extra="forbid"):
    path: str
    language: str = Field(default="English", min_length=1, max_length=30)
    regenerate: bool = False


class TranslationRequest(BaseModel, extra="forbid"):
    path: str
    language: str = Field(default="English", min_length=1, max_length=30)
    regenerate: bool = False


class LibraryChatRequest(BaseModel, extra="forbid"):
    query: str = Field(min_length=1, max_length=500)


def create_app(
    config: Config | None = None,
    config_path: Path | None = None,
    checks_factory: Callable[[Config], list[Check]] | None = None,
    session=None,
    pdf_export_dir: Path | None = None,
    pdf_sharer: Callable[[Path], None] | None = None,
) -> FastAPI:
    config_path = Path(config_path or DEFAULT_CONFIG_PATH)
    initial_config = config if config is not None else load_config(config_path)
    state = {
        "config": initial_config,
        "session": session,
        "pdf_export_dir": Path(pdf_export_dir or default_pdf_export_dir()),
        "pdf_sharer": pdf_sharer or reveal_pdf_for_sharing,
        "discussion_cache": DiscussionCache(
            Path(initial_config.data_dir) / "discussion-summaries"
        ),
        "translation_cache": TranslationCache(
            Path(initial_config.data_dir) / "translated-transcripts"
        ),
    }
    factory = checks_factory or (
        lambda cfg: build_checks(cfg, config_path=config_path)
    )

    app = FastAPI(title="beyondMeetings")
    # Binding loopback does not stop DNS rebinding: an attacker's domain can
    # resolve to 127.0.0.1. Reject non-loopback Host headers before routing.
    app.add_middleware(HostGuardMiddleware)

    def current_session():
        """Build the real session lazily — tests inject a fake instead."""
        if state["session"] is None:
            from .audio.factory import build_recorder
            from .transcribe.factory import build_transcriber

            cfg = state["config"]
            state["session"] = SessionManager(
                config=cfg,
                recorder=build_recorder(
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
        result = run_fix(check, payload)
        # Rebuild config from disk — a fix may have initialized the library.
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

    @app.post("/api/recording/reset")
    def recording_reset():
        """Escape hatch for a wedged or corrupt recording state."""
        return current_session().reset()

    # ---------- meetings ----------

    @app.get("/api/meetings")
    def meetings():
        return {"meetings": list_meetings(Path(state["config"].notes_path))}

    @app.get("/api/tasks")
    def tasks():
        return {"tasks": list_tasks(Path(state["config"].notes_path))}

    def read_note(path: str) -> tuple[Path, str]:
        try:
            target = resolve_markdown(Path(state["config"].notes_path), path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Note not found")
        return target, target.read_text(encoding="utf-8")

    def summary_language(language: str) -> str:
        matched = next(
            (item for item in SUMMARY_LANGUAGES if item.casefold() == language.casefold()),
            None,
        )
        if matched is None:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported summary language: {language}",
            )
        return matched

    def get_discussion(path: str, language: str, regenerate: bool = False) -> tuple[str, bool]:
        language = summary_language(language)
        target, content = read_note(path)
        note_id = str(target.relative_to(Path(state["config"].notes_path).resolve()))
        if not regenerate:
            cached = state["discussion_cache"].get(note_id, content, language)
            if cached:
                return cached, True
        try:
            generated = generate_discussion_summary(
                content,
                language,
                build_provider(state["config"]),
            )
            state["discussion_cache"].put(note_id, content, language, generated)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Could not create discussion summary: {exc}",
            ) from exc
        return generated, False

    def get_translation(
        path: str,
        language: str,
        regenerate: bool = False,
    ) -> tuple[str, bool]:
        language = summary_language(language)
        target, note_content = read_note(path)
        try:
            transcript_path = resolve_meeting_transcript(
                note_content,
                Path(state["config"].data_dir),
            )
            transcript = transcript_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        note_id = str(target.relative_to(Path(state["config"].notes_path).resolve()))
        cache_id = f"{note_id}::speaker-chat-v2"
        if not regenerate:
            cached = state["translation_cache"].get(cache_id, transcript, language)
            if cached:
                return cached, True
        try:
            translated = translate_transcript(
                transcript,
                language,
                build_provider(state["config"]),
            )
            state["translation_cache"].put(
                cache_id,
                transcript,
                language,
                translated,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Could not translate the full transcript: {exc}",
            ) from exc
        return translated, False

    @app.get("/api/note")
    def note(path: str):
        _, content = read_note(path)
        configured_language = next(
            (
                item for item in SUMMARY_LANGUAGES
                if item.casefold() == state["config"].notes_language.casefold()
            ),
            "English",
        )
        return {
            "path": path,
            "content": content,
            "notes_language": configured_language,
        }

    @app.post("/api/note/discussion")
    def discussion(request: DiscussionRequest):
        summary, cached = get_discussion(
            request.path,
            request.language,
            request.regenerate,
        )
        return {
            "path": request.path,
            "language": summary_language(request.language),
            "content": summary,
            "cached": cached,
        }

    @app.post("/api/note/translation")
    def translation(request: TranslationRequest):
        translated, cached = get_translation(
            request.path,
            request.language,
            request.regenerate,
        )
        return {
            "path": request.path,
            "language": summary_language(request.language),
            "content": translated,
            "turns": parse_translation_turns(translated),
            "cached": cached,
        }

    def make_pdf(
        path: str,
        view: str = "minutes",
        language: str = "English",
    ) -> Path:
        try:
            options = {}
            if view == "discussion":
                language = summary_language(language)
                target, content = read_note(path)
                summary, _ = get_discussion(path, language)
                options = {
                    "markdown_override": discussion_pdf_markdown(
                        content, target.stem, summary
                    ),
                    "filename_suffix": f"Discussion Summary - {language}",
                    "brief_label": f"{language} Discussion Summary",
                    "show_metrics": False,
                }
            elif view == "translation":
                language = summary_language(language)
                target, content = read_note(path)
                translated, _ = get_translation(path, language)
                options = {
                    "markdown_override": translation_pdf_markdown(
                        content,
                        target.stem,
                        translated,
                        language,
                    ),
                    "filename_suffix": f"Conversation Transcript - {language}",
                    "brief_label": f"{language} Full Conversation",
                    "show_metrics": False,
                }
            elif view != "minutes":
                raise HTTPException(status_code=422, detail=f"Unsupported view: {view}")
            return export_meeting_pdf(
                Path(state["config"].notes_path),
                path,
                state["pdf_export_dir"],
                **options,
            )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(
                status_code=500, detail=f"Could not create PDF: {exc}"
            ) from exc

    @app.post("/api/note/pdf")
    def create_note_pdf(request: NoteRequest):
        target = make_pdf(request.path, request.view, request.language)
        return {"pdf_path": str(target), "filename": target.name}

    @app.get("/api/note/pdf")
    def download_note_pdf(
        path: str,
        view: str = "minutes",
        language: str = "English",
    ):
        target = make_pdf(path, view, language)
        return FileResponse(
            target,
            media_type="application/pdf",
            filename=target.name,
        )

    @app.post("/api/note/share")
    def share_note_pdf(request: NoteRequest):
        target = make_pdf(request.path, request.view, request.language)
        try:
            state["pdf_sharer"](target)
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"Could not open the PDF for sharing: {exc}"
            ) from exc
        return {
            "pdf_path": str(target),
            "filename": target.name,
            "action": "revealed",
        }

    @app.post("/api/library/open")
    def open_library():
        path = Path(state["config"].notes_path)
        try:
            open_library_folder(path)
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"Could not open the notes folder: {exc}"
            ) from exc
        return {"path": str(path)}

    @app.post("/api/library/chat")
    def library_chat(request: LibraryChatRequest):
        return search_meetings(
            Path(state["config"].notes_path),
            request.query,
        )

    @app.post("/api/regenerate")
    def regenerate(request: RegenerateRequest):
        path = Path(request.transcript).expanduser()

        # Reading any caller-supplied path and shipping it to a third-party API
        # is a file-exfiltration primitive. Only our own transcripts qualify.
        transcripts = (Path(state["config"].data_dir) / "transcripts").resolve()
        try:
            inside = path.resolve().is_relative_to(transcripts)
        except (OSError, RuntimeError):
            inside = False
        if not inside:
            raise HTTPException(
                status_code=403,
                detail=f"Only transcripts under {transcripts} can be regenerated.",
            )

        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"No transcript at {path}")
        try:
            written = generate_notes(
                path.read_text(encoding="utf-8"),
                state["config"],
                build_provider(state["config"]),
                transcript_ref=str(path.resolve().relative_to(transcripts)),
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
