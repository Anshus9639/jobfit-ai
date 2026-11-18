"""Bounded request concurrency: memory stays flat under bursts instead of growing per request."""

import asyncio

import httpx
import pytest

from app import limits
from app.config import AnalysisLimits
from app.limits import AnalysisGate, ServerBusy
from app.main import app

from conftest import (
    FakeProvider, analyze_request, hf_ok_response, install_provider, make_pdf, read_fixture,
)

PDF = make_pdf([read_fixture("strong_resume.txt")])


def burst(n):
    """Fire n simultaneous /api/analyze requests in one event loop."""
    async def main():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            send = analyze_request(app, PDF)
            return await asyncio.gather(*(send(client) for _ in range(n)))

    return asyncio.run(main())


def slow_provider(delay=0.3):
    async def handler(request):
        await asyncio.sleep(delay)
        return hf_ok_response(0.5)

    return FakeProvider(handler)


def test_concurrent_analyses_never_exceed_the_configured_limit(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "2")
    monkeypatch.setenv("MAX_WAITING_ANALYSES", "4")
    provider = slow_provider()
    install_provider(provider)

    responses = burst(12)

    codes = [r.status_code for r in responses]
    assert set(codes) <= {200, 503}
    assert provider.max_in_flight <= 2                 # never more than 2 analyses at once
    assert codes.count(200) >= 2                       # real work still gets done
    assert codes.count(503) >= 1                       # overflow is shed, not buffered forever
    assert codes.count(200) + codes.count(503) == 12   # nothing hangs or crashes


def test_overflow_is_rejected_immediately_with_retry_after(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_WAITING_ANALYSES", "0")
    install_provider(slow_provider(0.4))

    rejected = [r for r in burst(5) if r.status_code == 503]

    assert rejected, "with no queue, simultaneous requests beyond the first must be rejected"
    for r in rejected:
        assert r.headers["retry-after"] == "5"
        assert list(r.json()) == ["detail"] and "busy" in r.json()["detail"].lower()


def test_queued_request_that_waits_too_long_gets_503(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_WAITING_ANALYSES", "1")
    monkeypatch.setenv("ANALYSIS_WAIT_TIMEOUT_SECONDS", "1")
    install_provider(slow_provider(2.0))  # first request holds the slot for 2s; waiter gives up at 1s

    codes = sorted(r.status_code for r in burst(2))

    assert codes == [200, 503]


def test_slots_are_released_after_success_and_after_provider_failure(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_WAITING_ANALYSES", "8")
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500, text="boom") if calls["n"] <= 6 else hf_ok_response(0.5)

    install_provider(FakeProvider(handler), max_retries=0)

    async def main():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            send = analyze_request(app, PDF)
            failures = [await send(client) for _ in range(6)]   # provider errors inside the gate
            success = await send(client)                          # must not be starved by leaked slots
            return failures, success

    failures, success = asyncio.run(main())
    assert [r.status_code for r in failures] == [502] * 6
    assert success.status_code == 200
    assert limits.get_gate()._in_system == 0


def test_gate_counters_return_to_zero_after_a_burst(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "2")
    monkeypatch.setenv("MAX_WAITING_ANALYSES", "3")
    install_provider(slow_provider(0.1))
    burst(10)
    gate = limits.get_gate()
    assert gate._in_system == 0 and gate._semaphore._value == 2


def test_gate_unit_cancelled_waiter_does_not_leak_a_slot():
    async def main():
        gate = AnalysisGate(AnalysisLimits(1, 2, 30.0, 15, 150_000))
        async with gate:
            waiter = asyncio.create_task(gate.__aenter__())
            await asyncio.sleep(0.05)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert gate._in_system == 1  # only the running holder remains
        assert gate._in_system == 0
        async with gate:  # and the slot is usable again
            assert gate._in_system == 1

    asyncio.run(main())


def test_gate_unit_rejects_when_full():
    async def main():
        gate = AnalysisGate(AnalysisLimits(1, 1, 30.0, 15, 150_000))
        async with gate:
            waiter = asyncio.create_task(gate.__aenter__())
            await asyncio.sleep(0.05)
            with pytest.raises(ServerBusy):
                await gate.__aenter__()
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    asyncio.run(main())


def test_rejected_requests_never_load_their_upload_into_memory(monkeypatch):
    """Regression: uploads were once read into RAM *before* the gate, so a burst of N big
    uploads cost N x 5 MB even though most were rejected. Only admitted requests may read."""
    from starlette.datastructures import UploadFile

    reads = []
    original_read = UploadFile.read

    async def counting_read(self, size=-1):
        reads.append(size)
        return await original_read(self, size)

    monkeypatch.setattr(UploadFile, "read", counting_read)
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_WAITING_ANALYSES", "0")
    install_provider(slow_provider(0.4))

    responses = burst(8)

    admitted = sum(r.status_code == 200 for r in responses)
    rejected = sum(r.status_code == 503 for r in responses)
    assert rejected >= 1
    assert len(reads) == admitted  # rejected requests never touched their bytes


def test_oversized_and_empty_uploads_are_rejected_without_reading_bytes(monkeypatch):
    from starlette.datastructures import UploadFile

    reads = []
    original_read = UploadFile.read

    async def counting_read(self, size=-1):
        reads.append(size)
        return await original_read(self, size)

    monkeypatch.setattr(UploadFile, "read", counting_read)
    install_provider(FakeProvider())

    from app.config import MAX_PDF_SIZE_BYTES
    from conftest import run_with_app
    for payload in (b"", b"%PDF-1.7\n" + b"0" * (MAX_PDF_SIZE_BYTES + 1)):
        response = run_with_app(app, analyze_request(app, payload))
        assert response.status_code == 400
    assert reads == []
