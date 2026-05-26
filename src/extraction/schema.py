"""Pydantic models for invoice extraction."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


InvoiceCategory = Literal[
    "cloud_infrastructure",
    "software_saas",
    "professional_services",
    "marketing_advertising",
    "office_supplies",
    "telecommunications",
    "travel",
    "training_education",
    "hardware",
    "tax_government",
    "freelancer_contractor",
    "revenue",
    "other",
]


class LineItemExtraction(BaseModel):
    description: str = Field(description="The text of the line item")
    quantity: Decimal | None = Field(default=None)
    unit_price: Decimal | None = Field(default=None)
    amount: Decimal | None = Field(
        default=None,
        description="Line total amount. Null if not shown.",
    )


def _coerce_date(value):
    """
    Pydantic date validator that fixes common malformed dates instead of crashing.

    Handles: '31/04/2025' (impossible), placeholder strings, empty strings.
    Returns None if the date can't be salvaged.
    """
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return value

    # Reject placeholder text like {invoice_date}, {receipt_date}
    if value.startswith("{") and value.endswith("}"):
        return None
    if value in ("invoice_date", "due_date", "date"):
        return None

    # Try parsing ISO format with day clamping for impossible dates
    parts = value.split("-")
    if len(parts) == 3:
        try:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            # Clamp day to month maximum
            from calendar import monthrange
            max_day = monthrange(year, month)[1]
            day = min(day, max_day)
            return date(year, month, day)
        except (ValueError, IndexError):
            return None

    return value  # let Pydantic handle (and possibly reject) other formats


def _coerce_decimal(value):
    """Pydantic decimal validator that returns None for placeholder text."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float, Decimal)):
        return value
    if isinstance(value, str):
        # Reject placeholders like {total}, {subtotal}
        if value.startswith("{") and value.endswith("}"):
            return None
        # Reject obvious non-numeric strings
        if value in ("total", "subtotal", "amount", "rate", "date_range: hours"):
            return None
        # Strip currency symbols, commas
        cleaned = value.replace(",", "").replace("£", "").replace("$", "").replace("€", "").strip()
        if not cleaned:
            return None
        return cleaned
    return value


class InvoiceExtraction(BaseModel):
    is_invoice: bool

    document_type: Literal["invoice", "receipt", "credit_note", "other"] | None = Field(default=None)

    direction: Literal["incoming", "outgoing"] | None = Field(default=None)

    issuer_name: str | None = Field(default=None)
    issuer_vat_id: str | None = Field(default=None)
    counterparty_name: str | None = Field(default=None)
    counterparty_vat_id: str | None = Field(default=None)

    invoice_number: str | None = Field(default=None)
    invoice_date: date | None = Field(default=None)
    due_date: date | None = Field(default=None)

    currency: str = Field(default="EUR")
    subtotal: Decimal | None = Field(default=None)
    tax_amount: Decimal | None = Field(default=None)
    total_amount: Decimal | None = Field(default=None)

    category: InvoiceCategory | None = Field(default=None)
    is_recurring: bool = Field(default=False)

    line_items: list[LineItemExtraction] = Field(default_factory=list)
    extraction_notes: str | None = Field(default=None)
    needs_review: bool = Field(default=False)

    # Validators
    @field_validator("invoice_date", "due_date", mode="before")
    @classmethod
    def coerce_dates(cls, v):
        return _coerce_date(v)

    @field_validator("subtotal", "tax_amount", "total_amount", mode="before")
    @classmethod
    def coerce_amounts(cls, v):
        return _coerce_decimal(v)

    @field_validator("currency")
    @classmethod
    def currency_uppercase(cls, v: str) -> str:
        return v.upper() if v else "EUR"

    @model_validator(mode="after")
    def check_invoice_required_fields(self):
        if self.is_invoice and self.total_amount is None:
            raise ValueError("total_amount is required when is_invoice=True")
        if self.is_invoice and not self.issuer_name:
            raise ValueError("issuer_name is required when is_invoice=True")
        return self

    @model_validator(mode="after")
    def filter_invalid_line_items(self):
        """Drop line items that have no usable amount."""
        self.line_items = [li for li in self.line_items if li.amount is not None]
        return self

    @model_validator(mode="after")
    def check_amounts_consistent(self):
        if (
            self.subtotal is not None
            and self.tax_amount is not None
            and self.total_amount is not None
        ):
            expected = self.subtotal + self.tax_amount
            diff = abs(expected - self.total_amount)
            tolerance = max(Decimal("0.02"), self.total_amount * Decimal("0.01"))
            if diff > tolerance:
                note = (
                    f"Amount mismatch: subtotal({self.subtotal}) + tax({self.tax_amount}) "
                    f"= {expected}, but total = {self.total_amount} (diff {diff})"
                )
                self.extraction_notes = (
                    f"{self.extraction_notes}; {note}" if self.extraction_notes else note
                )
                self.needs_review = True
        return self
