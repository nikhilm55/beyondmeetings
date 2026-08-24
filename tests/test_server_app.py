from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from beyondmeetings.config import Config
from beyondmeetings.server import (
    DiscussionRequest,
    NoteRequest,
    TranslationRequest,
    create_app,
)
from beyondmeetings.vault.scaffold import scaffold_vault

IDLE = {
    "phase": "idle", "detail": "", "recording": False, "name": "",
    "elapsed_seconds": 0, "segments_done": 0, "segments_total": 0,
    "note_path": None, "transcript_path": None, "error": None,
}


def route_endpoint(app, path, method):
    return next(
        route.endpoint for route in app.routes
        if getattr(route, "path", None) == path and method in route.methods
    )


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
    data = tmp_path / "data"
    (data / "transcripts").mkdir(parents=True)
    session = FakeSession()
    app = create_app(
        config=Config(vault_path=str(vault), data_dir=str(data)),
        config_path=tmp_path / "config.toml",
        checks_factory=lambda c: [],
        session=session,
        pdf_export_dir=tmp_path / "exports",
    )
    return TestClient(app), session, vault


def test_root_serves_the_app_page(app_and_session):
    client, _, _ = app_and_session
    response = client.get("/")
    assert response.status_code == 200
    assert "app.css" in response.text
    assert "Ask your notes" in response.text
    assert 'id="recordingBadge"' in response.text


def test_app_page_includes_pdf_and_share_actions(app_and_session):
    client, _, _ = app_and_session
    page = route_endpoint(client.app, "/", "GET")()
    assert 'id="convertPdf"' in page
    assert 'id="sharePdf"' in page
    assert 'id="minutesView"' in page
    assert 'id="discussionView"' in page
    assert 'id="translationView"' in page
    assert 'id="translationLanguage"' in page
    assert "Decisions and action items" in page
    assert "Topics, reasoning and context" in page
    assert "Full conversation in Hinglish" in page


def test_ai_tabs_stay_clickable_while_background_work_runs(app_and_session):
    client, _, _ = app_and_session
    script = route_endpoint(client.app, "/{asset}.js", "GET")("app")
    assert '$("discussionView").disabled = true' not in script.body.decode()
    assert '$("translationView").disabled = true' not in script.body.decode()
    assert "discussionRequests.get(cacheKey)" in script.body.decode()
    assert "translationRequests.get(cacheKey)" in script.body.decode()
    assert "result.turns" in script.body.decode()


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


def test_meeting_note_can_be_read_inside_the_app(app_and_session):
    client, _, vault = app_and_session
    note = vault / "Meetings" / "2026-07-30" / "Standup.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Standup\n\n## Executive Summary\nWe synced.\n")
    response = client.get("/api/note", params={"path": "Meetings/2026-07-30/Standup"})
    assert response.status_code == 200
    assert "We synced" in response.json()["content"]


def test_meeting_note_can_be_exported_and_downloaded_as_pdf(app_and_session):
    client, _, vault = app_and_session
    note = vault / "Meetings" / "2026-07-30" / "Standup.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Standup\n\n## Executive Summary\nWe synced.\n")

    create_pdf = route_endpoint(client.app, "/api/note/pdf", "POST")
    created = create_pdf(NoteRequest(path="Meetings/2026-07-30/Standup"))
    target = Path(created["pdf_path"])
    assert target.name == "Standup - 2026-07-30.pdf"
    assert target.read_bytes().startswith(b"%PDF")

    download_pdf = route_endpoint(client.app, "/api/note/pdf", "GET")
    downloaded = download_pdf("Meetings/2026-07-30/Standup")
    assert downloaded.media_type == "application/pdf"
    assert Path(downloaded.path).read_bytes().startswith(b"%PDF")


def test_discussion_summary_is_generated_cached_and_exported(app_and_session,
                                                              monkeypatch):
    client, _, vault = app_and_session
    note = vault / "Meetings" / "2026-07-30" / "Standup.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ndate: 2026-07-30\n---\n\n# Standup\n\n"
        "## Executive Summary\nWe compared launch options.\n"
    )

    from beyondmeetings import server as server_mod
    from beyondmeetings.models import MeetingNote

    calls = []

    class Stub:
        def analyse(self, prompt, valid_candidate_ids=None):
            calls.append(prompt)
            return MeetingNote(
                title="Discussion Summary",
                date="2026-01-01",
                executive_summary=(
                    "## Discussion Overview\n\nहमने विकल्पों पर चर्चा की।\n\n"
                    "## Main Themes\n- लॉन्च\n\n"
                    "## Important Context\nसमय महत्वपूर्ण था।"
                ),
            )

    monkeypatch.setattr(server_mod, "build_provider", lambda config: Stub())
    endpoint = route_endpoint(client.app, "/api/note/discussion", "POST")
    request = DiscussionRequest(
        path="Meetings/2026-07-30/Standup",
        language="Hindi",
    )
    generated = endpoint(request)
    cached = endpoint(request)

    assert generated["cached"] is False
    assert cached["cached"] is True
    assert "चर्चा" in cached["content"]
    assert len(calls) == 1

    create_pdf = route_endpoint(client.app, "/api/note/pdf", "POST")
    exported = create_pdf(NoteRequest(
        path="Meetings/2026-07-30/Standup",
        view="discussion",
        language="Hindi",
    ))
    target = Path(exported["pdf_path"])
    assert target.name == "Standup - 2026-07-30 - Discussion Summary - Hindi.pdf"
    assert target.read_bytes().startswith(b"%PDF")


def test_full_transcript_is_translated_cached_and_exported(
    app_and_session,
    monkeypatch,
    tmp_path,
):
    client, _, vault = app_and_session
    note = vault / "Meetings" / "2026-07-30" / "Standup.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ndate: 2026-07-30\n"
        "transcript: 2026-07-30/recording.txt\n---\n\n"
        "# Standup\n\n## Executive Summary\nWe talked.\n"
    )
    transcript = tmp_path / "data" / "transcripts" / "2026-07-30" / "recording.txt"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("First statement. Second statement. Repeat, repeat.")

    from beyondmeetings import server as server_mod
    from beyondmeetings.models import MeetingNote

    calls = []

    class Stub:
        def analyse(self, prompt, valid_candidate_ids=None):
            calls.append(prompt)
            return MeetingNote(
                title="Translated Transcript",
                date="2026-01-01",
                executive_summary=(
                    "Person A: पहला कथन।\n"
                    "Person B: दूसरा कथन।\n"
                    "Person A: दोहराएं, दोहराएं।"
                ),
            )

    monkeypatch.setattr(server_mod, "build_provider", lambda config: Stub())
    endpoint = route_endpoint(client.app, "/api/note/translation", "POST")
    request = TranslationRequest(
        path="Meetings/2026-07-30/Standup",
        language="Hindi",
    )
    generated = endpoint(request)
    cached = endpoint(request)

    assert generated["cached"] is False
    assert cached["cached"] is True
    assert "पहला" in cached["content"]
    assert cached["turns"][0] == {
        "speaker": "Person A",
        "text": "पहला कथन।",
    }
    assert cached["turns"][1]["speaker"] == "Person B"
    assert len(calls) == 1

    create_pdf = route_endpoint(client.app, "/api/note/pdf", "POST")
    exported = create_pdf(NoteRequest(
        path="Meetings/2026-07-30/Standup",
        view="translation",
        language="Hindi",
    ))
    target = Path(exported["pdf_path"])
    assert target.name == "Standup - 2026-07-30 - Conversation Transcript - Hindi.pdf"
    assert target.read_bytes().startswith(b"%PDF")


def test_share_reveals_the_generated_pdf(tmp_path):
    vault = tmp_path / "vault"
    note = vault / "Meetings" / "2026-07-30" / "Plan.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Plan\n\nShare this meeting.\n")
    shared = []
    app = create_app(
        config=Config(vault_path=str(vault), data_dir=str(tmp_path / "data")),
        config_path=tmp_path / "config.toml",
        checks_factory=lambda config: [],
        session=FakeSession(),
        pdf_export_dir=tmp_path / "exports",
        pdf_sharer=shared.append,
    )

    share_pdf = route_endpoint(app, "/api/note/share", "POST")
    response = share_pdf(NoteRequest(path="Meetings/2026-07-30/Plan"))

    assert response["action"] == "revealed"
    assert shared == [Path(response["pdf_path"])]
    assert shared[0].is_file()


def test_pdf_export_refuses_traversal(app_and_session, tmp_path):
    client, _, _ = app_and_session
    (tmp_path / "secret.md").write_text("secret")
    create_pdf = route_endpoint(client.app, "/api/note/pdf", "POST")
    with pytest.raises(HTTPException) as error:
        create_pdf(NoteRequest(path="../../secret"))
    assert error.value.status_code == 403


def test_note_reader_refuses_traversal(app_and_session, tmp_path):
    client, _, _ = app_and_session
    (tmp_path / "secret.md").write_text("secret")
    assert client.get("/api/note", params={"path": "../../secret"}).status_code == 403


def test_tasks_are_available_to_the_built_in_app(app_and_session):
    client, _, vault = app_and_session
    board = vault / "Tasks" / "Task Board.md"
    board.write_text(board.read_text().replace(
        "> [!todo]+ Pending — 0\n",
        "> [!todo]+ Pending — 1\n"
        "> > **==Ship it==** · `App` · `HIGH`\n"
        "> > Finish it. — **Nikhil** · [[Meetings/2026-07-30/Plan]]\n> >\n",
    ))
    assert client.get("/api/tasks").json()["tasks"][0]["title"] == "Ship it"


def test_library_folder_can_be_opened_from_setup(app_and_session, monkeypatch):
    client, _, vault = app_and_session
    opened = []
    monkeypatch.setattr("beyondmeetings.server.open_library_folder", opened.append)
    response = client.post("/api/library/open", json={})
    assert response.status_code == 200
    assert opened == [vault]


def test_library_chat_fetches_old_meeting_files(app_and_session):
    client, _, vault = app_and_session
    folder = vault / "Meetings" / "2026-07-30"
    folder.mkdir(parents=True)
    (folder / "Launch.md").write_text(
        "---\ntags:\n  - meeting\ndate: 2026-07-30\n---\n\n"
        "# Launch\n\n## Executive Summary\nWe planned the Mumbai launch.\n"
    )
    body = client.post("/api/library/chat", json={"query": "Mumbai"}).json()
    assert body["sources"][0]["title"] == "Launch"


def test_library_chat_rejects_an_empty_or_oversized_query(app_and_session):
    client, _, _ = app_and_session
    assert client.post("/api/library/chat", json={"query": ""}).status_code == 422
    assert client.post(
        "/api/library/chat", json={"query": "x" * 501}
    ).status_code == 422


def test_history_is_empty_without_a_vault(tmp_path):
    app = create_app(
        config=Config(), config_path=tmp_path / "c.toml",
        checks_factory=lambda c: [], session=FakeSession(),
    )
    assert TestClient(app).get("/api/meetings").json()["meetings"] == []


def test_regenerate_requires_an_existing_transcript(app_and_session, tmp_path):
    client, _, _ = app_and_session
    missing = tmp_path / "data" / "transcripts" / "nope.txt"
    response = client.post("/api/regenerate", json={"transcript": str(missing)})
    assert response.status_code == 404


def test_regenerate_writes_a_note(app_and_session, tmp_path, monkeypatch):
    client, _, _ = app_and_session
    transcript = tmp_path / "data" / "transcripts" / "t.txt"
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
    transcript = tmp_path / "data" / "transcripts" / "t.txt"
    transcript.write_text("text")

    from beyondmeetings import server as server_mod

    def boom(cfg):
        raise RuntimeError("no key stored")

    monkeypatch.setattr(server_mod, "build_provider", boom)
    response = client.post("/api/regenerate", json={"transcript": str(transcript)})
    assert response.status_code == 400
    assert "no key stored" in response.json()["detail"]


def test_reset_endpoint_clears_a_wedged_session(app_and_session):
    client, session, _ = app_and_session
    session.reset = lambda: {**session.state, "phase": "idle"}
    assert client.post("/api/recording/reset", json={}).json()["phase"] == "idle"


# --- Review finding: DNS rebinding + arbitrary-path exfiltration ---

def test_regenerate_refuses_a_path_outside_the_transcripts_dir(app_and_session,
                                                               tmp_path):
    """Reading any path and posting it to an LLM is an exfiltration primitive."""
    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY")
    client, _, _ = app_and_session
    response = client.post("/api/regenerate", json={"transcript": str(secret)})
    assert response.status_code == 403
    assert "PRIVATE KEY" not in response.text


def test_regenerate_refuses_traversal_out_of_the_transcripts_dir(app_and_session,
                                                                 tmp_path):
    client, _, _ = app_and_session
    sneaky = tmp_path / "data" / "transcripts" / ".." / ".." / "id_rsa"
    assert client.post(
        "/api/regenerate", json={"transcript": str(sneaky)}
    ).status_code == 403


def test_a_foreign_host_header_is_rejected(app_and_session):
    """DNS rebinding: attacker.com resolving to 127.0.0.1 would be same-origin."""
    client, _, _ = app_and_session
    response = client.get("/api/recording", headers={"host": "evil.example.com"})
    assert response.status_code == 421


def test_localhost_and_loopback_hosts_are_accepted(app_and_session):
    client, _, _ = app_and_session
    for host in ("localhost:7788", "127.0.0.1:7788"):
        assert client.get("/api/recording", headers={"host": host}).status_code == 200
