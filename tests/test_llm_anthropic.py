import json

import pytest

from beyondmeetings.llm.anthropic import AnthropicProvider
from beyondmeetings.llm.base import ResponseParseError

BODY = {"content": [{"type": "text", "text":
        '{"title": "Standup", "date": "2026-07-30", '
        '"executive_summary": "We synced."}'}]}


def test_returns_parsed_note(httpx_mock):
    httpx_mock.add_response(json=BODY)
    note = AnthropicProvider(api_key="sk-test").analyse("prompt")
    assert note.title == "Standup"


def test_sends_api_key_and_version_headers(httpx_mock):
    httpx_mock.add_response(json=BODY)
    AnthropicProvider(api_key="sk-test").analyse("prompt")
    request = httpx_mock.get_requests()[0]
    assert request.headers["x-api-key"] == "sk-test"
    assert request.headers["anthropic-version"] == "2023-06-01"


def test_sends_prompt_as_user_message(httpx_mock):
    httpx_mock.add_response(json=BODY)
    AnthropicProvider(api_key="sk-test").analyse("analyse this")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["messages"][0]["content"] == "analyse this"
    assert payload["model"]


def test_http_error_raises_runtime_error(httpx_mock):
    httpx_mock.add_response(status_code=401, json={"error": {"message": "bad key"}})
    with pytest.raises(RuntimeError, match="bad key"):
        AnthropicProvider(api_key="sk-bad").analyse("prompt")


def test_unparseable_content_raises_parse_error(httpx_mock):
    httpx_mock.add_response(json={"content": [{"type": "text", "text": "sorry"}]})
    with pytest.raises(ResponseParseError):
        AnthropicProvider(api_key="sk-test").analyse("prompt")
