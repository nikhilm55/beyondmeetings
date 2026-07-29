import pytest
from fastapi.testclient import TestClient

from beyondmeetings.config import Config, load_config
from beyondmeetings.doctor.base import Check, CheckResult, InputField
from beyondmeetings.server import create_app


class StubCheck(Check):
    id = "stub"
    label = "Stub"
    required = True
    inputs = [InputField(name="value", label="Value")]

    def __init__(self):
        self.status = "missing"
        self.received = None

    def detect(self):
        return CheckResult(status=self.status)

    @property
    def fixable(self):
        return True

    def fix(self, **kwargs):
        self.received = kwargs
        self.status = "ok"
        return CheckResult(status="ok")


@pytest.fixture
def check():
    return StubCheck()


@pytest.fixture
def client(tmp_path, check):
    app = create_app(
        config=Config(),
        config_path=tmp_path / "config.toml",
        checks_factory=lambda cfg: [check],
    )
    return TestClient(app)


def test_status_returns_rows_and_percent(client):
    body = client.get("/api/status").json()
    assert body["percent"] == 0
    assert body["checks"][0]["id"] == "stub"


def test_fix_dispatches_to_the_named_check(client, check):
    response = client.post("/api/fix/stub", json={"value": "hello"})
    assert response.status_code == 200
    assert check.received == {"value": "hello"}


def test_percent_updates_after_a_successful_fix(client):
    client.post("/api/fix/stub", json={})
    assert client.get("/api/status").json()["percent"] == 100


def test_fix_returns_fresh_rows_without_a_second_request(client):
    body = client.post("/api/fix/stub", json={}).json()
    assert body["percent"] == 100
    assert body["checks"][0]["status"] == "ok"


def test_fix_on_unknown_check_returns_404(client):
    assert client.post("/api/fix/nope", json={}).status_code == 404


def test_settings_persists_provider_choice(client, tmp_path):
    client.post("/api/settings", json={"provider": "openai"})
    assert load_config(tmp_path / "config.toml").provider == "openai"


def test_settings_rejects_unknown_field(client):
    assert client.post("/api/settings", json={"nope": 1}).status_code == 422


def test_status_never_leaks_secrets(client):
    assert "api_key" not in client.get("/api/status").text


def test_setup_page_is_served(client):
    response = client.get("/setup")
    assert response.status_code == 200
    assert "beyondMeetings" in response.text


def test_static_assets_are_served(client):
    assert client.get("/setup.css").status_code == 200
    assert client.get("/setup.js").status_code == 200
