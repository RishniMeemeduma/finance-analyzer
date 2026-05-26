"""Pydantic models for invoice extraction. Used as both the LLM tool schema and validator."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# Categories we want to constrain the LLM to. Adjust this list to your business.
InvoiceCategory = Literal[
    "cloud_infrastructure",  # AWS, GCP, Azure, DigitalOcean, Hetzner
    "software_saas",         # Notion, Linear, GitHub, Figma
    "professional_services", # Lawyers, accountants, consultants
    "marketing_advertising", # Ads, marketing tools
    "office_supplies",
    "telecommunications",
    "travel",
    "training_education",
    "hardware",
    "tax_government",
    "freelancer_contractor",
    "other",
]


class LineItemExtraction(BaseModel):
    """A single line in an invoice."""
    description: str = Field(description="The text of the line item as it appears on the invoice")
    quantity: Decimal | None = Field(default=None, description="Quantity if specified, else null")
    unit_price: Decimal | None = Field(default=None, description="Unit price if specified, else null")
    amount: Decimal = Field(description="Line total amount")


class InvoiceExtraction(BaseModel):
    """The full structured output we want from the LLM for a single invoice."""

    is_invoice: bool = Field(
        description=(
            "True if this document is an invoice, receipt, or bill (something with a vendor charging an amount). "
            "False if it's something else (a contract, brochure, statement, marketing email, etc)."
        )
    )

    document_type: Literal["invoice", "receipt", "credit_note", "other"] | None = Field(
        default=None,
        description="If is_invoice is true, what kind of document is it?",
    )

    vendor_name: str | None = Field(
        default=None,
        description="The company or person issuing the invoice. Use the most complete legal name shown.",
    )
    vendor_vat_id: str | None = Field(
        default=None,
        description="VAT / tax ID of the vendor if present. Include the country prefix if shown (e.g. 'IT12345678901').",
    )

    invoice_number: str | None = Field(
        default=None,
        description="Invoice number or reference. Keep the original formatting.",
    )
    invoice_date: date | None = Field(
        default=None,
        description="Invoice issue date, ISO format (YYYY-MM-DD).",
    )
    due_date: date | None = Field(
        default=None, description="Due date if shown, ISO format."
    )

    currency: str = Field(
        default="EUR",
        description="3-letter ISO currency code (EUR, USD, GBP, etc). If unclear, default to EUR.",
    )
    subtotal: Decimal | None = Field(
        default=None, description="Subtotal before tax, if shown."
    )
    tax_amount: Decimal | None = Field(
        default=None, description="Total tax / VAT amount, if shown."
    )
    total_amount: Decimal | None = Field(
        default=None,
        description="Grand total. This is the amount actually owed/paid. Required if is_invoice is true.",
    )

    category: InvoiceCategory | None = Field(
        default=None,
        description="Best-fit category for this expense.",
    )
    is_recurring: bool = Field(
        default=False,
        description="True if the invoice description suggests a recurring subscription (monthly/yearly billing).",
    )

    line_items: list[LineItemExtraction] = Field(
        default_factory=list,
        description="Itemized lines. Empty list if no line items are present.",
    )

    extraction_notes: str | None = Field(
        default=None,
        description=(
            "Optional notes about ambiguity or things you weren't sure about. "
            "Leave empty if extraction was clean."
        ),
    )

    # ------------------------------------------------------------------
    # Validators - semantic checks beyond shape
    # ------------------------------------------------------------------

    @field_validator("currency")
    @classmethod
    def currency_uppercase(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def check_invoice_required_fields(self):
        """If it's an invoice, total_amount is required."""
        if self.is_invoice and self.total_amount is None:
            raise ValueError("total_amount is required when is_invoice=True")
        if self.is_invoice and not self.vendor_name:
            raise ValueError("vendor_name is required when is_invoice=True")
        return self

    @model_validator(mode="after")
    def check_amounts_consistent(self):
        """
        If we have subtotal + tax + total, they should roughly add up.
        Allow 1% or 0.02 currency unit tolerance for rounding.
        """
        if (
            self.subtotal is not None
            and self.tax_amount is not None
            and self.total_amount is not None
        ):
            expected = self.subtotal + self.tax_amount
            diff = abs(expected - self.total_amount)
            tolerance = max(Decimal("0.02"), self.total_amount * Decimal("0.01"))
            if diff > tolerance:
                # Don't reject - this happens with weird rounding or fees.
                # Just append a note.
                note = (
                    f"Amount mismatch: subtotal({self.subtotal}) + tax({self.tax_amount}) "
                    f"= {expected}, but total = {self.total_amount} (diff {diff})"
                )
                if self.extraction_notes:
                    self.extraction_notes = f"{self.extraction_notes}; {note}"
                else:
                    self.extraction_notes = note
        return self
