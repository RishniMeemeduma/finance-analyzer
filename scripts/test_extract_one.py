"""Test extraction on a single PDF. Useful for prompt iteration."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extraction.extractor import extract_invoice_from_pdf


def find_pdf(arg: str) -> Path | None:
    """Find a PDF by exact path or by partial filename match."""
    p = Path(arg)
    if p.exists():
        return p

    # Try partial match in data/samples and data/raw
    for search_dir in [Path("data/samples"), Path("data/raw")]:
        if not search_dir.exists():
            continue
        matches = list(search_dir.glob(f"*{arg}*"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print(f"Multiple matches for {arg!r}:")
            for m in matches:
                print(f"  {m}")
            return None

    return None


def main():
    args = sys.argv[1:]
    force_vision = False
    if "--vision" in args:
        force_vision = True
        args.remove("--vision")

    if not args:
        print("Usage: python scripts/test_extract_one.py [--vision] PATH_OR_PARTIAL_NAME")
        sys.exit(1)

    pdf_path = find_pdf(args[0])
    if not pdf_path:
        print(f"No PDF found matching: {args[0]!r}")
        sys.exit(1)

    print(f"Extracting from {pdf_path.name}...\n")
    result = extract_invoice_from_pdf(pdf_path, force_vision=force_vision)
    

    print(f"Success: {result.success}")
    print(f"Path used: {result.path_used}")
    print(f"Model: {result.model}")

    if result.error:
        print(f"\nError: {result.error}")
        if result.raw_response:
            print(f"\nRaw response (failed validation):")
            print(json.dumps(result.raw_response, indent=2, default=str))
        return

    print("\nExtracted data:")
    print(json.dumps(result.data.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
