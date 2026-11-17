"""
pdf_parser.py
Extract raw text from an uploaded PDF resume using PyMuPDF (fitz).

All allocations are bounded: the caller caps upload size, and this module caps
page count and extracted characters before running analysis.
"""

import fitz  # PyMuPDF
from fastapi import HTTPException

from . import config


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extract plain text from PDF bytes.
    Raises HTTPException(400) if the file cannot be parsed, is encrypted,
    exceeds the page/text limits, or contains no text.
    """
    settings = config.settings

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Could not read PDF file. It may be corrupted or not a valid PDF.",
        ) from exc

    try:
        if doc.needs_pass:
            raise HTTPException(
                status_code=400,
                detail="Password-protected PDFs are not supported. Please upload an unlocked PDF.",
            )
        if doc.page_count == 0:
            raise HTTPException(status_code=400, detail="The PDF contains no pages.")
        if doc.page_count > settings.max_pdf_pages:
            raise HTTPException(
                status_code=400,
                detail=f"PDF has too many pages (max {settings.max_pdf_pages}).",
            )

        text_parts = []
        total_chars = 0
        for page in doc:
            page_text = page.get_text()
            total_chars += len(page_text)
            if total_chars > settings.max_resume_text_chars:
                raise HTTPException(
                    status_code=400,
                    detail="Resume text is too long to analyze. Please upload a shorter resume.",
                )
            text_parts.append(page_text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Could not extract text from the PDF. It may be corrupted.",
        ) from exc
    finally:
        doc.close()

    full_text = "\n".join(text_parts).strip()

    if not full_text:
        raise HTTPException(
            status_code=400,
            detail="No extractable text found in PDF. It may be a scanned/image-only resume.",
        )

    return full_text
