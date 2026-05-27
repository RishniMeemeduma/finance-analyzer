"""
Ingest receipt-style emails that don't have PDF attachments.

Looks for emails from common receipt senders (Apple, PayPal, Medium, etc),
pulls the body, extracts as if it were an invoice.

Run from project root:
    python scripts/ingest_email_receipts.py
"""
import hashlib
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.gmail_client import GmailClient, extract_message_body, html_to_text
from src.storage.db import get_session
from src.storage.models import Document
from src.storage.repository import (
    create_invoice,
    mark_extraction_failed,
    mark_extraction_skipped,
)
from src.extraction.extractor import extract_invoice_from_text
from src.config import settings


# Tune this query for your senders. Gmail OR syntax: "{a b c}" means a OR b OR c.
# Add senders as you discover more. "-has:attachment" excludes ones we already got.
GMAIL_QUERY = (
    'newer_than:1y '
    '-has:attachment '
    '-from:me '
    '-from:innovaorbit1.0@gmail.com '
    '-from:ashameemeduma@gmail.com '
    '-from:revolvspace.com '
    '('
    'from:no_reply@email.apple.com '
    'OR from:service@paypal.com '
    'OR from:noreply@medium.com '
    'OR from:billing@medium.com '
    'OR from:noreply@notify.cloudflare.com '
    'OR from:invoices@vercel.com '
    'OR from:no-reply@spotify.com '
    'OR from:info@account.netflix.com '
    'OR (subject:"your receipt" -from:me)'
    ')'
)
MAX_MESSAGES = 100


def _save_body_as_synthetic_file(message_id: str, body_text: str) -> Path:
    """Save the email body to disk so we have a 'source file' on record."""
    save_dir = settings.data_dir / "raw_emails"
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / f"email_{message_id}.txt"
    path.write_text(body_text, encoding="utf-8")
    return path


def _content_hash_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    print(f"Connecting to Gmail...")
    client = GmailClient()

    print(f"Searching: {GMAIL_QUERY!r}\n")
    messages = client.search_messages(GMAIL_QUERY, max_results=MAX_MESSAGES)
    print(f"Found {len(messages)} candidate messages\n")

    succeeded = 0
    failed = 0
    skipped = 0
    deduped = 0

    for i, msg_ref in enumerate(messages, 1):
        message_id = msg_ref["id"]
        message = client.get_message(message_id)
        headers = client.get_headers(message)
        sender = headers.get("From", "(unknown)")
        subject = headers.get("Subject", "(no subject)")

        print(f"[{i}/{len(messages)}] {sender[:50]} | {subject[:60]}")

        plaintext, html = extract_message_body(message)
        body = plaintext if plaintext.strip() else html_to_text(html)
        if not body.strip():
            print("       SKIP: no body extracted")
            skipped += 1
            continue

        # Dedup by content hash of the body
        content_hash = _content_hash_of_text(body)

        with get_session() as session:
            existing = (
                session.query(Document).filter_by(content_hash=content_hash).first()
            )
            if existing:
                print("       SKIP: already ingested")
                deduped += 1
                continue

            # Save the body to disk
            file_path = _save_body_as_synthetic_file(message_id, body)

            # Create the Document row by hand (the repository's create_document
            # assumes a real file with .stat() so we replicate it inline)
            doc = Document(
                source_type="gmail",
                source_id=message_id,
                file_path=str(file_path),
                content_hash=content_hash,
                original_filename=f"{subject[:80]}.txt",
                file_size_bytes=len(body.encode("utf-8")),
                mime_type="text/plain",
                source_metadata={
                    "from": sender,
                    "subject": subject,
                    "date": headers.get("Date"),
                },
            )
            session.add(doc)
            session.flush()

            # Extract
            result = extract_invoice_from_text(body, source_label=f"email:{sender}")

            if not result.success:
                mark_extraction_failed(session, doc, result.error or "unknown")
                print(f"       FAIL: {result.error}")
                failed += 1
                continue

            data = result.data
            if not data.is_invoice:
                mark_extraction_skipped(session, doc, "Not classified as invoice")
                print("       SKIP: not an invoice")
                skipped += 1
                continue

            create_invoice(
                session,
                document=doc,
                vendor_name=data.issuer_name,
                total_amount=data.total_amount,
                raw_extraction=result.raw_response,
                extracted_by_model=result.model,
                invoice_number=data.invoice_number,
                invoice_date=data.invoice_date,
                due_date=data.due_date,
                currency=data.currency,
                subtotal=data.subtotal,
                tax_amount=data.tax_amount,
                vendor_vat_id=data.issuer_vat_id,
                category=data.category,
                is_recurring=data.is_recurring,
                line_items=[
                    {
                        "description": li.description,
                        "quantity": li.quantity,
                        "unit_price": li.unit_price,
                        "amount": li.amount,
                    }
                    for li in data.line_items
                ],
            )
            print(
                f"       OK: {data.issuer_name} | {data.total_amount} {data.currency} "
                f"| {data.category}"
            )
            succeeded += 1

    print(
        f"\nDone. Succeeded: {succeeded}, failed: {failed}, "
        f"skipped: {skipped}, already-ingested: {deduped}"
    )


if __name__ == "__main__":
    main()
