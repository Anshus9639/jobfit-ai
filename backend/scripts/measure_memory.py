#!/usr/bin/env python
"""
Measure the backend's real memory use under concurrent load -- no API key needed.

Starts the actual `uvicorn app.main:app` server plus a tiny local stand-in embedding
server (via EMBEDDING_API_URL), sends bursts of concurrent PDF analyses, and reports the
server process's RSS (idle, after load, and peak). Run from the backend directory:

    python scripts/measure_memory.py [--concurrency 30] [--waves 3]

The stand-in server exists only for this measurement; the app itself never fabricates
embeddings or scores.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import multiprocessing
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fitz
import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
DIM = 384


class _Server(ThreadingHTTPServer):
    request_queue_size = 256  # default of 5 refuses connections under bursts
    daemon_threads = True


class StandInEmbeddings(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["content-length"])))
        vectors = [[((hash(text) >> i) % 97 + 1) / 97 for i in range(DIM)] for text in payload["inputs"]]
        body = json.dumps(vectors).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve_standin(port_queue):
    httpd = _Server(("127.0.0.1", 0), StandInEmbeddings)
    port_queue.put(httpd.server_port)
    httpd.serve_forever()


def rss_mb(pid: int, key: str = "VmRSS") -> float:
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith(key + ":"):
                return int(line.split()[1]) / 1024
    except FileNotFoundError:
        pass
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout
    return int(out.strip() or 0) / 1024


def build_pdf(pages: int, pad_mb: float = 0.0) -> bytes:
    doc = fitz.open()
    for p in range(pages):
        page = doc.new_page()
        for i in range(70):
            page.insert_text((36, 40 + i * 10), f"Built REST APIs with Python and React, improved latency by {i}% (page {p})", fontsize=7)
    data = doc.tobytes()
    doc.close()
    if pad_mb:  # trailing bytes after %%EOF are ignored by PDF readers; used to simulate a large upload
        data += b"\n%" + b"0" * int(pad_mb * 1024 * 1024)
    return data


async def load(base_url: str, pdf: bytes, concurrency: int, waves: int, pid: int):
    jd = "Backend Developer\nRequirements:\n- Python, FastAPI, SQL, Docker, AWS\n- 2+ years of experience"
    codes, peak = {}, 0.0
    async with httpx.AsyncClient(base_url=base_url, timeout=120) as client:
        async def one():
            r = await client.post("/api/analyze", files={"resume": ("r.pdf", pdf, "application/pdf")}, data={"job_description": jd})
            codes[r.status_code] = codes.get(r.status_code, 0) + 1

        async def sampler():
            nonlocal peak
            while True:
                peak = max(peak, rss_mb(pid))
                await asyncio.sleep(0.02)

        sample_task = asyncio.create_task(sampler())
        for _ in range(waves):
            await asyncio.gather(*(one() for _ in range(concurrency)))
        sample_task.cancel()
    return codes, peak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=30)
    ap.add_argument("--waves", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=180.0, help="abort the load phase after this many seconds")
    ap.add_argument("--pages", type=int, default=2, help="pages in the test resume PDF")
    ap.add_argument("--pad-mb", type=float, default=0.0, help="pad the PDF to simulate a large upload (max 4.9)")
    args = ap.parse_args()

    # Separate process: the load generator below is CPU-heavy and would otherwise starve it.
    port_queue = multiprocessing.Queue()
    provider = multiprocessing.Process(target=_serve_standin, args=(port_queue,), daemon=True)
    provider.start()
    provider_port = port_queue.get(timeout=10)

    env = {
        **os.environ,
        "RATE_LIMIT_PER_CLIENT": "0",
        "RATE_LIMIT_GLOBAL": "0",
        "EMBEDDING_PROVIDER": "huggingface",
        "HF_TOKEN": "local-measurement-token",
        "EMBEDDING_API_URL": f"http://127.0.0.1:{provider_port}/embed",
    }
    port = 8765
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND_DIR, env=env,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        time.sleep(0.5)
        idle = rss_mb(server.pid)

        pdf = build_pdf(args.pages, args.pad_mb)
        codes, peak = asyncio.run(
            asyncio.wait_for(load(base, pdf, args.concurrency, args.waves, server.pid), timeout=args.timeout)
        )
        after = rss_mb(server.pid)
        hwm = max(peak, rss_mb(server.pid, "VmHWM"))

        print(f"resume PDF: {args.pages} page(s), {len(pdf) / 1024:.0f} KB; "
              f"{args.concurrency} concurrent x {args.waves} waves")
        print(f"responses:        {dict(sorted(codes.items()))}")
        print(f"idle RSS:         {idle:7.1f} MB")
        print(f"after-load RSS:   {after:7.1f} MB")
        print(f"peak RSS:         {hwm:7.1f} MB   (Render free limit: 512 MB)")
    finally:
        server.terminate()
        server.wait(timeout=10)
        provider.terminate()


if __name__ == "__main__":
    main()
