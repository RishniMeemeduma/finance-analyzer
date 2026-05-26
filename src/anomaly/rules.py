"""Anomaly detection rules. Pure functions over the invoices table."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, stdev
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import Invoice
from src.storage.anomaly_model import Anomaly


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _load_invoices(session: Session, direction: str = "incoming") -> list[Invoice]:
    """Load invoices for analysis. Default to incoming (expenses)."""
    stmt = select(Invoice).where(
        Invoice.raw_extraction["direction"].astext == direction,
        Invoice.invoice_date.is_not(None),
    ).order_by(Invoice.invoice_date)
    return list(session.scalars(stmt))


def _group_by_vendor(invoices: list[Invoice]) -> dict[str, list[Invoice]]:
    """Group invoices by normalized vendor name."""
    by_vendor = defaultdict(list)
    for inv in invoices:
        by_vendor[inv.vendor_name_normalized].append(inv)
    return by_vendor


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

def find_duplicates(invoices: list[Invoice]) -> list[dict]:
    """
    Flag same vendor + same amount + dates within 7 days.

    We already dedupe on file content hash and invoice_number, but real-world
    duplicates can slip through if a vendor reissues with a new number.
    """
    findings = []
    by_vendor = _group_by_vendor(invoices)

    for vendor, vendor_invoices in by_vendor.items():
        for i, inv_a in enumerate(vendor_invoices):
            for inv_b in vendor_invoices[i + 1:]:
                if inv_a.total_amount != inv_b.total_amount:
                    continue
                if not inv_a.invoice_date or not inv_b.invoice_date:
                    continue
                days_apart = abs((inv_a.invoice_date - inv_b.invoice_date).days)
                if days_apart > 7:
                    continue

                findings.append(
                    {
                        "rule": "duplicate_suspect",
                        "severity": "warning",
                        "invoice_id": inv_a.id,
                        "message": (
                            f"Possible duplicate: {vendor} charged "
                            f"{inv_a.total_amount} {inv_a.currency} twice within {days_apart} days"
                        ),
                        "context": {
                            "vendor": vendor,
                            "amount": str(inv_a.total_amount),
                            "currency": inv_a.currency,
                            "invoice_a_id": str(inv_a.id),
                            "invoice_b_id": str(inv_b.id),
                            "dates": [str(inv_a.invoice_date), str(inv_b.invoice_date)],
                        },
                    }
                )
    return findings


def find_recurring_drift(invoices: list[Invoice], threshold_pct: float = 30.0) -> list[dict]:
    """
    For vendors seen 3+ times, flag invoices that jumped >threshold_pct above the running average.
    """
    findings = []
    by_vendor = _group_by_vendor(invoices)

    for vendor, vendor_invoices in by_vendor.items():
        # Need enough history to compute a baseline
        if len(vendor_invoices) < 3:
            continue

        # Use the same currency for comparison (skip mixed-currency vendors)
        currencies = {inv.currency for inv in vendor_invoices}
        if len(currencies) > 1:
            continue

        for i in range(2, len(vendor_invoices)):
            current = vendor_invoices[i]
            prior_amounts = [float(inv.total_amount) for inv in vendor_invoices[:i]]
            baseline = mean(prior_amounts)

            if baseline == 0:
                continue

            pct_change = ((float(current.total_amount) - baseline) / baseline) * 100
            if abs(pct_change) < threshold_pct:
                continue

            direction = "up" if pct_change > 0 else "down"
            findings.append(
                {
                    "rule": "recurring_drift",
                    "severity": "warning" if abs(pct_change) < 100 else "alert",
                    "invoice_id": current.id,
                    "message": (
                        f"{vendor}: {current.total_amount} {current.currency} is "
                        f"{abs(pct_change):.0f}% {direction} vs avg {baseline:.2f}"
                    ),
                    "context": {
                        "vendor": vendor,
                        "current_amount": str(current.total_amount),
                        "baseline_avg": f"{baseline:.2f}",
                        "pct_change": f"{pct_change:.1f}",
                        "currency": current.currency,
                    },
                }
            )
    return findings


def find_new_vendors(invoices: list[Invoice]) -> list[dict]:
    """Flag a vendor's first invoice as 'info' (not a problem, just notable)."""
    findings = []
    by_vendor = _group_by_vendor(invoices)

    for vendor, vendor_invoices in by_vendor.items():
        first_invoice = vendor_invoices[0]
        findings.append(
            {
                "rule": "new_vendor",
                "severity": "info",
                "invoice_id": first_invoice.id,
                "message": (
                    f"First invoice from {vendor}: "
                    f"{first_invoice.total_amount} {first_invoice.currency} "
                    f"on {first_invoice.invoice_date}"
                ),
                "context": {
                    "vendor": vendor,
                    "first_amount": str(first_invoice.total_amount),
                    "first_date": str(first_invoice.invoice_date),
                },
            }
        )
    return findings


def find_outliers(invoices: list[Invoice], z_threshold: float = 3.0) -> list[dict]:
    """
    For vendors with 4+ invoices, flag any invoice with z-score above threshold.
    """
    findings = []
    by_vendor = _group_by_vendor(invoices)

    for vendor, vendor_invoices in by_vendor.items():
        if len(vendor_invoices) < 4:
            continue

        amounts = [float(inv.total_amount) for inv in vendor_invoices]
        avg = mean(amounts)
        std = stdev(amounts)

        if std == 0:
            continue

        for inv in vendor_invoices:
            z = (float(inv.total_amount) - avg) / std
            if abs(z) < z_threshold:
                continue

            findings.append(
                {
                    "rule": "amount_outlier",
                    "severity": "warning",
                    "invoice_id": inv.id,
                    "message": (
                        f"{vendor}: {inv.total_amount} {inv.currency} is "
                        f"{z:+.1f} std deviations from this vendor's average ({avg:.2f})"
                    ),
                    "context": {
                        "vendor": vendor,
                        "amount": str(inv.total_amount),
                        "vendor_avg": f"{avg:.2f}",
                        "vendor_stdev": f"{std:.2f}",
                        "z_score": f"{z:.2f}",
                    },
                }
            )
    return findings


def find_missing_recurring(invoices: list[Invoice]) -> list[dict]:
    """
    For vendors that appear monthly, flag months with no invoice.

    Heuristic: if we see a vendor at least 3 times with average gap < 35 days,
    and the most recent invoice is older than (avg_gap * 1.5), flag it.
    """
    findings = []
    by_vendor = _group_by_vendor(invoices)
    today = date.today()

    for vendor, vendor_invoices in by_vendor.items():
        if len(vendor_invoices) < 3:
            continue

        dates = [inv.invoice_date for inv in vendor_invoices if inv.invoice_date]
        if len(dates) < 3:
            continue

        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        avg_gap = mean(gaps)

        if avg_gap > 35:  # not actually monthly
            continue

        last_seen = max(dates)
        days_since = (today - last_seen).days

        if days_since > avg_gap * 1.5:
            findings.append(
                {
                    "rule": "missing_recurring",
                    "severity": "warning",
                    "invoice_id": None,
                    "message": (
                        f"{vendor} normally bills every ~{avg_gap:.0f} days "
                        f"but hasn't been seen in {days_since} days"
                    ),
                    "context": {
                        "vendor": vendor,
                        "avg_gap_days": f"{avg_gap:.0f}",
                        "last_seen": str(last_seen),
                        "days_since": str(days_since),
                    },
                }
            )
    return findings


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

ALL_RULES = [
    find_duplicates,
    find_recurring_drift,
    find_new_vendors,
    find_outliers,
    find_missing_recurring,
]


def detect_all(invoices: list[Invoice]) -> list[dict]:
    """Run every rule and concatenate the findings."""
    all_findings = []
    for rule in ALL_RULES:
        all_findings.extend(rule(invoices))
    return all_findings


def persist_findings(session: Session, findings: list[dict]) -> int:
    """Insert findings into the anomalies table. Replaces any existing anomalies."""
    # Clean slate: delete previous anomalies (this is a full recompute)
    session.query(Anomaly).delete()

    for f in findings:
        anomaly = Anomaly(
            invoice_id=f.get("invoice_id"),
            rule=f["rule"],
            severity=f["severity"],
            message=f["message"],
            context=f.get("context", {}),
        )
        session.add(anomaly)

    session.flush()
    return len(findings)
