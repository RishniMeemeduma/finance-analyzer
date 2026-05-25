"""Database operations. All DB access goes through this module."""
import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Sequence
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session, selectinload

from src.storage.models import Document, Invoice, LineItem


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def compute_file_hash(file_path: Path) -> str:
    """SHA-256 of file contents. Used for dedup."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_document_by_hash(session: Session, content_hash: str) -> Document | None:
    """Find an existing document by its content hash (used for dedup)."""
    stmt = select(Document).where(Document.content_hash == content_hash)
    return session.scalar(stmt)


def create_document(
    session: Session,
    *,
    source_type: str,
    source_id: str,
    file_path: Path,
    original_filename: str,
    mime_type: str = "application/pdf",
    source_metadata: dict | None = None,
) -> Document:
    """
    Register a document in the database. Returns existing record if hash matches.
    """
    content_hash = compute_file_hash(file_path)

    # Dedup check
    existing = get_document_by_hash(session, content_hash)
    if existing:
        return existing

    doc = Document(
        source_type=source_type,
        source_id=source_id,
        file_path=str(file_path),
        content_hash=content_hash,
        original_filename=original_filename,
        file_size_bytes=file_path.stat().st_size,
        mime_type=mime_type,
        source_metadata=source_metadata or {},
    )
    session.add(doc)
    session.flush()  # assigns the id without committing
    return doc


def get_pending_documents(session: Session, limit: int = 100) -> Sequence[Document]:
    """Documents that haven't been extracted yet."""
    stmt = (
        select(Document)
        .where(Document.extraction_status == "pending")
        .order_by(Document.ingested_at)
        .limit(limit)
    )
    return session.scalars(stmt).all()


def mark_extraction_failed(session: Session, document: Document, error: str) -> None:
    document.extraction_status = "failed"
    document.extraction_error = error


def mark_extraction_skipped(session: Session, document: Document, reason: str) -> None:
    document.extraction_status = "skipped"
    document.extraction_error = reason


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

def normalize_vendor_name(name: str) -> str:
    """Lowercased, trimmed, no double spaces. For matching only."""
    return " ".join(name.lower().split())


def create_invoice(
    session: Session,
    *,
    document: Document,
    vendor_name: str,
    total_amount: Decimal,
    raw_extraction: dict,
    extracted_by_model: str,
    invoice_number: str | None = None,
    invoice_date: date | None = None,
    due_date: date | None = None,
    currency: str = "EUR",
    subtotal: Decimal | None = None,
    tax_amount: Decimal | None = None,
    vendor_vat_id: str | None = None,
    category: str | None = None,
    is_recurring: bool = False,
    line_items: list[dict] | None = None,
) -> Invoice:
    """Create an invoice and its line items."""
    invoice = Invoice(
        document_id=document.id,
        vendor_name=vendor_name,
        vendor_name_normalized=normalize_vendor_name(vendor_name),
        vendor_vat_id=vendor_vat_id,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        currency=currency,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total_amount=total_amount,
        category=category,
        is_recurring=is_recurring,
        raw_extraction=raw_extraction,
        extracted_by_model=extracted_by_model,
    )

    for i, item in enumerate(line_items or []):
        invoice.line_items.append(
            LineItem(
                description=item["description"],
                quantity=item.get("quantity"),
                unit_price=item.get("unit_price"),
                amount=item["amount"],
                position=i,
            )
        )

    session.add(invoice)
    document.extraction_status = "success"
    document.extraction_error = None
    session.flush()
    return invoice


def search_invoices(
    session: Session,
    *,
    vendor: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    limit: int = 100,
) -> Sequence[Invoice]:
    """Structured invoice search. All filters AND together."""
    stmt = select(Invoice).options(selectinload(Invoice.line_items))

    conditions = []
    if vendor:
        conditions.append(
            Invoice.vendor_name_normalized.contains(normalize_vendor_name(vendor))
        )
    if date_from:
        conditions.append(Invoice.invoice_date >= date_from)
    if date_to:
        conditions.append(Invoice.invoice_date <= date_to)
    if category:
        conditions.append(Invoice.category == category)
    if min_amount is not None:
        conditions.append(Invoice.total_amount >= min_amount)
    if max_amount is not None:
        conditions.append(Invoice.total_amount <= max_amount)

    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(Invoice.invoice_date.desc().nulls_last()).limit(limit)
    return session.scalars(stmt).all()


def get_invoice_by_id(session: Session, invoice_id: UUID) -> Invoice | None:
    stmt = (
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .options(selectinload(Invoice.line_items))
    )
    return session.scalar(stmt)


def count_invoices(session: Session) -> int:
    return session.scalar(select(func.count(Invoice.id))) or 0


def count_documents_by_status(session: Session) -> dict[str, int]:
    stmt = select(Document.extraction_status, func.count(Document.id)).group_by(
        Document.extraction_status
    )
    return {status: count for status, count in session.execute(stmt).all()}
