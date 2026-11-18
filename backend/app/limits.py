"""
limits.py
Request-level resource protection for a 512 MB host:

  * AnalysisGate       -- bounds how many analyses run at once and how many may queue.
  * AdmissionControlMiddleware -- takes a gate slot BEFORE the body is read, so FastAPI's
                          multipart parsing (which spools every upload before the route runs)
                          is bounded in aggregate, not just per request.
  * BodySizeLimitMiddleware -- rejects oversized request bodies before they are buffered.
"""

import asyncio
import json
from typing import Optional

from .config import AnalysisLimits, load_analysis_limits


class ServerBusy(Exception):
    """Raised when the analysis queue is full or a queued request waited too long."""

    retry_after_seconds = 5


class AnalysisGate:
    """
    At most `max_concurrent` analyses run at once; up to `max_waiting` more may queue
    (for at most `wait_timeout_seconds`). Anything beyond that is rejected immediately,
    so memory held by buffered uploads stays bounded under load.
    """

    def __init__(self, limits: Optional[AnalysisLimits] = None):
        self.limits = limits or load_analysis_limits()
        self._semaphore = asyncio.Semaphore(self.limits.max_concurrent)
        self._in_system = 0  # running + waiting

    @property
    def capacity(self) -> int:
        return self.limits.max_concurrent + self.limits.max_waiting

    async def __aenter__(self):
        if self._in_system >= self.capacity:
            raise ServerBusy()
        self._in_system += 1
        # Not wait_for(acquire()): on a timeout/cancel race it can finish acquiring and still
        # raise, leaking a permit forever. Own the task so a late permit is always returned.
        task = asyncio.ensure_future(self._semaphore.acquire())
        try:
            done, _ = await asyncio.wait({task}, timeout=self.limits.wait_timeout_seconds)
        except BaseException:
            await self._abandon(task)
            self._in_system -= 1
            raise
        if task not in done:
            await self._abandon(task)
            self._in_system -= 1
            raise ServerBusy()
        return self

    async def _abandon(self, task: "asyncio.Future") -> None:
        task.cancel()
        try:
            await task
        except BaseException:
            pass
        if task.done() and not task.cancelled() and task.exception() is None:
            self._semaphore.release()  # the permit was granted just before the cancel landed

    async def __aexit__(self, exc_type, exc, tb):
        self._semaphore.release()
        self._in_system -= 1
        return False


_gate: Optional[AnalysisGate] = None


def get_gate() -> AnalysisGate:
    global _gate
    if _gate is None:
        _gate = AnalysisGate()
    return _gate


def reset_gate() -> None:
    global _gate
    _gate = None


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """
    Pure-ASGI middleware that returns 413 for request bodies over `max_bytes`.

    Checks Content-Length up front, and also counts bytes as they stream in, so a
    client that omits or lies about Content-Length cannot push an unbounded body
    through. Only applies to `path_prefix`. Install it *inside* CORSMiddleware so the
    413 carries CORS headers and the browser can show the message.
    """

    def __init__(self, app, max_bytes: int, path_prefix: str = "/api/"):
        self.app = app
        self.max_bytes = max_bytes
        self.path_prefix = path_prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(self.path_prefix):
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await self._reject(send)
                    return

        received = 0
        exceeded = False
        response_started = False

        async def counting_receive():
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    raise _BodyTooLarge()
            return message

        async def guarded_send(message):
            # FastAPI turns exceptions raised while parsing the body into a generic 400
            # before they can reach us, so once the limit is exceeded we replace whatever
            # response the app produces with our own 413 and drop the rest.
            nonlocal response_started
            if exceeded:
                if not response_started:
                    response_started = True
                    await self._reject(send)
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _BodyTooLarge:
            if not response_started:
                await self._reject(send)

    async def _reject(self, send):
        limit_mb = self.max_bytes / (1024 * 1024)
        body = json.dumps(
            {"detail": f"Request is too large (limit {limit_mb:.0f} MB). The resume PDF must be under 5 MB."}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class AdmissionControlMiddleware:
    """
    Pure-ASGI admission control for POST `path`. A gate slot is taken before the app is
    called -- i.e. before Starlette reads and spools the multipart body -- and held until the
    response is finished. Requests beyond capacity get an immediate 503 + Retry-After
    without their body being read. Install inside CORS (so the 503 carries CORS headers)
    and outside BodySizeLimitMiddleware.
    """

    def __init__(self, app, path: str = "/api/analyze"):
        self.app = app
        self.path = path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != self.path:
            await self.app(scope, receive, send)
            return
        try:
            async with get_gate():
                await self.app(scope, receive, send)
        except ServerBusy as busy:
            body = json.dumps(
                {"detail": "The server is busy analyzing other resumes. Please try again in a few seconds."}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"retry-after", str(busy.retry_after_seconds).encode()),
                        (b"connection", b"close"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
