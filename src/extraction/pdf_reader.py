"""PDF reading utilities - text extraction and image conversion."""
import base64
import io
from pathlib import Path

import pdfplumber
from pdf2image import convert_from_path


def extract_text(pdf_path: Path) -> str:
    """
    Extract all text from a PDF. Returns empty string if PDF is image-only.
    """
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return "\n\n".join(text_parts).strip()


def is_text_pdf(pdf_path: Path, min_chars: int = 100) -> bool:
    """
    Quick heuristic: does this PDF have enough extractable text to use the text path?

    Scanned PDFs return very little (or only metadata cruft), which is the signal
    to fall back to vision.
    """
    text = extract_text(pdf_path)
    return len(text) >= min_chars


def pdf_pages_as_base64_images(
    pdf_path: Path, max_pages: int = 3, dpi: int = 150
) -> list[str]:
    """
    Convert PDF pages to base64-encoded PNGs for use with vision models.

    Most invoices are 1-2 pages. We cap at 3 to control cost.
    """
    images = convert_from_path(pdf_path, dpi=dpi, first_page=1, last_page=max_pages)

    encoded = []
    for img in images:
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        encoded.append(base64.standard_b64encode(buffer.getvalue()).decode("utf-8"))
    return encoded
