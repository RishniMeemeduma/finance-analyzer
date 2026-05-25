"""Google Drive client: list files in a folder, download PDFs and Docs."""
import io
from pathlib import Path
from typing import Iterator

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from src.ingestion.google_auth import get_credentials


# Common MIME types we'll care about
MIME_PDF = "application/pdf"
MIME_GOOGLE_DOC = "application/vnd.google-apps.document"
MIME_FOLDER = "application/vnd.google-apps.folder"


class DriveClient:
    def __init__(self):
        creds = get_credentials()
        self.service = build("drive", "v3", credentials=creds)

    def list_files_in_folder(
        self,
        folder_id: str,
        mime_types: list[str] | None = None,
        recursive: bool = False,
    ) -> Iterator[dict]:
        """
        Yield file metadata for every file in a folder.

        Args:
            folder_id: the Drive folder ID
            mime_types: filter to only these MIME types (e.g. [MIME_PDF])
            recursive: if True, also walk into subfolders

        Each yielded dict has: id, name, mimeType, size, modifiedTime, parents
        """
        # Build the query string
        query_parts = [f"'{folder_id}' in parents", "trashed = false"]

        if mime_types and not recursive:
            # If recursive, we need to also match folders to descend into them
            mime_filter = " or ".join(f"mimeType = '{m}'" for m in mime_types)
            query_parts.append(f"({mime_filter})")

        query = " and ".join(query_parts)

        # Paginate through results
        page_token = None
        while True:
            response = (
                self.service.files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, parents)",
                    pageSize=100,
                    pageToken=page_token,
                )
                .execute()
            )

            for file in response.get("files", []):
                if recursive and file["mimeType"] == MIME_FOLDER:
                    # Recurse into subfolders
                    yield from self.list_files_in_folder(
                        file["id"], mime_types=mime_types, recursive=True
                    )
                else:
                    # If filtering and we recursed, apply filter here
                    if mime_types and file["mimeType"] not in mime_types:
                        continue
                    yield file

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def download_file(self, file_id: str) -> bytes:
        """Download a regular (non-Google-Docs) file's content."""
        request = self.service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _status, done = downloader.next_chunk()

        return buffer.getvalue()

    def export_google_doc_as_pdf(self, file_id: str) -> bytes:
        """
        Export a native Google Doc as PDF.

        Native Google Docs can't be downloaded directly - they have to be
        converted/exported to a standard format first.
        """
        request = self.service.files().export_media(
            fileId=file_id, mimeType="application/pdf"
        )
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _status, done = downloader.next_chunk()

        return buffer.getvalue()

    def get_file_metadata(self, file_id: str) -> dict:
        """Get metadata for a single file."""
        return (
            self.service.files()
            .get(
                fileId=file_id,
                fields="id, name, mimeType, size, modifiedTime, parents, webViewLink",
            )
            .execute()
        )


def save_drive_file(
    content: bytes, file_name: str, file_id: str, save_dir: Path, suffix: str = ""
) -> Path:
    """Save downloaded file content with a traceable name."""
    save_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in file_name if c.isalnum() or c in "._- ")
    if suffix and not safe_name.lower().endswith(suffix.lower()):
        safe_name += suffix
    output_path = save_dir / f"drive_{file_id[:12]}__{safe_name}"
    output_path.write_bytes(content)
    return output_path
