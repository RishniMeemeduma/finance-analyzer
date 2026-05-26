"""
Run extraction on every pending document in the database.

Idempotent: skips documents already in success/skipped state.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.db import get_session
from src.storage.repository import (
    create_invoice,
    get_pending_documents,
    mark_extraction_failed,
    mark_extraction_skipped,
    count_documents_by_status,
)
from src.extraction.extractor import extract_invoice_from_pdf


MAX_DOCUMENTS = 50
DELAY_BETWEEN_CALLS = 0.5


def main():
    print("Starting batch extraction...\n")
    print(f"Status before run:")
    with get_session() as session:
        for status, count in count_documents_by_status(session).items():
            print(f"  {status}: {count}")
    print()

    processed = 0
    succeeded = 0
    failed = 0
    skipped = 0

    while processed < MAX_DOCUMENTS:
        with get_session() as session:
            docs = get_pending_documents(session, limit=5)
            if not docs:
                break

            for doc in docs:
                pdf_path = Path(doc.file_path)
                if not pdf_path.exists():
                    mark_extraction_failed(
                        session, doc, f"File missing: {doc.file_path}"
                    )
                    failed += 1
                    processed += 1
                    continue

                print(f"[{processed + 1}] {doc.original_filename[:60]}")
                result = extract_invoice_from_pdf(pdf_path, force_vision=True)
                processed += 1

                if not result.success:
                    print(f"     FAILED: {result.error}")
                    mark_extraction_failed(session, doc, result.error or "unknown")
                    failed += 1
                    continue

                data = result.data
                if not data.is_invoice:
                    print(f"     SKIPPED: not an invoice")
                    mark_extraction_skipped(
                        session, doc, "Model classified as not an invoice"
                    )
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
                    f"     OK: {data.issuer_name} | {data.total_amount} {data.currency} | "
                    f"{data.category} | dir={data.direction} | path={result.path_used}"
                )
                succeeded += 1

                if processed >= MAX_DOCUMENTS:
                    break

                time.sleep(DELAY_BETWEEN_CALLS)

    print(f"\nDone. Processed: {processed}, succeeded: {succeeded}, failed: {failed}, skipped: {skipped}")

    print(f"\nStatus after run:")
    with get_session() as session:
        for status, count in count_documents_by_status(session).items():
            print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
