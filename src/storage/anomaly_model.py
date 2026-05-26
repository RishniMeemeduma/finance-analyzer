"""Anomaly findings model. Separate file so migrations stay clean."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.models import Base, Invoice


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=True,  # nullable for vendor-level anomalies
    )

    rule: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)  # LLM-generated
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    invoice: Mapped[Invoice | None] = relationship()

    def __repr__(self):
        return f"<Anomaly {self.rule} ({self.severity}): {self.message[:50]}>"
