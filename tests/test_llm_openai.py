import json

import pytest

from beyondmeetings.llm.base import ResponseParseError
from beyondmeetings.llm.openai import OpenAIProvider

NOTE_JSON = ('{"title": "Standup", "date": "2026-07-30", '
             '"executive_summary": "We synced."}')
BODY = {"choices": [{"message": {"content": NOTE_JSON}}]}


def test_returns_parsed_note(httpx_mock):
    httpx_mock.add_response(json=BODY)
    assert OpenAIProvider(api_key="sk-t").analyse("prompt").title == "Standup"


def test_sends_bearer_authorization(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OpenAIProvider(api_key="sk-t").analyse("prompt")
    assert httpx_mock.get_requests()[0].headers["authorization"] == "Bearer sk-t"


def test_requests_json_object_response_format(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OpenAIProvider(api_key="sk-t").analyse("prompt")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["response_format"] == {"type": "json_object"}


def test_sends_prompt_as_user_message(httpx_mock):
    httpx_mock.add_response(json=BODY)
    OpenAIProvider(api_key="sk-t").analyse("analyse this")
    payload = json.loads(httpx_mock.get_requests()[0].content)
    assert payload["messages"][-1]["content"] == "analyse this"


def test_http_error_surfaces_the_api_message(httpx_mock):
    httpx_mock.add_response(status_code=401, json={"error": {"message": "bad key"}})
    with pytest.raises(RuntimeError, match="bad key"):
        OpenAIProvider(api_key="sk-bad").analyse("prompt")


def test_unparseable_content_raises_parse_error(httpx_mock):
    httpx_mock.add_response(json={"choices": [{"message": {"content": "sorry"}}]})
    with pytest.raises(ResponseParseError):
        OpenAIProvider(api_key="sk-t").analyse("prompt")


def test_candidate_ids_are_enforced(httpx_mock):
    raw = NOTE_JSON[:-1] + ', "follow_up_of": "2020-01-01/Invented"}'
    httpx_mock.add_response(json={"choices": [{"message": {"content": raw}}]})
    note = OpenAIProvider(api_key="sk-t").analyse("p", valid_candidate_ids=[])
    assert note.follow_up_of is None


# --- Review finding #7: realistic responses crashed the adapter ---

def test_refusal_raises_a_parse_error_not_an_attribute_error(httpx_mock):
    """A refusal sets content to null; .strip() on None crashed."""
    httpx_mock.add_response(json={"choices": [{
        "message": {"content": None, "refusal": "I can't help with that"},
        "finish_reason": "stop",
    }]})
    with pytest.raises(ResponseParseError, match="refused"):
        OpenAIProvider(api_key="sk-t").analyse("prompt")


def test_truncated_output_is_reported_as_truncation(httpx_mock):
    httpx_mock.add_response(json={"choices": [{
        "message": {"content": '{"title": "Half a no'},
        "finish_reason": "length",
    }]})
    with pytest.raises(RuntimeError, match="output limit"):
        OpenAIProvider(api_key="sk-t").analyse("prompt")


def test_html_error_body_reports_the_status_code(httpx_mock):
    httpx_mock.add_response(status_code=502, text="<html><h1>Bad Gateway</h1></html>")
    with pytest.raises(RuntimeError, match="502"):
        OpenAIProvider(api_key="sk-t").analyse("prompt")


def test_empty_choices_raises_a_parse_error(httpx_mock):
    httpx_mock.add_response(json={"choices": []})
    with pytest.raises(ResponseParseError, match="no choices"):
        OpenAIProvider(api_key="sk-t").analyse("prompt")
