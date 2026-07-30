import httpx

from beyondmeetings.doctor.keys import (
    ProviderKeyCheck, validate_gemini_key, validate_ollama, validate_openai_key,
)


class _BrokenKeyring:
    def set_password(self, *a):
        raise RuntimeError("no backend")

    def get_password(self, *a):
        raise RuntimeError("no backend")


def _file_secrets(monkeypatch):
    from beyondmeetings import secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", _BrokenKeyring())
    return secrets_mod


def test_openai_accepts_a_working_key(httpx_mock):
    httpx_mock.add_response(json={"data": []})
    assert validate_openai_key("sk-good") == (True, "")


def test_openai_rejects_a_bad_key(httpx_mock):
    httpx_mock.add_response(status_code=401, json={"error": {"message": "nope"}})
    ok, detail = validate_openai_key("sk-bad")
    assert ok is False and "nope" in detail


def test_openai_reports_network_failure(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("no route"))
    ok, detail = validate_openai_key("sk-x")
    assert ok is False and "no route" in detail


def test_gemini_accepts_a_working_key(httpx_mock):
    httpx_mock.add_response(json={"models": []})
    assert validate_gemini_key("good") == (True, "")


def test_gemini_sends_the_key_in_a_header(httpx_mock):
    httpx_mock.add_response(json={"models": []})
    validate_gemini_key("secret")
    request = httpx_mock.get_requests()[0]
    assert request.headers["x-goog-api-key"] == "secret"
    assert "secret" not in str(request.url)


def test_ollama_ok_when_daemon_responds(httpx_mock):
    httpx_mock.add_response(json={"models": [{"name": "qwen2.5:14b"}]})
    assert validate_ollama("http://localhost:11434", "qwen2.5:14b") == (True, "")


def test_ollama_reports_a_stopped_daemon(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    ok, detail = validate_ollama("http://localhost:11434", "qwen2.5:14b")
    assert ok is False and "ollama serve" in detail


def test_ollama_reports_a_model_that_is_not_pulled(httpx_mock):
    httpx_mock.add_response(json={"models": [{"name": "llama3:8b"}]})
    ok, detail = validate_ollama("http://localhost:11434", "qwen2.5:14b")
    assert ok is False and "ollama pull qwen2.5:14b" in detail
    assert "llama3:8b" in detail


def test_ollama_provider_check_needs_no_key_input(tmp_path):
    assert ProviderKeyCheck(provider="ollama", secret_dir=tmp_path).inputs == []


def test_ollama_check_is_not_fixable_from_the_wizard(tmp_path):
    assert ProviderKeyCheck(provider="ollama", secret_dir=tmp_path).fixable is False


def test_ollama_check_ok_without_any_stored_secret(tmp_path, httpx_mock, monkeypatch):
    _file_secrets(monkeypatch)
    httpx_mock.add_response(json={"models": [{"name": "qwen2.5:14b"}]})
    check = ProviderKeyCheck(provider="ollama", secret_dir=tmp_path)
    assert check.detect().status == "ok"


def test_ollama_check_missing_when_daemon_down(tmp_path, httpx_mock, monkeypatch):
    _file_secrets(monkeypatch)
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    check = ProviderKeyCheck(provider="ollama", secret_dir=tmp_path)
    assert check.detect().status == "missing"


def test_openai_check_stores_a_validated_key(tmp_path, httpx_mock, monkeypatch):
    secrets_mod = _file_secrets(monkeypatch)
    httpx_mock.add_response(json={"data": []})
    httpx_mock.add_response(json={"data": []})
    check = ProviderKeyCheck(provider="openai", secret_dir=tmp_path)
    assert check.fix(api_key="sk-new").status == "ok"
    assert secrets_mod.get_secret("openai_api_key", fallback_dir=tmp_path) == "sk-new"


def test_gemini_check_refuses_an_invalid_key(tmp_path, httpx_mock, monkeypatch):
    secrets_mod = _file_secrets(monkeypatch)
    httpx_mock.add_response(status_code=400, json={"error": {"message": "bad"}})
    check = ProviderKeyCheck(provider="gemini", secret_dir=tmp_path)
    assert check.fix(api_key="bad").status != "ok"
    assert secrets_mod.get_secret("gemini_api_key", fallback_dir=tmp_path) is None
