"""PDF upload limits and safe handling."""

from app import embeddings
from app.config import MAX_PDF_SIZE_BYTES, MAX_REQUEST_BODY_BYTES
from app.main import app

from conftest import (
    FakeProvider, analyze_request, install_provider, make_blank_pdf, make_pdf, read_fixture, run_with_app,
)

RESUME = read_fixture("strong_resume.txt")


def post(pdf, **kwargs):
    if embeddings._client is None:  # tests that don't care about the provider get a working one
        install_provider(FakeProvider())
    return run_with_app(app, analyze_request(app, pdf, **kwargs))


def test_valid_pdf_is_accepted():
    provider = FakeProvider()
    install_provider(provider)
    response = post(make_pdf([RESUME]))
    assert response.status_code == 200 and provider.calls == 1


def test_body_over_limit_is_rejected_with_413_before_any_processing():
    provider = FakeProvider()
    install_provider(provider)
    response = post(b"%PDF-1.7\n" + b"0" * (MAX_REQUEST_BODY_BYTES + 1024))
    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()
    assert provider.calls == 0


def test_streamed_body_without_content_length_is_still_capped():
    """A client that omits Content-Length must not be able to stream unbounded data."""
    provider = FakeProvider()
    install_provider(provider)
    chunk = b"x" * 65536

    async def body_stream():
        yield b'--b\r\nContent-Disposition: form-data; name="job_description"\r\n\r\nhi\r\n'
        yield b'--b\r\nContent-Disposition: form-data; name="resume"; filename="r.pdf"\r\n'
        yield b"Content-Type: application/pdf\r\n\r\n%PDF-1.7\n"
        for _ in range((MAX_REQUEST_BODY_BYTES // len(chunk)) + 4):
            yield chunk

    async def run(client):
        return await client.post(
            "/api/analyze", content=body_stream(), headers={"content-type": "multipart/form-data; boundary=b"}
        )

    response = run_with_app(app, run)
    assert response.status_code == 413
    assert provider.calls == 0


def test_413_response_carries_cors_headers_so_the_browser_can_show_the_message():
    install_provider(FakeProvider())
    response = post(b"%PDF-" + b"0" * (MAX_REQUEST_BODY_BYTES + 10), headers={"Origin": "https://example.app"})
    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") == "*"


def test_pdf_just_over_5mb_but_under_body_limit_gets_the_original_400_message():
    provider = FakeProvider()
    install_provider(provider)
    response = post(b"%PDF-1.7\n" + b"0" * (MAX_PDF_SIZE_BYTES + 1))
    assert response.status_code == 400
    assert response.json()["detail"] == "Resume PDF exceeds 5 MB limit."
    assert provider.calls == 0


def test_non_pdf_content_type_rejected():
    response = post(make_pdf([RESUME]), content_type="text/plain")
    assert response.status_code == 400 and response.json()["detail"] == "Resume must be a PDF file."


def test_pdf_content_type_with_non_pdf_bytes_rejected():
    response = post(b"MZ\x90\x00 this is an executable, not a PDF")
    assert response.status_code == 400 and "PDF" in response.json()["detail"]


def test_empty_file_rejected():
    response = post(b"")
    assert response.status_code == 400 and response.json()["detail"] == "Uploaded resume file is empty."


def test_too_many_pages_rejected_before_extraction(monkeypatch):
    monkeypatch.setenv("MAX_PDF_PAGES", "3")
    provider = FakeProvider()
    install_provider(provider)
    response = post(make_pdf([RESUME] * 4))
    assert response.status_code == 400
    assert "too many pages" in response.json()["detail"]
    assert provider.calls == 0


def test_page_limit_boundary_is_inclusive(monkeypatch):
    monkeypatch.setenv("MAX_PDF_PAGES", "3")
    install_provider(FakeProvider())
    assert post(make_pdf([RESUME] * 3)).status_code == 200


def test_password_protected_pdf_rejected_with_clear_message():
    response = post(make_pdf([RESUME], encrypt=True))
    assert response.status_code == 400
    assert "password" in response.json()["detail"].lower()


def test_image_only_pdf_rejected_with_original_message():
    response = post(make_blank_pdf())
    assert response.status_code == 400
    assert response.json()["detail"].startswith("No extractable text found in PDF")


def test_excessive_extracted_text_rejected(monkeypatch):
    monkeypatch.setenv("MAX_RESUME_CHARS", "1000")
    provider = FakeProvider()
    install_provider(provider)
    response = post(make_pdf([RESUME]))
    assert response.status_code == 400 and "too much text" in response.json()["detail"]
    assert provider.calls == 0


def test_corrupt_pdf_rejected_without_crashing():
    response = post(b"%PDF-1.7\n1 0 obj\n<< /Broken garbage >>\n" * 5)
    assert response.status_code == 400


def test_oversized_job_description_and_empty_job_description_still_rejected():
    install_provider(FakeProvider())
    pdf = make_pdf([RESUME])
    assert post(pdf, jd="x" * 20001).status_code == 400
    assert post(pdf, jd="   ").status_code == 400
