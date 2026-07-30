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
