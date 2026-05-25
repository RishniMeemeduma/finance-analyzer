"""Find and optionally remove duplicate PDFs in data/raw/."""
import hashlib
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings


def file_hash(path: Path) -> str:
    """SHA-256 hash of file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    raw_dir = settings.data_dir / "raw"
    by_hash = defaultdict(list)

    for path in raw_dir.glob("*.pdf"):
        by_hash[file_hash(path)].append(path)

    duplicates_found = 0
    for h, paths in by_hash.items():
        if len(paths) > 1:
            duplicates_found += len(paths) - 1
            print(f"Duplicate group (hash {h[:12]}...):")
            for p in paths:
                print(f"  {p.name}")
            print()

    print(f"Total files: {sum(len(v) for v in by_hash.values())}")
    print(f"Unique:      {len(by_hash)}")
    print(f"Duplicates:  {duplicates_found}")


if __name__ == "__main__":
    main()
