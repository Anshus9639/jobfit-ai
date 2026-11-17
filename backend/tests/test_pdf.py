import fitz
import pytest
from fastapi import HTTPException

from app import config
from app.pdf_parser import extract_text_from_pdf
from tests.conftest import RESUME_TEXT, make_pdf_bytes


def test_valid_pdf_text_is_extracted():
    text = extract_text_from_pdf(make_pdf_bytes())
    assert "Jane Doe" in text
    assert "Python" in text
    assert "Education" in text


def test_empty_bytes_are_rejected():
    with pytest.raises(HTTPException) as exc_info:
        extract_text_from_pdf(b"")
    assert exc_info.value.status_code == 400
    assert "could not read pdf" in exc_info.value.detail.lower()


def test_corrupt_pdf_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        extract_text_from_pdf(b"this is definitely not a pdf")
    assert exc_info.value.status_code == 400


def test_scanned_pdf_without_text_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        extract_text_from_pdf(make_pdf_bytes(text=""))
    assert exc_info.value.status_code == 400
    assert "no extractable text" in exc_info.value.detail.lower()


def test_page_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(config.settings, "max_pdf_pages", 2)
    with pytest.raises(HTTPException) as exc_info:
        extract_text_from_pdf(make_pdf_bytes(pages=3))
    assert exc_info.value.status_code == 400
    assert "too many pages" in exc_info.value.detail.lower()


def test_extracted_text_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(config.settings, "max_resume_text_chars", 10)
    with pytest.raises(HTTPException) as exc_info:
        extract_text_from_pdf(make_pdf_bytes(text=RESUME_TEXT))
    assert exc_info.value.status_code == 400
    assert "too long" in exc_info.value.detail.lower()


def test_encrypted_pdf_is_rejected():
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), "confidential resume")
        encrypted = doc.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )
    finally:
        doc.close()

    with pytest.raises(HTTPException) as exc_info:
        extract_text_from_pdf(encrypted)
    assert exc_info.value.status_code == 400
    assert "password" in exc_info.value.detail.lower()
