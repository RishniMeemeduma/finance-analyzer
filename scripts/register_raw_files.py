"""
Scan data/raw/ and register every PDF as a Document.

This is a one-time backfill for files that were ingested before the DB existed.
Future ingestion scripts should write to the DB directly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
from src.storage.db import get_session
from src.storage.repository import create_document, count_documents_by_status


def infer_source(filename: str) -> tuple[str, str]:
    """
    Guess (source_type, source_id) from the filename.

    Gmail files are named: {gmail_message_id}__{original_name}
    Drive files are named: drive_{file_id_prefix}__{original_name}
    """
    if filename.startswith("drive_"):
        # drive_abc123__name.pdf
        rest = filename[len("drive_"):]
        prefix, _, _ = rest.partition("__")
        return "drive", prefix
    elif "__" in filename:
        prefix, _, _ = filename.partition("__")
        return "gmail", prefix
    else:
        return "unknown", ""


def main():
    raw_dir = settings.data_dir / "raw"
    pdfs = list(raw_dir.glob("*.pdf"))
    print(f"Found {len(pdfs)} PDFs in {raw_dir}")

    registered = 0
    deduped = 0

    with get_session() as session:
        for pdf_path in pdfs:
            source_type, source_id = infer_source(pdf_path.name)

            # Strip the prefix to get the "original" filename
            if "__" in pdf_path.name:
                original = pdf_path.name.split("__", 1)[1]
            else:
                original = pdf_path.name

            existing_count_before = session.query.__self__  # placeholder to detect dedup below

            doc = create_document(
                session,
                source_type=source_type,
                source_id=source_id,
                file_path=pdf_path,
                original_filename=original,
            )
            # If it was deduped, doc.id was already set (existing record)
            # We can tell by checking if it was just added (in session.new) or pre-existing
            if doc in session.new:
                registered += 1
            else:
                deduped += 1

        print(f"Registered: {registered} new documents")
        print(f"Skipped (duplicates): {deduped}")

    # Final summary
    with get_session() as session:
        counts = count_documents_by_status(session)
        print(f"\nDocument status counts:")
        for status, count in counts.items():
            print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
