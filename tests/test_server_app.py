import pytest
from fastapi.testclient import TestClient

from beyondmeetings.config import Config
from beyondmeetings.server import create_app
from beyondmeetings.vault.scaffold import scaffold_vault

IDLE = {
    "phase": "idle", "detail": "", "recording": False, "name": "",
    "elapsed_seconds": 0, "segments_done": 0, "segments_total": 0,
    "note_path": None, "transcript_path": None, "error": None,
}


class FakeSession:
    def __init__(self):
        self.started = None
        self.stopped = False
        self.state = dict(IDLE)

    def start(self, name=""):
        self.started = name
        self.state = {**self.state, "phase": "recording", "recording": True,
                      "name": name or "recording-10-00"}
        return self.state

    def stop(self):
        self.stopped = True
        self.state = {**self.state, "phase": "stopping", "recording": False}
        return self.state

    def status(self):
        return self.state


@pytest.fixture
def app_and_session(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    scaffold_vault(vault)
    session = FakeSession()
    app = create_app(
        config=Config(vault_path=str(vault)),
        config_path=tmp_path / "config.toml",
        checks_factory=lambda c: [],
        session=session,
    )
    return TestClient(app), session, vault


def test_root_serves_the_app_page(app_and_session):
    client, _, _ = app_and_session
    response = client.get("/")
    assert response.status_code == 200
    assert "app.css" in response.text


def test_setup_still_serves_the_wizard(app_and_session):
    client, _, _ = app_and_session
    assert "setup.css" in client.get("/setup").text


def test_app_assets_are_served(app_and_session):
    client, _, _ = app_and_session
    assert client.get("/app.css").status_code == 200
    assert client.get("/app.js").status_code == 200


def test_wizard_assets_are_still_served(app_and_session):
    client, _, _ = app_and_session
    assert client.get("/setup.css").status_code == 200
    assert client.get("/setup.js").status_code == 200


def test_unknown_asset_returns_404(app_and_session):
    client, _, _ = app_and_session
    assert client.get("/nope.css").status_code == 404


def test_recording_status_is_exposed(app_and_session):
    client, _, _ = app_and_session
    assert client.get("/api/recording").json()["phase"] == "idle"


def test_start_passes_the_name_through(app_and_session):
    client, session, _ = app_and_session
    body = client.post("/api/recording/start", json={"name": "Kickoff"}).json()
    assert session.started == "Kickoff"
    assert body["recording"] is True


def test_start_without_a_name_is_allowed(app_and_session):
    client, session, _ = app_and_session
    assert client.post("/api/recording/start", json={}).status_code == 200
    assert session.started == ""


def test_stop_dispatches_to_the_session(app_and_session):
    client, session, _ = app_and_session
    client.post("/api/recording/start", json={"name": "x"})
    client.post("/api/recording/stop", json={})
    assert session.stopped is True


def test_start_while_recording_returns_409(app_and_session, monkeypatch):
    client, session, _ = app_and_session

    def boom(name=""):
        raise RuntimeError("already recording")

    monkeypatch.setattr(session, "start", boom)
    response = client.post("/api/recording/start", json={})
    assert response.status_code == 409
    assert "already recording" in response.json()["detail"]


def test_stop_without_recording_returns_409(app_and_session, monkeypatch):
    client, session, _ = app_and_session

    def boom():
        raise RuntimeError("no active recording")

    monkeypatch.setattr(session, "stop", boom)
    assert client.post("/api/recording/stop", json={}).status_code == 409


def test_start_rejects_an_unknown_field(app_and_session):
    client, _, _ = app_and_session
    assert client.post("/api/recording/start", json={"nope": 1}).status_code == 422


def test_history_lists_vault_meetings(app_and_session):
    client, _, vault = app_and_session
    folder = vault / "Meetings" / "2026-07-30"
    folder.mkdir(parents=True)
    (folder / "Standup.md").write_text(
        "---\ntags:\n  - meeting\ndate: 2026-07-30\n---\n\n"
        "# Standup\n\n## Executive Summary\nWe synced.\n"
    )
    rows = client.get("/api/meetings").json()["meetings"]
    assert rows[0]["title"] == "Standup"


def test_history_is_empty_without_a_vault(tmp_path):
    app = create_app(
        config=Config(), config_path=tmp_path / "c.toml",
        checks_factory=lambda c: [], session=FakeSession(),
    )
    assert TestClient(app).get("/api/meetings").json()["meetings"] == []


def test_regenerate_requires_an_existing_transcript(app_and_session):
    client, _, _ = app_and_session
    response = client.post("/api/regenerate", json={"transcript": "/nope.txt"})
    assert response.status_code == 404


def test_regenerate_writes_a_note(app_and_session, tmp_path, monkeypatch):
    client, _, _ = app_and_session
    transcript = tmp_path / "t.txt"
    transcript.write_text("we discussed things")

    from beyondmeetings import server as server_mod
    from beyondmeetings.models import MeetingNote

    class Stub:
        def analyse(self, prompt, valid_candidate_ids=None):
            return MeetingNote(
                title="Regenerated", date="2026-07-30",
                executive_summary="x", one_line_summary="x",
            )

    monkeypatch.setattr(server_mod, "build_provider", lambda cfg: Stub())
    body = client.post("/api/regenerate", json={"transcript": str(transcript)}).json()
    assert body["note_path"].endswith("Regenerated.md")


def test_regenerate_surfaces_a_provider_failure_as_400(app_and_session, tmp_path,
                                                       monkeypatch):
    client, _, _ = app_and_session
    transcript = tmp_path / "t.txt"
    transcript.write_text("text")

    from beyondmeetings import server as server_mod

    def boom(cfg):
        raise RuntimeError("no key stored")

    monkeypatch.setattr(server_mod, "build_provider", boom)
    response = client.post("/api/regenerate", json={"transcript": str(transcript)})
    assert response.status_code == 400
    assert "no key stored" in response.json()["detail"]
