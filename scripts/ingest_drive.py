"""
Phase 2: Ingest invoices from a Google Drive folder.

Run from project root:
    python scripts/ingest_drive.py FOLDER_ID

Or set DRIVE_FOLDER_ID at the top of this file and just run:
    python scripts/ingest_drive.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.drive_client import (
    DriveClient,
    save_drive_file,
    MIME_PDF,
    MIME_GOOGLE_DOC,
)
from src.config import settings


# Default folder to scan. Override by passing folder ID as first arg.
DRIVE_FOLDER_ID = ""  # paste a folder ID here, or pass on command line

# What kinds of files to download
INCLUDE_PDFS = True
INCLUDE_GOOGLE_DOCS = True  # exports them as PDF
RECURSIVE = True  # walk into subfolders


def main():
    # Accept folder ID from command line or fall back to config above
    if len(sys.argv) > 1:
        folder_id = sys.argv[1]
    elif DRIVE_FOLDER_ID:
        folder_id = DRIVE_FOLDER_ID
    else:
        print("Usage: python scripts/ingest_drive.py FOLDER_ID")
        print("Or set DRIVE_FOLDER_ID at the top of this file.")
        sys.exit(1)

    print(f"Connecting to Google Drive...")
    client = DriveClient()

    # Verify the folder exists and we can see it
    try:
        folder_meta = client.get_file_metadata(folder_id)
        print(f"Folder: {folder_meta['name']} (id: {folder_id})")
    except Exception as e:
        print(f"ERROR: Could not access folder {folder_id}")
        print(f"  {e}")
        print("  Check the folder ID and that your Google account has access.")
        sys.exit(1)

    # Build the list of mime types we want
    mime_types = []
    if INCLUDE_PDFS:
        mime_types.append(MIME_PDF)
    if INCLUDE_GOOGLE_DOCS:
        mime_types.append(MIME_GOOGLE_DOC)

    print(f"Searching for: {mime_types} (recursive={RECURSIVE})\n")

    save_dir = settings.data_dir / "raw"
    total = 0

    for file in client.list_files_in_folder(
        folder_id, mime_types=mime_types, recursive=RECURSIVE
    ):
        name = file["name"]
        file_id = file["id"]
        mime = file["mimeType"]
        size = int(file.get("size", 0)) if file.get("size") else None

        size_label = f"{size / 1024:.1f} KB" if size else "n/a"
        print(f"[{total + 1}] {name} ({mime.split('.')[-1]}, {size_label})")

        try:
            if mime == MIME_PDF:
                content = client.download_file(file_id)
                output_path = save_drive_file(content, name, file_id, save_dir)
            elif mime == MIME_GOOGLE_DOC:
                content = client.export_google_doc_as_pdf(file_id)
                output_path = save_drive_file(
                    content, name, file_id, save_dir, suffix=".pdf"
                )
            else:
                print(f"      skipped (unsupported mime: {mime})")
                continue

            print(f"      saved -> {output_path.name}")
            total += 1

        except Exception as e:
            print(f"      ERROR: {e}")

    print(f"\nDone. Downloaded {total} files to {save_dir}")


if __name__ == "__main__":
    main()
