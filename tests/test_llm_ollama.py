import json

import httpx
import pytest

from beyondmeetings.llm.base import ResponseParseError
from beyondmeetings.llm.ollama import OllamaProvider

NOTE_JSON = ('{"title": "Standup", "date": "2026-07-30", '
             '"executive_summary": "We synced."}')
BODY = {"message": {"content": NOTE_JSON}}


def test_returns_parsed_note(httpx_mock):
    httpx_mock.add_response(json=BODY)
    assert OllamaProvider().analyse("prompt").title == "Standup"


def test_posts_to_the_configured_host(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OllamaProvider(host="http://box:1234").analyse("prompt")
    assert str(httpx_mock.get_requests()[0].url).startswith("http://box:1234")


def test_trailing_slash_on_host_is_tolerated(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OllamaProvider(host="http://box:1234/").analyse("prompt")
    assert "//api/chat" not in str(httpx_mock.get_requests()[0].url)


def test_requests_json_format_and_disables_streaming(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OllamaProvider().analyse("prompt")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["format"] == "json"
    assert payload["stream"] is False


def test_no_authorization_header_is_sent(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OllamaProvider().analyse("prompt")
    assert "authorization" not in httpx_mock.get_requests()[0].headers


def test_daemon_not_running_gives_an_actionable_error(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    with pytest.raises(RuntimeError, match="ollama serve"):
        OllamaProvider().analyse("prompt")


def test_missing_model_error_suggests_pulling_it(httpx_mock):
    httpx_mock.add_response(status_code=404, json={"error": "model not found"})
    with pytest.raises(RuntimeError, match="ollama pull qwen2.5:14b"):
        OllamaProvider(model="qwen2.5:14b").analyse("prompt")


def test_unparseable_content_raises_parse_error(httpx_mock):
    httpx_mock.add_response(json={"message": {"content": "I cannot"}})
    with pytest.raises(ResponseParseError):
        OllamaProvider().analyse("prompt")


def test_default_model_is_reported_on_the_instance():
    assert OllamaProvider().model


# --- Review finding #10: silent context truncation ---

def test_num_ctx_is_sent_explicitly(httpx_mock):
    """Ollama's 4096 default would drop most of an hour-long meeting."""
    httpx_mock.add_response(json=BODY)
    OllamaProvider().analyse("prompt")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["options"]["num_ctx"] >= 32768


def test_an_oversized_prompt_is_refused_rather_than_truncated():
    """A silently truncated transcript yields a confident, wrong note."""
    provider = OllamaProvider(num_ctx=4096)
    with pytest.raises(RuntimeError, match="silently drop"):
        provider.analyse("x" * 200_000)


def test_the_refusal_names_both_numbers():
    provider = OllamaProvider(num_ctx=4096)
    with pytest.raises(RuntimeError, match="4,096"):
        provider.analyse("x" * 200_000)


def test_a_prompt_within_the_window_is_sent(httpx_mock):
    httpx_mock.add_response(json=BODY)
    assert OllamaProvider(num_ctx=32768).analyse("x" * 1000).title == "Standup"


def test_html_error_body_reports_the_status_code(httpx_mock):
    httpx_mock.add_response(status_code=502, text="<html>Bad Gateway</html>")
    with pytest.raises(RuntimeError, match="502"):
        OllamaProvider().analyse("prompt")
