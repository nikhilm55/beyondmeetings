import json

import pytest

from beyondmeetings.llm.base import ResponseParseError
from beyondmeetings.llm.gemini import GeminiProvider

NOTE_JSON = ('{"title": "Standup", "date": "2026-07-30", '
             '"executive_summary": "We synced."}')
BODY = {"candidates": [{"content": {"parts": [{"text": NOTE_JSON}]}}]}


def test_returns_parsed_note(httpx_mock):
    httpx_mock.add_response(json=BODY)
    assert GeminiProvider(api_key="k").analyse("prompt").title == "Standup"


def test_sends_key_as_header_not_query_string(httpx_mock):
    """A key in the URL leaks into logs and proxies."""
    httpx_mock.add_response(json=BODY)
    GeminiProvider(api_key="secret-key").analyse("prompt")
    request = httpx_mock.get_requests()[0]
    assert request.headers["x-goog-api-key"] == "secret-key"
    assert "secret-key" not in str(request.url)


def test_requests_json_response_mime_type(httpx_mock):
    httpx_mock.add_response(json=BODY)
    GeminiProvider(api_key="k").analyse("prompt")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


def test_sends_prompt_text(httpx_mock):
    httpx_mock.add_response(json=BODY)
    GeminiProvider(api_key="k").analyse("analyse this")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["contents"][0]["parts"][0]["text"] == "analyse this"


def test_model_appears_in_the_url(httpx_mock):
    httpx_mock.add_response(json=BODY)
    GeminiProvider(api_key="k", model="gemini-3-pro").analyse("p")
    assert "gemini-3-pro:generateContent" in str(httpx_mock.get_requests()[0].url)


def test_http_error_surfaces_the_api_message(httpx_mock):
    httpx_mock.add_response(status_code=400, json={"error": {"message": "bad key"}})
    with pytest.raises(RuntimeError, match="bad key"):
        GeminiProvider(api_key="bad").analyse("prompt")


def test_joins_multiple_parts(httpx_mock):
    half, rest = NOTE_JSON[:20], NOTE_JSON[20:]
    httpx_mock.add_response(json={"candidates": [
        {"content": {"parts": [{"text": half}, {"text": rest}]}}]})
    assert GeminiProvider(api_key="k").analyse("p").title == "Standup"


def test_empty_candidates_raises_parse_error(httpx_mock):
    httpx_mock.add_response(json={"candidates": []})
    with pytest.raises(ResponseParseError):
        GeminiProvider(api_key="k").analyse("prompt")


# --- Review finding #7: realistic responses crashed the adapter ---

def test_safety_block_raises_a_parse_error_not_a_key_error(httpx_mock):
    """A blocked candidate omits `content` entirely."""
    httpx_mock.add_response(json={"candidates": [{"finishReason": "SAFETY"}]})
    with pytest.raises(ResponseParseError, match="SAFETY"):
        GeminiProvider(api_key="k").analyse("prompt")


def test_safety_block_explains_why_transcripts_trigger_it(httpx_mock):
    httpx_mock.add_response(json={"candidates": [{"finishReason": "SAFETY"}]})
    with pytest.raises(ResponseParseError, match="personnel or health"):
        GeminiProvider(api_key="k").analyse("prompt")


def test_truncated_output_is_reported_as_truncation(httpx_mock):
    httpx_mock.add_response(json={"candidates": [{
        "finishReason": "MAX_TOKENS",
        "content": {"parts": [{"text": '{"title": "Half'}]},
    }]})
    with pytest.raises(RuntimeError, match="output limit"):
        GeminiProvider(api_key="k").analyse("prompt")


def test_prompt_block_names_the_reason(httpx_mock):
    httpx_mock.add_response(json={"promptFeedback": {"blockReason": "OTHER"}})
    with pytest.raises(ResponseParseError, match="OTHER"):
        GeminiProvider(api_key="k").analyse("prompt")


def test_html_error_body_reports_the_status_code(httpx_mock):
    httpx_mock.add_response(status_code=502, text="<html>Bad Gateway</html>")
    with pytest.raises(RuntimeError, match="502"):
        GeminiProvider(api_key="k").analyse("prompt")
