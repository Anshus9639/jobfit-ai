"""
pdf_parser.py
Extract raw text from an uploaded PDF resume using PyMuPDF (fitz).
"""

import fitz  # PyMuPDF
from fastapi import HTTPException


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extract plain text from PDF bytes.
    Raises HTTPException(400) if the file cannot be parsed or contains no text.
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read PDF file: {exc}")

    text_parts = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()

    full_text = "\n".join(text_parts).strip()

    if not full_text:
        raise HTTPException(
            status_code=400,
            detail="No extractable text found in PDF. It may be a scanned/image-only resume.",
        )

    return full_text