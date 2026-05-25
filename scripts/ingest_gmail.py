"""
Phase 1: Ingest PDF attachments from Gmail.

This script does NOT use AI. It just:
1. Searches Gmail for messages with PDF attachments
2. Downloads each PDF to data/raw/
3. Logs metadata (sender, subject, date, filename) to the console

Run from project root:
    python scripts/ingest_gmail.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.gmail_client import GmailClient, save_pdf
from src.config import settings


# Configure your search here. Gmail query syntax:
# https://support.google.com/mail/answer/7190
GMAIL_QUERY = "has:attachment filename:pdf newer_than:90d"
MAX_MESSAGES = 30  # Start small for testing


def main():
    print(f"Connecting to Gmail...")
    client = GmailClient()

    print(f"Searching for: {GMAIL_QUERY!r}")
    messages = client.search_messages(GMAIL_QUERY, max_results=MAX_MESSAGES)
    print(f"Found {len(messages)} messages\n")

    save_dir = settings.data_dir / "raw"
    total_pdfs = 0

    for i, msg_ref in enumerate(messages, 1):
        message_id = msg_ref["id"]
        message = client.get_message(message_id)
        headers = client.get_headers(message)

        sender = headers.get("From", "(unknown sender)")
        subject = headers.get("Subject", "(no subject)")
        date = headers.get("Date", "(no date)")

        # Truncate for readable output
        print(f"[{i}/{len(messages)}] {date[:25]} | {sender[:40]}")
        print(f"       Subject: {subject[:70]}")

        pdf_count_for_message = 0
        for filename, content in client.iter_pdf_attachments(message):
            output_path = save_pdf(content, filename, message_id, save_dir)
            size_kb = len(content) / 1024
            print(f"       PDF: {filename} ({size_kb:.1f} KB) -> {output_path.name}")
            pdf_count_for_message += 1
            total_pdfs += 1

        if pdf_count_for_message == 0:
            print(f"       (no PDFs extracted - might be inline or wrong mime type)")
        print()

    print(f"\nDone. Downloaded {total_pdfs} PDFs to {save_dir}")


if __name__ == "__main__":
    main()
