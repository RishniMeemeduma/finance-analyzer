"""Gmail client: search for emails with PDF attachments and download them."""
import base64
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.ingestion.google_auth import get_credentials
from src.config import settings


class GmailClient:
    def __init__(self):
        creds = get_credentials()
        self.service = build("gmail", "v1", credentials=creds)

    def search_messages(self, query: str, max_results: int = 50) -> list[dict]:
        """
        Search Gmail using its query syntax.

        Examples:
          'has:attachment filename:pdf'
          'from:billing@aws.amazon.com'
          'newer_than:30d has:attachment filename:pdf'
        """
        all_messages = []
        page_token = None

        while True:
            response = (
                self.service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    maxResults=min(max_results - len(all_messages), 100),
                    pageToken=page_token,
                )
                .execute()
            )

            messages = response.get("messages", [])
            all_messages.extend(messages)

            page_token = response.get("nextPageToken")
            if not page_token or len(all_messages) >= max_results:
                break

        return all_messages[:max_results]

    def get_message(self, message_id: str) -> dict:
        """Fetch the full content of a single message."""
        return (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

    def get_headers(self, message: dict) -> dict:
        """Extract headers (From, Subject, Date) as a flat dict."""
        headers = message.get("payload", {}).get("headers", [])
        return {h["name"]: h["value"] for h in headers}

    def iter_pdf_attachments(self, message: dict) -> Iterator[tuple[str, bytes]]:
        """
        Walk the message parts tree and yield (filename, content_bytes)
        for every PDF attachment.
        """
        message_id = message["id"]

        def walk(part: dict) -> Iterator[tuple[str, bytes]]:
            mime_type = part.get("mimeType", "")
            filename = part.get("filename", "")

            # Recurse into multipart messages
            if mime_type.startswith("multipart/"):
                for sub_part in part.get("parts", []):
                    yield from walk(sub_part)
                return

            # Only care about PDFs
            is_pdf = mime_type == "application/pdf" or filename.lower().endswith(".pdf")
            if not is_pdf or not filename:
                return

            body = part.get("body", {})
            attachment_id = body.get("attachmentId")

            if attachment_id:
                # Attachment needs a separate fetch
                attachment = (
                    self.service.users()
                    .messages()
                    .attachments()
                    .get(userId="me", messageId=message_id, id=attachment_id)
                    .execute()
                )
                data = attachment["data"]
            else:
                # Attachment data inline
                data = body.get("data", "")

            if data:
                # Gmail uses URL-safe base64
                content = base64.urlsafe_b64decode(data)
                yield filename, content

        yield from walk(message["payload"])


def save_pdf(content: bytes, filename: str, message_id: str, save_dir: Path) -> Path:
    """
    Save PDF content to disk with a unique, traceable name.

    We prefix with message_id so we can always trace a file back to its source email.
    """
    save_dir.mkdir(parents=True, exist_ok=True)
    # Sanitize filename: remove path separators and weird chars
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")
    output_path = save_dir / f"{message_id}__{safe_name}"
    output_path.write_bytes(content)
    return output_path
