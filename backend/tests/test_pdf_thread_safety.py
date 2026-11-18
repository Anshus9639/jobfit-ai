"""PyMuPDF is not thread-safe: all use of it is serialized behind a module lock."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from app import pdf_parser

from conftest import make_pdf


def test_pymupdf_calls_never_overlap_across_threads(monkeypatch):
    state = {"active": 0, "peak": 0}
    guard = threading.Lock()
    real_open, real_shrink = pdf_parser.fitz.open, pdf_parser.fitz.TOOLS.store_shrink

    def tracked(fn):
        def wrapper(*a, **k):
            with guard:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            try:
                time.sleep(0.01)  # widen the race window
                return fn(*a, **k)
            finally:
                with guard:
                    state["active"] -= 1
        return wrapper

    monkeypatch.setattr(pdf_parser.fitz, "open", tracked(real_open))
    monkeypatch.setattr(pdf_parser.fitz.TOOLS, "store_shrink", tracked(real_shrink), raising=False)
    pdfs = [make_pdf([f"Resume number {i} Python FastAPI"]) for i in range(16)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        texts = list(pool.map(pdf_parser.extract_text_from_pdf, pdfs))
    assert state["peak"] == 1
    assert all(f"Resume number {i}" in t for i, t in enumerate(texts))


def test_lock_is_held_for_the_whole_open_to_close_span(monkeypatch):
    pdf = make_pdf(["hello world"])  # built before spying: make_pdf itself uses fitz.open
    seen = []
    real_open = pdf_parser.fitz.open

    def spy(*a, **k):
        seen.append(pdf_parser._PYMUPDF_LOCK.locked())
        return real_open(*a, **k)

    monkeypatch.setattr(pdf_parser.fitz, "open", spy)
    real_shrink = pdf_parser.fitz.TOOLS.store_shrink
    monkeypatch.setattr(
        pdf_parser.fitz.TOOLS, "store_shrink",
        lambda n: (seen.append(pdf_parser._PYMUPDF_LOCK.locked()), real_shrink(n))[1], raising=False,
    )
    pdf_parser.extract_text_from_pdf(pdf)
    assert seen == [True, True]
    assert not pdf_parser._PYMUPDF_LOCK.locked()


def test_lock_is_released_after_failures():
    for bad in (b"%PDF-1.4 garbage", make_pdf(["x"], encrypt=True)):
        with pytest.raises(HTTPException):
            pdf_parser.extract_text_from_pdf(bad)
        assert not pdf_parser._PYMUPDF_LOCK.locked()


def test_parser_errors_do_not_echo_library_messages():
    with pytest.raises(HTTPException) as info:
        pdf_parser.extract_text_from_pdf(b"%PDF-1.4 definitely not a real pdf")
    assert info.value.detail == "Could not read PDF file. It may be corrupted."
