"""
Measure process RSS for the backend, optionally including a local model load.

Usage (from backend/):
    python scripts/measure_memory.py
    python scripts/measure_memory.py --local

Requires psutil: pip install -r requirements-dev.txt
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def rss_mb() -> float:
    import psutil

    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--local",
        action="store_true",
        help="Also load the local SentenceTransformer (requires requirements-local.txt).",
    )
    args = parser.parse_args()

    baseline = rss_mb()
    print(f"baseline process RSS:        {baseline:7.1f} MB")

    from app.main import app  # noqa: F401  (imports the full web stack)

    print(f"after importing app.main:    {rss_mb():7.1f} MB (delta {rss_mb() - baseline:+.1f} MB)")

    if args.local:
        from app.config import settings
        from app.embeddings import LocalSentenceTransformerProvider

        provider = LocalSentenceTransformerProvider(settings.embeddings_model)
        asyncio.run(provider.embed(["resume text", "job description text"]))
        print(f"after local model inference: {rss_mb():7.1f} MB")


if __name__ == "__main__":
    main()
