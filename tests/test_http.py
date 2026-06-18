"""Tests for the shared polite-fetch helper (retry/backoff)."""

from __future__ import annotations

import httpx
import pytest

from cutoffs.adapters import _http


class _FakeResp:
    def __init__(self):
        self.text = "ok"

    def raise_for_status(self):
        return None


def test_fetch_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom")
        return _FakeResp()

    monkeypatch.setattr(_http.httpx, "get", flaky)
    resp = _http.fetch("https://example.test/", retries=2, backoff=0)
    assert resp.text == "ok"
    assert calls["n"] == 3  # failed twice, succeeded on the third


def test_fetch_reraises_after_exhausting_retries(monkeypatch):
    def always_fail(url, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(_http.httpx, "get", always_fail)
    with pytest.raises(httpx.ConnectError):
        _http.fetch("https://example.test/", retries=1, backoff=0)


def test_fetch_sends_user_agent(monkeypatch):
    seen = {}

    def capture(url, **kwargs):
        seen.update(kwargs)
        return _FakeResp()

    monkeypatch.setattr(_http.httpx, "get", capture)
    _http.fetch("https://example.test/")
    assert "User-Agent" in seen["headers"]
    assert seen["follow_redirects"] is True
