import re

from beyondmeetings.cli import build_parser, placeholder_name


def test_start_accepts_a_name():
    args = build_parser().parse_args(["start", "Client Kickoff"])
    assert args.command == "start"
    assert args.name == "Client Kickoff"


def test_start_name_is_optional():
    args = build_parser().parse_args(["start"])
    assert args.name is None


def test_placeholder_name_uses_the_clock():
    assert re.fullmatch(r"recording-\d{2}-\d{2}", placeholder_name())


def test_stop_takes_no_arguments():
    assert build_parser().parse_args(["stop"]).command == "stop"


def test_notes_accepts_a_transcript_path():
    args = build_parser().parse_args(["notes", "/tmp/t.txt"])
    assert args.command == "notes"
    assert args.transcript == "/tmp/t.txt"


def test_stop_without_a_recording_exits_cleanly(tmp_path, monkeypatch, capsys):
    """No traceback — this is the most likely first-run mistake."""
    import pytest

    from beyondmeetings import cli
    from beyondmeetings.config import Config

    monkeypatch.setattr(cli, "load_config", lambda: Config(data_dir=str(tmp_path)))
    with pytest.raises(SystemExit) as exc:
        cli.main(["stop"])
    assert "Nothing to stop" in str(exc.value)


# --- Review finding #1: cli stop and the app were two divergent pipelines ---

def test_cli_stop_delegates_to_the_shared_session(monkeypatch, tmp_path, capsys):
    """There must be exactly one stop implementation."""
    import pytest

    from beyondmeetings import cli
    from beyondmeetings.config import Config

    calls = []

    class FakeSession:
        def run_stop(self):
            calls.append("run_stop")
            return {"phase": "done", "note_path": "/v/Meetings/2026-07-30/N.md",
                    "transcript_path": "/d/t.txt", "error": None}

    monkeypatch.setattr(cli, "load_config", lambda: Config(data_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "_session", lambda c, d: FakeSession())
    assert cli.main(["stop"]) == 0
    assert calls == ["run_stop"]
    assert "Note written" in capsys.readouterr().out


def test_cli_stop_reports_a_failed_stop_with_the_transcript_path(monkeypatch,
                                                                 tmp_path, capsys):
    import pytest

    from beyondmeetings import cli
    from beyondmeetings.config import Config

    class FakeSession:
        def run_stop(self):
            return {"phase": "failed", "note_path": None,
                    "transcript_path": "/d/t.txt", "error": "api down"}

    monkeypatch.setattr(cli, "load_config", lambda: Config(data_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "_session", lambda c, d: FakeSession())
    with pytest.raises(SystemExit, match="api down"):
        cli.main(["stop"])
    assert "/d/t.txt" in capsys.readouterr().out


def test_placeholder_name_is_defined_once():
    """cli re-exports session's, rather than repeating the rule."""
    from beyondmeetings import cli, session
    assert cli.placeholder_name is session.placeholder_name


# --- Interrupted stop left audio unreachable; the CLI was also silent ---

def test_notes_accepts_a_recording_not_just_a_transcript(monkeypatch, tmp_path,
                                                        capsys):
    """Recovery path: a killed stop leaves a .wav and no transcript."""
    from beyondmeetings import cli
    from beyondmeetings.config import Config
    from beyondmeetings.segments import transcript_path

    wav = tmp_path / "seg000.wav"
    wav.write_bytes(b"RIFF")
    transcript_path(wav).write_text("cached from the interrupted run", encoding="utf-8")

    seen = {}
    monkeypatch.setattr(cli, "load_config", lambda: Config(data_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "build_transcriber", lambda c: object())
    monkeypatch.setattr(
        cli, "generate_notes",
        lambda text, cfg, prov, *a: seen.setdefault("text", text) or tmp_path / "n.md",
    )
    monkeypatch.setattr(cli, "_provider", lambda c: object())

    assert cli.main(["notes", str(wav)]) == 0
    assert seen["text"] == "cached from the interrupted run"


def test_notes_rejects_a_missing_file(monkeypatch, tmp_path):
    import pytest

    from beyondmeetings import cli
    from beyondmeetings.config import Config

    monkeypatch.setattr(cli, "load_config", lambda: Config(data_dir=str(tmp_path)))
    with pytest.raises(SystemExit, match="No such file"):
        cli.main(["notes", str(tmp_path / "absent.txt")])


def test_stop_reports_progress_instead_of_sitting_silent(monkeypatch, tmp_path,
                                                         capsys):
    """32 minutes of silent work made a user assume a hang and Ctrl+C out."""
    from beyondmeetings import cli
    from beyondmeetings.config import Config

    class FakeSession:
        on_phase_change = None

        def status(self):
            return {"detail": "Transcribing segment 1 of 1"}

        def run_stop(self):
            if self.on_phase_change:
                self.on_phase_change("transcribing")
            return {"phase": "done", "note_path": "/v/n.md",
                    "transcript_path": "/d/t.txt", "error": None}

    monkeypatch.setattr(cli, "load_config", lambda: Config(data_dir=str(tmp_path)))
    monkeypatch.setattr(cli, "_session", lambda c, d: FakeSession())
    cli.main(["stop"])
    assert "Transcribing segment 1 of 1" in capsys.readouterr().out


# --- `setup`/`serve` handed the URL over before the server was listening ---

def _server_probe(monkeypatch, tmp_path, *, binds=True):
    """Stands in for uvicorn, and records when the browser was opened.

    Readiness is uvicorn's own `started` flag rather than the port answering:
    a port that answers says nothing about *whose* server answered, and a
    stranger already on it would otherwise get our browser sent to it.
    """
    import threading
    import time

    import uvicorn

    from beyondmeetings import cli, desktop, server
    from beyondmeetings.config import Config

    servers, opened, opened_too_early = [], [], []
    keep_serving = threading.Event()

    class FakeServer:
        def __init__(self, config):
            self.started = False
            servers.append(self)

        def run(self):
            if not binds:
                # What uvicorn does on a port it cannot have is sys.exit(3).
                # In `setup` that unwinds the caller; in `serve` the server
                # runs on its own thread, where it only ends that thread.
                if threading.current_thread() is threading.main_thread():
                    raise SystemExit(3)
                return
            time.sleep(0.05)  # binding is never instant
            self.started = True
            keep_serving.wait(10)

    def fake_open(url):
        if not any(s.started for s in servers):
            opened_too_early.append(url)
        opened.append(url)
        keep_serving.set()  # the browser is up; the server may stop pretending
        return True

    monkeypatch.setattr(cli, "load_config", lambda: Config(data_dir=str(tmp_path)))
    monkeypatch.setattr(server, "create_app", lambda **kw: object())
    # `setup` opens from a watcher thread (late-bound) and `serve` opens
    # directly, so both names have to point at the probe.
    monkeypatch.setattr(desktop, "open_browser", fake_open)
    monkeypatch.setattr(cli, "open_browser", fake_open)
    monkeypatch.setattr(uvicorn, "Config", lambda app, **kw: object())
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    return keep_serving, opened, opened_too_early


def test_setup_opens_the_browser_only_once_the_server_is_listening(
    monkeypatch, tmp_path
):
    """An already-running browser navigates in milliseconds and beat uvicorn's bind."""
    from beyondmeetings import cli

    _, opened, too_early = _server_probe(monkeypatch, tmp_path)

    assert cli.main(["setup", "--port", "7788"]) == 0
    assert opened == ["http://127.0.0.1:7788/setup"]
    assert too_early == [], "browser was sent to a server that was not listening"


def test_setup_honours_no_browser(monkeypatch, tmp_path):
    from beyondmeetings import cli

    keep_serving, opened, _ = _server_probe(monkeypatch, tmp_path)
    keep_serving.set()  # nothing will open a browser, so nothing releases it
    assert cli.main(["setup", "--port", "7788", "--no-browser"]) == 0
    assert opened == []


def test_setup_reports_a_port_it_could_not_bind(monkeypatch, tmp_path, capsys):
    """uvicorn's bare sys.exit(3) tells the user nothing about what to do."""
    from beyondmeetings import cli

    _, opened, _ = _server_probe(monkeypatch, tmp_path, binds=False)

    assert cli.main(["setup", "--port", "7788"]) == 1
    assert "7788" in capsys.readouterr().err
    assert opened == []


def test_serve_opens_the_browser_only_once_the_server_is_listening(
    monkeypatch, tmp_path
):
    from beyondmeetings import cli

    _, opened, too_early = _server_probe(monkeypatch, tmp_path)

    assert cli.main(["serve", "--port", "7788", "--no-tray"]) == 0
    assert opened == ["http://127.0.0.1:7788/"]
    assert too_early == [], "browser was sent to a server that was not listening"


def test_serve_honours_no_browser(monkeypatch, tmp_path):
    from beyondmeetings import cli

    keep_serving, opened, _ = _server_probe(monkeypatch, tmp_path)
    keep_serving.set()
    assert cli.main(["serve", "--port", "7788", "--no-tray", "--no-browser"]) == 0
    assert opened == []


def test_serve_fails_loudly_when_the_server_never_started(monkeypatch, tmp_path, capsys):
    """It used to print the URL, open nothing, and exit 0 — a silent failure."""
    from beyondmeetings import cli

    _, opened, _ = _server_probe(monkeypatch, tmp_path, binds=False)

    assert cli.main(["serve", "--port", "7788", "--no-tray"]) == 1
    assert "7788" in capsys.readouterr().err
    assert opened == []


def test_serve_does_not_open_a_stranger_already_on_the_port(monkeypatch, tmp_path):
    """Waiting on the port would have opened someone else's page instead of ours."""
    import socket

    from beyondmeetings import cli

    with socket.socket() as stranger:
        stranger.bind(("127.0.0.1", 0))
        stranger.listen()
        port = stranger.getsockname()[1]

        _, opened, _ = _server_probe(monkeypatch, tmp_path, binds=False)
        assert cli.main(["serve", "--port", str(port), "--no-tray"]) == 1
        assert opened == [], "opened a page belonging to another process"


def test_serve_does_not_start_the_tray_when_the_server_never_started(
    monkeypatch, tmp_path
):
    from beyondmeetings import cli, tray

    _server_probe(monkeypatch, tmp_path, binds=False)
    ran = []
    monkeypatch.setattr(tray, "tray_available", lambda: True)
    monkeypatch.setattr(tray, "run_tray", lambda url, session=None: ran.append(url))

    assert cli.main(["serve", "--port", "7788"]) == 1
    assert ran == [], "a tray icon for a server that is not there"
