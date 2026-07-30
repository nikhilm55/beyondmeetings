"""Shared HTTP-error handling for the provider adapters.

Every adapter used to call response.json() inside its own error branch, so a
502 with an HTML body from a proxy raised JSONDecodeError instead of the
intended "API error 502". doctor/keys.py already solved this; the adapters
just were not reusing it.
"""
from __future__ import annotations

import httpx


def error_detail(response: httpx.Response) -> str:
    """A useful message whatever the body turns out to be."""
    try:
        payload = response.json()
    except Exception:
        body = response.text.strip()
        return body[:200] or f"empty body (HTTP {response.status_code})"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str):
            return error
        if payload.get("message"):
            return str(payload["message"])
    return str(payload)[:200]


def raise_for_status(provider: str, response: httpx.Response) -> None:
    if response.status_code != 200:
        raise RuntimeError(
            f"{provider} API error {response.status_code}: {error_detail(response)}"
        )


class TruncatedResponseError(RuntimeError):
    """The model hit its output limit — the JSON is cut off, not malformed."""

    def __init__(self, provider: str, limit: int):
        super().__init__(
            f"{provider} stopped at the {limit}-token output limit, so the note "
            "is incomplete. Raise max_tokens, or use a shorter meeting."
        )
