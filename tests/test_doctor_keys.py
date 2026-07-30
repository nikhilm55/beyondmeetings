import pytest

from beyondmeetings.doctor.keys import (
    GroqKeyCheck, ProviderKeyCheck, validate_anthropic_key, validate_groq_key,
)


class _BrokenKeyring:
    """Forces the file fallback so tests never touch the real OS keyring."""

    def set_password(self, *a):
        raise RuntimeError("no backend")

    def get_password(self, *a):
        raise RuntimeError("no backend")


@pytest.fixture
def file_secrets(monkeypatch):
    from beyondmeetings import secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "keyring", _BrokenKeyring())
    return secrets_mod


def test_groq_validation_accepts_a_working_key(httpx_mock):
    httpx_mock.add_response(json={"data": []})
    assert validate_groq_key("gsk_good") == (True, "")


def test_groq_validation_rejects_a_bad_key(httpx_mock):
    httpx_mock.add_response(status_code=401, json={"error": {"message": "invalid"}})
    ok, detail = validate_groq_key("gsk_bad")
    assert ok is False
    assert "invalid" in detail


def test_groq_validation_reports_network_failure(httpx_mock):
    import httpx as _httpx
    httpx_mock.add_exception(_httpx.ConnectError("no route"))
    ok, detail = validate_groq_key("gsk_any")
    assert ok is False
    assert "no route" in detail


def test_anthropic_validation_accepts_a_working_key(httpx_mock):
    httpx_mock.add_response(json={"content": [{"type": "text", "text": "hi"}]})
    assert validate_anthropic_key("sk-good") == (True, "")


def test_anthropic_validation_rejects_a_bad_key(httpx_mock):
    httpx_mock.add_response(status_code=401, json={"error": {"message": "bad key"}})
    ok, detail = validate_anthropic_key("sk-bad")
    assert ok is False
    assert "bad key" in detail


def test_groq_check_missing_when_no_key_stored(tmp_path, file_secrets):
    assert GroqKeyCheck(secret_dir=tmp_path).detect().status == "missing"


def test_groq_check_ok_when_stored_key_validates(tmp_path, httpx_mock, file_secrets):
    file_secrets.set_secret("groq_api_key", "gsk_good", fallback_dir=tmp_path)
    httpx_mock.add_response(json={"data": []})
    assert GroqKeyCheck(secret_dir=tmp_path).detect().status == "ok"


def test_groq_check_broken_when_stored_key_rejected(tmp_path, httpx_mock, file_secrets):
    file_secrets.set_secret("groq_api_key", "gsk_bad", fallback_dir=tmp_path)
    httpx_mock.add_response(status_code=401, json={"error": {"message": "invalid"}})
    assert GroqKeyCheck(secret_dir=tmp_path).detect().status == "broken"


def test_groq_fix_stores_a_valid_key(tmp_path, httpx_mock, file_secrets):
    httpx_mock.add_response(json={"data": []})
    httpx_mock.add_response(json={"data": []})
    check = GroqKeyCheck(secret_dir=tmp_path)
    assert check.fix(api_key="gsk_new").status == "ok"
    assert file_secrets.get_secret("groq_api_key", fallback_dir=tmp_path) == "gsk_new"


def test_groq_fix_refuses_to_store_an_invalid_key(tmp_path, httpx_mock, file_secrets):
    httpx_mock.add_response(status_code=401, json={"error": {"message": "nope"}})
    check = GroqKeyCheck(secret_dir=tmp_path)
    assert check.fix(api_key="gsk_bad").status != "ok"
    assert file_secrets.get_secret("groq_api_key", fallback_dir=tmp_path) is None


def test_groq_fix_rejects_an_empty_key(tmp_path, file_secrets):
    assert GroqKeyCheck(secret_dir=tmp_path).fix(api_key="   ").status == "missing"


def test_provider_check_exposes_a_secret_input_field(tmp_path):
    check = ProviderKeyCheck(provider="anthropic", secret_dir=tmp_path)
    assert check.inputs[0].secret is True


def test_provider_check_rejects_unknown_provider(tmp_path):
    with pytest.raises(ValueError):
        ProviderKeyCheck(provider="nope", secret_dir=tmp_path)


def test_every_provider_now_has_a_working_check(tmp_path, file_secrets):
    """Was: asserted OpenAI is unsupported. Milestone 3 made that false."""
    for provider in ("anthropic", "openai", "gemini", "ollama"):
        check = ProviderKeyCheck(provider=provider, secret_dir=tmp_path)
        assert check.label
        assert "milestone" not in check.description.lower()


# --- Review findings #11, #12 ---

def test_error_detail_redacts_key_fragments():
    """OpenAI's 401 body echoes a partial key, and this reaches the browser."""
    import httpx

    from beyondmeetings.doctor.keys import _error_detail

    response = httpx.Response(
        401,
        json={"error": {"message": "Incorrect API key provided: sk-proj-AbCd1234XYZ"}},
    )
    detail = _error_detail(response)
    assert "sk-proj-AbCd1234XYZ" not in detail
    assert "<redacted>" in detail


def test_detect_says_where_a_verified_key_is_stored(tmp_path, httpx_mock,
                                                    file_secrets):
    file_secrets.set_secret("groq_api_key", "gsk_good", fallback_dir=tmp_path)
    httpx_mock.add_response(json={"data": []})
    detail = GroqKeyCheck(secret_dir=tmp_path).detect().detail
    assert "0600 file" in detail or "keyring" in detail
