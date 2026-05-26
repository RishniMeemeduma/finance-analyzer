"""Deterministic direction detection. Don't let the LLM guess this."""
from typing import Literal

from src.extraction.schema import InvoiceExtraction


# Your businesses. Edit this list as needed.
# VAT IDs should be uppercase, no spaces. Names should be lowercase substrings.
YOUR_BUSINESSES = [
    {
        "name": "INNOVAORBIT",
        "name_match": "innovaorbit",  # lowercase substring to match
        "vat_ids": [],  # add INNOVAORBIT's VAT ID if/when it has one
        "emails": ["innovaorbit1.0@gmail.com"],
    },
]


def _normalize_vat(vat: str | None) -> str:
    if not vat:
        return ""
    return vat.upper().replace(" ", "").replace("-", "")


def _name_matches(extracted_name: str | None, target: str) -> bool:
    if not extracted_name:
        return False
    return target in extracted_name.lower()


def determine_direction(
    extracted: InvoiceExtraction,
) -> tuple[Literal["incoming", "outgoing", "unknown"], str]:
    """
    Determine direction by matching extracted fields against the user's known businesses.

    Returns (direction, reason).
    """
    issuer_vat = _normalize_vat(extracted.issuer_vat_id)
    counterparty_vat = _normalize_vat(extracted.counterparty_vat_id)

    for biz in YOUR_BUSINESSES:
        biz_vats = {_normalize_vat(v) for v in biz["vat_ids"] if v}
        name_target = biz["name_match"]

        # Strongest signal: VAT ID match
        if issuer_vat and issuer_vat in biz_vats:
            return "outgoing", f"Issuer VAT matches {biz['name']}"
        if counterparty_vat and counterparty_vat in biz_vats:
            return "incoming", f"Counterparty VAT matches {biz['name']}"

        # Fallback: name match
        if _name_matches(extracted.issuer_name, name_target):
            return "outgoing", f"Issuer name contains '{biz['name']}'"
        if _name_matches(extracted.counterparty_name, name_target):
            return "incoming", f"Counterparty name contains '{biz['name']}'"

    return "unknown", "No match against known businesses"


def correct_direction(extracted: InvoiceExtraction) -> InvoiceExtraction:
    """
    Override the LLM's direction with our deterministic answer.

    Also swaps issuer/counterparty if the LLM got them backwards.
    """
    direction, reason = determine_direction(extracted)

    # Detect a swap: LLM said outgoing but our logic says it's actually incoming
    # (or vice versa). This catches the case where issuer and counterparty are swapped.
    swapped = False
    if direction != "unknown" and extracted.direction and direction != extracted.direction:
        # The LLM put the names in the wrong slots. Swap them.
        extracted.issuer_name, extracted.counterparty_name = (
            extracted.counterparty_name,
            extracted.issuer_name,
        )
        extracted.issuer_vat_id, extracted.counterparty_vat_id = (
            extracted.counterparty_vat_id,
            extracted.issuer_vat_id,
        )
        swapped = True

    extracted.direction = direction if direction != "unknown" else extracted.direction

    note = f"[direction={direction}: {reason}"
    if swapped:
        note += "; swapped issuer/counterparty"
    note += "]"

    if extracted.extraction_notes:
        extracted.extraction_notes = f"{extracted.extraction_notes} {note}"
    else:
        extracted.extraction_notes = note

    return extracted
