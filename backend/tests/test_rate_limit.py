"""Per-client and global rate limits protect the shared embedding-provider quota."""

import pytest

from app import ratelimit
from app.config import RateLimitSettings
from app.main import app
from app.ratelimit import RateLimitExceeded, SlidingWindowLimiter, client_key

from conftest import FakeProvider, analyze_request, install_provider, make_pdf, read_fixture, run_with_app

PDF = make_pdf([read_fixture("strong_resume.txt")])


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def limiter(per_client=2, global_limit=0, window=60.0, clock=None):
    return SlidingWindowLimiter(RateLimitSettings(per_client, global_limit, window, 1), clock=clock or Clock())


# --- limiter unit tests ---------------------------------------------------------------

def test_per_client_limit_and_window_expiry():
    clock = Clock()
    lim = limiter(per_client=2, clock=clock)
    lim.check("a"); lim.check("a")
    with pytest.raises(RateLimitExceeded) as info:
        lim.check("a")
    assert info.value.scope == "client" and info.value.retry_after == pytest.approx(60)
    lim.check("b")  # other clients unaffected
    clock.now += 61
    lim.check("a")  # window slid


def test_global_limit_applies_across_clients_and_reports_scope():
    lim = limiter(per_client=0, global_limit=3)
    for key in "abc":
        lim.check(key)
    with pytest.raises(RateLimitExceeded) as info:
        lim.check("d")
    assert info.value.scope == "global"


def test_rejected_check_consumes_nothing():
    lim = limiter(per_client=1, global_limit=2)
    lim.check("a")
    for _ in range(5):
        with pytest.raises(RateLimitExceeded):
            lim.check("a")  # per-client rejection must not burn global allowance
    lim.check("b")  # global still has one left


def test_zero_disables_limits():
    lim = limiter(per_client=0, global_limit=0)
    for _ in range(1000):
        lim.check("a")


def test_tracked_clients_are_bounded(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_TRACKED_CLIENTS", 3)
    lim = limiter(per_client=1)
    for key in "abc":
        lim.check(key)
    lim.check("d")  # table full: lands in the shared overflow bucket
    with pytest.raises(RateLimitExceeded):
        lim.check("e")
    assert len(lim._clients) <= 4


def test_expired_clients_are_evicted_when_table_is_full(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_TRACKED_CLIENTS", 2)
    clock = Clock()
    lim = limiter(per_client=1, clock=clock)
    lim.check("a"); lim.check("b")
    clock.now += 100
    lim.check("c")
    assert "c" in lim._clients and "__overflow__" not in lim._clients


# --- client key derivation ------------------------------------------------------------

def test_xff_uses_nth_entry_from_the_right_so_spoofing_does_not_help():
    assert client_key("6.6.6.6, 198.51.100.7", "10.0.0.1", 1) == "198.51.100.7"
    assert client_key("6.6.6.6, 198.51.100.7, 10.9.9.9", "10.0.0.1", 2) == "198.51.100.7"


def test_xff_ignored_without_trusted_proxy_or_when_malformed():
    assert client_key("1.2.3.4", "10.0.0.1", 0) == "10.0.0.1"
    assert client_key(None, "10.0.0.1", 1) == "10.0.0.1"
    assert client_key("not-an-ip", "10.0.0.1", 1) == "10.0.0.1"
    assert client_key("1.2.3.4", "10.0.0.1", 3) == "10.0.0.1"  # fewer hops than trusted
    assert client_key(None, None, 1) == "unknown"


def test_ipv6_clients_group_by_slash_64():
    a = client_key("2001:db8:1:2::1", None, 1)
    b = client_key("2001:db8:1:2:ffff::9", None, 1)
    c = client_key("2001:db8:1:3::1", None, 1)
    assert a == b != c


# --- through the API -------------------------------------------------------------------

def post(headers=None):
    return run_with_app(app, analyze_request(app, PDF, headers=headers))


def test_per_client_429_with_retry_after_and_no_provider_call(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_CLIENT", "2")
    provider = FakeProvider()
    install_provider(provider)
    h = {"x-forwarded-for": "198.51.100.1"}
    assert [post(h).status_code for _ in range(2)] == [200, 200]
    response = post(h)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1
    assert list(response.json()) == ["detail"]
    assert provider.calls == 2, "a limited request must not reach the provider"
    assert post({"x-forwarded-for": "198.51.100.2"}).status_code == 200


def test_global_limit_returns_503_across_distinct_clients(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_GLOBAL", "2")
    provider = FakeProvider()
    install_provider(provider)
    assert post({"x-forwarded-for": "198.51.100.1"}).status_code == 200
    assert post({"x-forwarded-for": "198.51.100.2"}).status_code == 200
    response = post({"x-forwarded-for": "198.51.100.3"})
    assert response.status_code == 503 and response.headers["retry-after"]
    assert provider.calls == 2


def test_invalid_uploads_do_not_consume_allowance(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_CLIENT", "1")
    provider = FakeProvider()
    install_provider(provider)
    h = {"x-forwarded-for": "198.51.100.1"}
    bad = run_with_app(app, analyze_request(app, b"not a pdf", headers=h))
    assert bad.status_code == 400
    assert post(h).status_code == 200  # the one allowed analysis is still available


def test_spoofed_leftmost_xff_cannot_evade_per_client_limit(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_CLIENT", "1")
    install_provider(FakeProvider())
    assert post({"x-forwarded-for": "1.1.1.1, 198.51.100.9"}).status_code == 200
    assert post({"x-forwarded-for": "2.2.2.2, 198.51.100.9"}).status_code == 429
