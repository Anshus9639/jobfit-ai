"""
pdf_parser.py
Extract raw text from an uploaded PDF resume using PyMuPDF (fitz).

Memory safety: the parser rejects files that are not PDFs, are encrypted, have too
many pages, or yield an unreasonable amount of text, and always releases the
document (and PyMuPDF's internal cache) even when parsing fails.
"""

import threading
from typing import Optional

import fitz  # PyMuPDF
from fastapi import HTTPException

from .config import load_analysis_limits

_PDF_MAGIC = b"%PDF-"

# PyMuPDF/MuPDF is not thread-safe: its global context and object store are shared, and
# extraction runs in worker threads (asyncio.to_thread). Every use of the library, from
# open to close/store_shrink, happens under this lock. Cost: PDF parsing is serialized,
# which is fine because it is short and the analysis gate already bounds concurrency.
_PYMUPDF_LOCK = threading.Lock()


def extract_text_from_pdf(
    file_bytes: bytes,
    max_pages: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> str:
    """
    Extract plain text from PDF bytes.
    Raises HTTPException(400) if the file cannot be parsed, is too large to analyze,
    or contains no text.
    """
    limits = load_analysis_limits()
    max_pages = max_pages or limits.max_pdf_pages
    max_chars = max_chars or limits.max_resume_chars

    # Content-Type is client-controlled; check the file's own signature too. The PDF spec
    # allows leading bytes before the header, but only within the first 1024.
    if _PDF_MAGIC not in file_bytes[:1024]:
        raise HTTPException(status_code=400, detail="Resume must be a PDF file.")

    with _PYMUPDF_LOCK:
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Could not read PDF file. It may be corrupted.")

        try:
            if doc.needs_pass:
                raise HTTPException(
                    status_code=400,
                    detail="Password-protected PDFs are not supported. Please upload an unprotected copy.",
                )
            if doc.page_count > max_pages:
                raise HTTPException(
                    status_code=400,
                    detail=f"Resume PDF has too many pages ({doc.page_count}; max {max_pages}).",
                )

            text_parts = []
            total_chars = 0
            for page in doc:
                page_text = page.get_text()
                total_chars += len(page_text)
                if total_chars > max_chars:
                    raise HTTPException(
                        status_code=400,
                        detail="Resume PDF contains too much text to analyze.",
                    )
                text_parts.append(page_text)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Could not read PDF file. It may be corrupted.")
        finally:
            doc.close()
            fitz.TOOLS.store_shrink(100)  # drop PyMuPDF's internal object cache


    full_text = "\n".join(text_parts).strip()

    if not full_text:
        raise HTTPException(
            status_code=400,
            detail="No extractable text found in PDF. It may be a scanned/image-only resume.",
        )

    return full_text
