"""SQLAlchemy ORM models. These define both the Python objects and the DB schema."""
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    String,
    DateTime,
    Date,
    Numeric,
    Boolean,
    Integer,
    ForeignKey,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """All models inherit from this."""
    pass


class Document(Base):
    """A file we've ingested. Not necessarily an invoice yet."""
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    extraction_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationship to invoice (one-to-one, may not exist)
    invoice: Mapped["Invoice | None"] = relationship(
        back_populates="document", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Document {self.original_filename} ({self.extraction_status})>"


class Invoice(Base):
    """A successfully extracted invoice."""
    __tablename__ = "invoices"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    vendor_name: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_name_normalized: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    vendor_vat_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    raw_extraction: Mapped[dict] = mapped_column(JSONB, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    extracted_by_model: Mapped[str] = mapped_column(String(50), nullable=False)

    document: Mapped[Document] = relationship(back_populates="invoice")
    line_items: Mapped[list["LineItem"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="LineItem.position",
    )

    def __repr__(self):
        return f"<Invoice {self.vendor_name} {self.invoice_number} {self.total_amount} {self.currency}>"


class LineItem(Base):
    """A single line in an invoice."""
    __tablename__ = "line_items"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="line_items")
