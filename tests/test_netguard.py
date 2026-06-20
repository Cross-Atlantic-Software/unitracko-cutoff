"""Tests for the SSRF guard + polite-fetch helpers (cutoffs/netguard).

The URL guard and the redirect-revalidation are security-critical, so they get
direct coverage. IP literals are used for the public/blocked cases so the guard's
verdict never depends on live DNS; the one unresolvable-host case uses the reserved
``.invalid`` TLD (guaranteed NXDOMAIN, no real network).
"""
from __future__ import annotations

import cutoffs.netguard as ng
from cutoffs.netguard import fetch_validated, is_safe_url


# --------------------------------------------------------------------------
# is_safe_url — the SSRF guard
# --------------------------------------------------------------------------
def test_public_ip_urls_are_allowed():
    assert is_safe_url("http://8.8.8.8/")
    assert is_safe_url("https://1.1.1.1/path?q=1")
    assert is_safe_url("http://1.1.1.1:8080/x")     # port stripped from host check


def test_loopback_and_localhost_blocked():
    assert not is_safe_url("http://127.0.0.1/")
    assert not is_safe_url("http://localhost/")
    assert not is_safe_url("http://[::1]/")          # IPv6 loopback


def test_cloud_metadata_and_private_ranges_blocked():
    assert not is_safe_url("http://169.254.169.254/latest/meta-data/")  # link-local
    assert not is_safe_url("http://10.0.0.5/")
    assert not is_safe_url("http://192.168.1.1/")
    assert not is_safe_url("http://172.16.0.9/")


def test_non_http_schemes_blocked():
    assert not is_safe_url("file:///etc/passwd")
    assert not is_safe_url("ftp://8.8.8.8/")
    assert not is_safe_url("gopher://8.8.8.8/")
    assert not is_safe_url("")
    assert not is_safe_url("not a url")


def test_unresolvable_host_blocked():
    # reserved .invalid TLD never resolves -> guard blocks (no live network needed)
    assert not is_safe_url("http://nonexistent-host.invalid/")


# --------------------------------------------------------------------------
# throttle — must not crash; records the host
# --------------------------------------------------------------------------
def test_throttle_records_host(monkeypatch):
    monkeypatch.setattr(ng, "JITTER", (0.0, 0.0))   # keep the test fast
    ng.throttle("")                                  # no host -> no-op, no error
    ng.throttle("example.com")
    assert "example.com" in ng._LAST_REQUEST


# --------------------------------------------------------------------------
# fetch_validated — per-hop redirect validation + size cap (stub client)
# --------------------------------------------------------------------------
class _StubResp:
    def __init__(self, status, headers=None, body=b""):
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self.encoding = "utf-8"

    @property
    def is_redirect(self):
        return 300 <= self.status_code < 400

    def iter_bytes(self):
        for i in range(0, len(self._body), 4):       # small chunks -> exercise the cap
            yield self._body[i:i + 4]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _StubClient:
    def __init__(self, responses):
        self._responses = responses
        self.requested: list[str] = []

    def stream(self, method, url):
        self.requested.append(url)
        return self._responses[url]


def test_fetch_validated_returns_capped_body(monkeypatch):
    monkeypatch.setattr(ng, "JITTER", (0.0, 0.0))
    client = _StubClient({"http://1.1.1.1/": _StubResp(200, {}, b"x" * 100)})
    status, text = fetch_validated(client, "http://1.1.1.1/", max_bytes=10)
    assert status == 200
    assert 0 < len(text) <= 10                       # capped, not the full 100


def test_fetch_validated_blocks_redirect_to_internal(monkeypatch):
    monkeypatch.setattr(ng, "JITTER", (0.0, 0.0))
    # a public start that 302s to the cloud-metadata IP must be refused, unfetched
    client = _StubClient({
        "http://1.1.1.1/start": _StubResp(302, {"location": "http://169.254.169.254/"}),
    })
    status, text = fetch_validated(client, "http://1.1.1.1/start")
    assert (status, text) == (None, "")
    assert "http://169.254.169.254/" not in client.requested  # never even streamed


def test_fetch_validated_blocks_unsafe_initial_url(monkeypatch):
    monkeypatch.setattr(ng, "JITTER", (0.0, 0.0))
    client = _StubClient({})                          # should never be called
    assert fetch_validated(client, "http://127.0.0.1/") == (None, "")
    assert client.requested == []
