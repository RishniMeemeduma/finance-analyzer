"""
Run anomaly detection across all invoices.

Wipes the existing anomalies table and re-detects from scratch.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.db import get_session
from src.anomaly.rules import _load_invoices, detect_all, persist_findings


def main():
    with get_session() as session:
        # Run on incoming (expenses) first - that's what most matters
        print("Loading incoming invoices...")
        incoming = _load_invoices(session, direction="incoming")
        print(f"  {len(incoming)} invoices loaded")

        print("Loading outgoing invoices...")
        outgoing = _load_invoices(session, direction="outgoing")
        print(f"  {len(outgoing)} invoices loaded")

        all_invoices = incoming + outgoing
        print(f"\nRunning {len(['rule'])} rules on {len(all_invoices)} invoices...")

        findings = detect_all(all_invoices)

        # Summary
        by_rule = Counter(f["rule"] for f in findings)
        by_severity = Counter(f["severity"] for f in findings)

        print(f"\nFound {len(findings)} anomalies:")
        for rule, count in by_rule.most_common():
            print(f"  {rule}: {count}")
        print(f"\nBy severity:")
        for severity, count in by_severity.most_common():
            print(f"  {severity}: {count}")

        persist_findings(session, findings)
        print(f"\nPersisted to database.")

        # Show a few examples
        print("\nSample findings:")
        for f in findings[:8]:
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")


if __name__ == "__main__":
    main()
