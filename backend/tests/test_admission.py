"""Admission control runs BEFORE multipart parsing, so aggregate upload buffering is bounded."""

import asyncio

import httpx
import pytest

from app import limits
from app.config import AnalysisLimits
from app.limits import AnalysisGate, ServerBusy, get_gate
from app.main import app

from conftest import FakeProvider, analyze_request, hf_ok_response, install_provider, make_pdf, read_fixture

PDF = make_pdf([read_fixture("strong_resume.txt")])


def raw_post(application, receive_log):
    """Drive one POST through the raw ASGI interface and record whether the body was read."""
    sent = []

    async def receive():
        receive_log.append(1)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "method": "POST", "path": "/api/analyze", "raw_path": b"/api/analyze",
        "query_string": b"", "scheme": "http", "http_version": "1.1", "root_path": "",
        "server": ("test", 80), "client": ("203.0.113.9", 5000),
        "headers": [(b"content-type", b"multipart/form-data; boundary=x"), (b"content-length", b"100")],
    }

    async def run():
        await application(scope, receive, send)
        return sent

    return run


def test_overflow_request_is_rejected_before_its_body_is_read(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_WAITING_ANALYSES", "0")
    reads = []

    async def main():
        async with get_gate():  # the only slot is taken
            return await raw_post(app, reads)()

    sent = asyncio.run(main())
    start = sent[0]
    assert start["status"] == 503
    headers = dict(start["headers"])
    assert headers[b"retry-after"] == b"5" and headers[b"connection"] == b"close"
    assert reads == [], "body must not be read for a request that is not admitted"


def test_queued_request_that_times_out_never_reads_its_body(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_WAITING_ANALYSES", "5")
    monkeypatch.setenv("ANALYSIS_WAIT_TIMEOUT_SECONDS", "1")
    reads = []

    async def main():
        async with get_gate():
            return await raw_post(app, reads)()

    sent = asyncio.run(main())
    assert sent[0]["status"] == 503 and reads == []


def test_aggregate_parsed_uploads_never_exceed_the_slot_count(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "2")
    monkeypatch.setenv("MAX_WAITING_ANALYSES", "0")
    active = peak = 0

    async def handler(request):
        await asyncio.sleep(0.3)
        return hf_ok_response(0.5)

    install_provider(FakeProvider(handler))

    async def measuring_app(scope, receive, send):
        # Outermost wrapper: counts requests whose body has started to be consumed
        # (i.e. that were admitted) until their response is complete.
        nonlocal active, peak
        started = False

        async def counted_receive():
            nonlocal active, peak, started
            if not started:
                started = True
                active += 1
                peak = max(peak, active)
            return await receive()

        async def counted_send(message):
            nonlocal active
            if message["type"] == "http.response.body" and not message.get("more_body") and started:
                active -= 1
            await send(message)

        await app(scope, counted_receive, counted_send)

    async def main():
        transport = httpx.ASGITransport(app=measuring_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            send = analyze_request(app, PDF)
            return await asyncio.gather(*(send(client) for _ in range(8)))

    responses = asyncio.run(main())
    codes = [r.status_code for r in responses]
    assert peak <= 2
    assert codes.count(200) >= 2 and codes.count(503) >= 1
    assert all(r.headers.get("retry-after") for r in responses if r.status_code == 503)


def test_admission_only_applies_to_post_analyze(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_WAITING_ANALYSES", "0")

    async def main():
        async with get_gate():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return [(await client.get("/health")).status_code,
                        (await client.options("/api/analyze", headers={
                            "Origin": "http://x", "Access-Control-Request-Method": "POST"})).status_code]

    health, preflight = asyncio.run(main())
    assert health == 200 and preflight == 200


def test_busy_503_carries_cors_headers(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_WAITING_ANALYSES", "0")

    async def main():
        async with get_gate():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await analyze_request(app, PDF, headers={"Origin": "http://frontend.example"})(client)

    response = asyncio.run(main())
    assert response.status_code == 503
    assert "access-control-allow-origin" in response.headers


# --- permit accounting under cancel / timeout races -------------------------------------

def limits_for(wait=0.05, concurrent=1, waiting=2):
    return AnalysisLimits(concurrent, waiting, wait, 15, 150000)


def test_timed_out_waiter_leaks_no_permit():
    async def main():
        gate = AnalysisGate(limits_for(wait=0.05))
        async with gate:
            with pytest.raises(ServerBusy):
                async with gate:
                    pass
        assert gate._in_system == 0
        async with asyncio.timeout(1):
            async with gate:  # would hang if a permit had leaked
                pass

    asyncio.run(main())


def test_cancel_racing_with_release_does_not_leak_the_permit():
    async def main():
        gate = AnalysisGate(limits_for(wait=5))
        await gate.__aenter__()

        async def waiter():
            async with gate:
                pass

        task = asyncio.ensure_future(waiter())
        await asyncio.sleep(0.01)  # waiter is queued on the semaphore
        await gate.__aexit__(None, None, None)  # hands the permit to the waiter...
        task.cancel()  # ...and cancel lands in the same tick
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate._in_system == 0
        async with asyncio.timeout(1):
            async with gate:
                pass

    asyncio.run(main())
