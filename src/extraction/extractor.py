"""LLM-based invoice extraction. Uses Anthropic tool calling for structured output."""
import json
from pathlib import Path

import anthropic
from pydantic import ValidationError

from src.config import settings
from src.extraction.schema import InvoiceExtraction
from src.extraction.direction import correct_direction
from src.extraction.pdf_reader import (
    extract_text,
    is_text_pdf,
    pdf_pages_as_base64_images,
)


TEXT_MODEL = "claude-haiku-4-5-20251001"
VISION_MODEL = "claude-haiku-4-5-20251001"


SYSTEM_PROMPT = """\
You are an expert at extracting structured data from invoices and receipts.

You will be given the contents of a PDF document. Your job is to:
1. Decide whether it is an invoice/receipt/bill.
2. If yes, extract the structured data using the `extract_invoice` tool.
3. If no, still call the tool but set is_invoice=false.

CRITICAL: Identifying issuer vs counterparty (don't get this backwards)

The "issuer" is the party being PAID (who sent the invoice).
The "counterparty" is the party being BILLED (who has to pay).

Pay close attention to these explicit labels in the document text:
- "Customer VAT number" / "Customer:" / "Bill to:" / "Invoice to:" / "Sold to:" -> the entity here is the COUNTERPARTY (customer)
- "Vendor:" / "From:" / "Supplier:" / "Issued by:" -> the entity here is the ISSUER
- If you see "Customer VAT number: XXX" near a company name, that VAT belongs to the COUNTERPARTY
- The issuer's own info (name, address, VAT) usually appears WITHOUT a "Customer" label - it's standalone, often in the header or as a logo

Two-column layouts are common: one side is the issuer, the other is "Invoice to: <counterparty>".
When in doubt, follow the explicit labels in the document over positional cues.

The user's business is INNOVAORBIT. If you see INNOVAORBIT on a document:
- If INNOVAORBIT appears as the issuer (no "Customer" label nearby), the direction is "outgoing".
- If INNOVAORBIT appears under "Invoice to:", "Customer", "Bill to:", the direction is "incoming".

Other rules:
- Be conservative. If a field isn't clearly present, leave it null.
- Preserve invoice_number formatting (e.g. "INV-2025-0001", "000018").
- Dates in ISO format YYYY-MM-DD. If the document uses DD/MM/YYYY, convert it.
- Amounts: decimal numbers (1234.56), no currency symbols, no thousands separators.
- Currency: 3-letter ISO code (EUR, USD, GBP).
- Line items: every itemized row. Empty list if no itemization.
- Use extraction_notes for anything ambiguous.
- Set needs_review=true if you're not fully confident in the extraction (ambiguous labels, missing fields, layout that's hard to interpret, conflicting signals).
"""


def _build_tool_definition() -> dict:
    """Build the Anthropic tool definition from the Pydantic schema."""
    schema = InvoiceExtraction.model_json_schema()
    return {
        "name": "extract_invoice",
        "description": "Submit the extracted invoice data.",
        "input_schema": schema,
    }


class ExtractionResult:
    def __init__(
        self,
        *,
        success: bool,
        data: InvoiceExtraction | None = None,
        raw_response: dict | None = None,
        model: str,
        path_used: str,
        error: str | None = None,
    ):
        self.success = success
        self.data = data
        self.raw_response = raw_response or {}
        self.model = model
        self.path_used = path_used
        self.error = error


def _call_claude_text(client: anthropic.Anthropic, pdf_text: str) -> tuple[dict, str]:
    response = client.messages.create(
        model=TEXT_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[_build_tool_definition()],
        tool_choice={"type": "tool", "name": "extract_invoice"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Here is the text content of a PDF document. Extract the invoice data.\n\n"
                    "---BEGIN DOCUMENT---\n"
                    f"{pdf_text}\n"
                    "---END DOCUMENT---"
                ),
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_invoice":
            return block.input, TEXT_MODEL

    raise RuntimeError("Model did not call the extract_invoice tool.")


def _call_claude_vision(
    client: anthropic.Anthropic, page_images: list[str]
) -> tuple[dict, str]:
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img,
            },
        }
        for img in page_images
    ]
    content.append(
        {
            "type": "text",
            "text": "Extract the invoice data from these document images.",
        }
    )

    response = client.messages.create(
        model=VISION_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[_build_tool_definition()],
        tool_choice={"type": "tool", "name": "extract_invoice"},
        messages=[{"role": "user", "content": content}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_invoice":
            return block.input, VISION_MODEL

    raise RuntimeError("Model did not call the extract_invoice tool.")


def extract_invoice_from_pdf(pdf_path: Path, force_vision: bool = False) -> ExtractionResult:
    """
    Extract an invoice from a PDF file. Auto-selects text vs vision path.

    Pass force_vision=True to skip text extraction and go straight to vision.
    """
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        if not force_vision and is_text_pdf(pdf_path):
            pdf_text = extract_text(pdf_path)
            tool_input, model_used = _call_claude_text(client, pdf_text)
            path_used = "text"
        else:
            images = pdf_pages_as_base64_images(pdf_path)
            if not images:
                return ExtractionResult(
                    success=False,
                    model="none",
                    path_used="none",
                    error="PDF has no extractable text and no convertible images",
                )
            tool_input, model_used = _call_claude_vision(client, images)
            path_used = "vision"
    except anthropic.APIError as e:
        return ExtractionResult(
            success=False,
            model="error",
            path_used="error",
            error=f"Anthropic API error: {e}",
        )
    except Exception as e:
        return ExtractionResult(
            success=False,
            model="error",
            path_used="error",
            error=f"Extraction error: {type(e).__name__}: {e}",
        )

    try:
        validated = InvoiceExtraction.model_validate(tool_input)
    except ValidationError as e:
        return ExtractionResult(
            success=False,
            raw_response=tool_input,
            model=model_used,
            path_used=path_used,
            error=f"Validation failed: {e}",
        )

    # Override LLM direction with deterministic logic
    if validated.is_invoice:
        validated = correct_direction(validated)

    return ExtractionResult(
        success=True,
        data=validated,
        raw_response=tool_input,
        model=model_used,
        path_used=path_used,
    )
