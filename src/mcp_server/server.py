import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

"""
MCP server for the Finance Analyzer.

Exposes the database as a set of tools any MCP client (Claude Desktop,
custom apps, etc) can call.

Run:
    python -m src.mcp_server.server     # stdio transport (for Claude Desktop)
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import FastMCP

from src.storage.db import get_session
from src.storage.repository import search_invoices, get_invoice_by_id
from src.storage.models import Invoice
from src.storage.anomaly_model import Anomaly
from sqlalchemy import select, func, and_


# --------------------------------------------------------------------------
# Server setup
# --------------------------------------------------------------------------

mcp = FastMCP("finance-analyzer")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _invoice_to_dict(inv: Invoice) -> dict:
    """Convert an Invoice to a JSON-serializable dict."""
    return {
        "id": str(inv.id),
        "vendor": inv.vendor_name,
        "vendor_normalized": inv.vendor_name_normalized,
        "invoice_number": inv.invoice_number,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "currency": inv.currency,
        "subtotal": str(inv.subtotal) if inv.subtotal is not None else None,
        "tax_amount": str(inv.tax_amount) if inv.tax_amount is not None else None,
        "total_amount": str(inv.total_amount),
        "category": inv.category,
        "direction": inv.raw_extraction.get("direction"),
        "document_type": inv.raw_extraction.get("document_type"),
        "is_recurring": inv.is_recurring,
    }


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return date.fromisoformat(s)


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

@mcp.tool()
def search_invoices_tool(
    vendor: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    category: str | None = None,
    direction: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    limit: int = 25,
) -> dict:
    """
    Search invoices by any combination of filters.

    Args:
        vendor: Vendor name substring (case-insensitive). E.g. "anthropic".
        date_from: ISO date "YYYY-MM-DD". Only invoices on or after this date.
        date_to: ISO date "YYYY-MM-DD". Only invoices on or before this date.
        category: Exact category match (e.g. "software_saas", "professional_services").
        direction: "incoming" (expenses) or "outgoing" (revenue).
        min_amount: Minimum total amount.
        max_amount: Maximum total amount.
        limit: Max rows to return (default 25, hard cap 200).

    Returns a dict with: count, invoices (list of invoice dicts).
    """
    limit = min(limit, 200)

    with get_session() as session:
        stmt = select(Invoice)
        conditions = []

        if vendor:
            conditions.append(Invoice.vendor_name_normalized.contains(vendor.lower()))
        if date_from:
            conditions.append(Invoice.invoice_date >= _parse_date(date_from))
        if date_to:
            conditions.append(Invoice.invoice_date <= _parse_date(date_to))
        if category:
            conditions.append(Invoice.category == category)
        if direction:
            conditions.append(Invoice.raw_extraction["direction"].astext == direction)
        if min_amount is not None:
            conditions.append(Invoice.total_amount >= Decimal(str(min_amount)))
        if max_amount is not None:
            conditions.append(Invoice.total_amount <= Decimal(str(max_amount)))

        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(Invoice.invoice_date.desc().nulls_last()).limit(limit)

        invoices = list(session.scalars(stmt))
        return {
            "count": len(invoices),
            "invoices": [_invoice_to_dict(inv) for inv in invoices],
        }


@mcp.tool()
def get_invoice_details_tool(invoice_id: str) -> dict:
    """
    Fetch a single invoice in full detail, including line items.

    Args:
        invoice_id: The invoice's UUID (as returned by search_invoices_tool).
    """
    with get_session() as session:
        inv = get_invoice_by_id(session, UUID(invoice_id))
        if not inv:
            return {"error": f"Invoice {invoice_id} not found"}

        data = _invoice_to_dict(inv)
        data["line_items"] = [
            {
                "description": li.description,
                "quantity": str(li.quantity) if li.quantity is not None else None,
                "unit_price": str(li.unit_price) if li.unit_price is not None else None,
                "amount": str(li.amount),
                "position": li.position,
            }
            for li in inv.line_items
        ]
        data["extraction_notes"] = inv.raw_extraction.get("extraction_notes")
        return data


@mcp.tool()
def aggregate_spending_tool(
    direction: str = "incoming",
    group_by: str = "category",
    date_from: str | None = None,
    date_to: str | None = None,
    currency: str | None = None,
    exclude_receipts: bool = True,
) -> dict:
    """
    Aggregate spending or revenue.

    Args:
        direction: "incoming" (expenses) or "outgoing" (revenue). Default incoming.
        group_by: "category", "vendor", "month", or "currency".
        date_from: ISO date filter.
        date_to: ISO date filter.
        currency: Filter to a single currency (e.g. "GBP", "USD").
        exclude_receipts: If True (default), only count invoices, not payment receipts.

    Returns a dict with: group_by, rows (list of {group, count, total}).
    """
    with get_session() as session:
        # Choose the GROUP BY column
        if group_by == "category":
            group_col = Invoice.category
        elif group_by == "vendor":
            group_col = Invoice.vendor_name_normalized
        elif group_by == "month":
            group_col = func.to_char(Invoice.invoice_date, "YYYY-MM")
        elif group_by == "currency":
            group_col = Invoice.currency
        else:
            return {"error": f"Unsupported group_by: {group_by}"}

        stmt = select(
            group_col.label("grp"),
            func.count(Invoice.id).label("cnt"),
            func.sum(Invoice.total_amount).label("total"),
            Invoice.currency,
        )

        conditions = [
            Invoice.raw_extraction["direction"].astext == direction,
            Invoice.invoice_date.is_not(None),
        ]
        if exclude_receipts:
            conditions.append(
                Invoice.raw_extraction["document_type"].astext != "receipt"
            )
        if date_from:
            conditions.append(Invoice.invoice_date >= _parse_date(date_from))
        if date_to:
            conditions.append(Invoice.invoice_date <= _parse_date(date_to))
        if currency:
            conditions.append(Invoice.currency == currency)

        stmt = stmt.where(and_(*conditions)).group_by(group_col, Invoice.currency)
        stmt = stmt.order_by(func.sum(Invoice.total_amount).desc())

        rows = []
        for grp, cnt, total, curr in session.execute(stmt).all():
            rows.append(
                {
                    "group": grp,
                    "count": cnt,
                    "total": str(total),
                    "currency": curr,
                }
            )

        return {
            "group_by": group_by,
            "direction": direction,
            "rows": rows,
        }


@mcp.tool()
def compare_periods_tool(
    period_a_from: str,
    period_a_to: str,
    period_b_from: str,
    period_b_to: str,
    direction: str = "incoming",
    group_by: str = "category",
    currency: str | None = None,
) -> dict:
    """
    Compare aggregated spending between two periods, broken down by category or vendor.

    Args:
        period_a_from / period_a_to: First period bounds (ISO dates).
        period_b_from / period_b_to: Second period bounds (ISO dates).
        direction: "incoming" or "outgoing".
        group_by: "category" or "vendor".
        currency: Optional currency filter.

    Returns a dict with period totals, per-group breakdown, and pct changes.
    """
    a = aggregate_spending_tool(
        direction=direction,
        group_by=group_by,
        date_from=period_a_from,
        date_to=period_a_to,
        currency=currency,
    )
    b = aggregate_spending_tool(
        direction=direction,
        group_by=group_by,
        date_from=period_b_from,
        date_to=period_b_to,
        currency=currency,
    )

    a_map = {r["group"]: r for r in a["rows"]}
    b_map = {r["group"]: r for r in b["rows"]}
    all_groups = set(a_map) | set(b_map)

    comparison = []
    for g in all_groups:
        a_total = Decimal(a_map[g]["total"]) if g in a_map else Decimal(0)
        b_total = Decimal(b_map[g]["total"]) if g in b_map else Decimal(0)
        pct = None
        if a_total > 0:
            pct = float((b_total - a_total) / a_total * 100)
        comparison.append(
            {
                "group": g,
                "period_a_total": str(a_total),
                "period_b_total": str(b_total),
                "absolute_change": str(b_total - a_total),
                "pct_change": f"{pct:.1f}" if pct is not None else None,
            }
        )

    comparison.sort(key=lambda x: Decimal(x["period_b_total"]), reverse=True)

    return {
        "period_a": {"from": period_a_from, "to": period_a_to},
        "period_b": {"from": period_b_from, "to": period_b_to},
        "by_group": comparison,
    }


@mcp.tool()
def list_anomalies_tool(
    severity: str | None = None,
    rule: str | None = None,
    limit: int = 25,
) -> dict:
    """
    List anomalies detected by the rules engine.

    Args:
        severity: "info", "warning", or "alert". Omit for all.
        rule: Filter to one rule, e.g. "recurring_drift", "duplicate_suspect".
        limit: Max results.
    """
    limit = min(limit, 100)
    with get_session() as session:
        stmt = select(Anomaly)
        conditions = []
        if severity:
            conditions.append(Anomaly.severity == severity)
        if rule:
            conditions.append(Anomaly.rule == rule)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(Anomaly.detected_at.desc()).limit(limit)

        results = []
        for a in session.scalars(stmt):
            results.append(
                {
                    "id": str(a.id),
                    "rule": a.rule,
                    "severity": a.severity,
                    "message": a.message,
                    "invoice_id": str(a.invoice_id) if a.invoice_id else None,
                    "context": a.context,
                    "detected_at": a.detected_at.isoformat(),
                }
            )
        return {"count": len(results), "anomalies": results}


@mcp.tool()
def list_vendors_tool(direction: str | None = None, limit: int = 50) -> dict:
    """
    List all distinct vendors with invoice counts and total spending.

    Args:
        direction: "incoming" or "outgoing". Omit for both.
        limit: Max results.
    """
    limit = min(limit, 200)
    with get_session() as session:
        stmt = select(
            Invoice.vendor_name_normalized,
            Invoice.currency,
            func.count(Invoice.id).label("cnt"),
            func.sum(Invoice.total_amount).label("total"),
        )
        if direction:
            stmt = stmt.where(Invoice.raw_extraction["direction"].astext == direction)
        stmt = (
            stmt.group_by(Invoice.vendor_name_normalized, Invoice.currency)
            .order_by(func.sum(Invoice.total_amount).desc())
            .limit(limit)
        )

        rows = [
            {
                "vendor": vendor,
                "invoices": cnt,
                "total_amount": str(total),
                "currency": curr,
            }
            for vendor, curr, cnt, total in session.execute(stmt).all()
        ]
        return {"count": len(rows), "vendors": rows}


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

@mcp.tool()
def add_invoice_tool(
    vendor_name: str,
    total_amount: float,
    invoice_date: str,
    direction: str = "incoming",
    currency: str = "USD",
    category: str | None = None,
    is_recurring: bool = False,
    invoice_number: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    Manually add an invoice that isn't backed by any PDF or email.

    Use this for subscriptions paid via channels that don't email receipts
    (e.g. Apple in-app subscriptions to your iCloud), cash purchases, or
    one-off corrections.

    Args:
        vendor_name: Name of the vendor (e.g. "Medium").
        total_amount: The amount (decimal).
        invoice_date: ISO date "YYYY-MM-DD".
        direction: "incoming" (expense, default) or "outgoing" (revenue).
        currency: 3-letter ISO code. Defaults to USD.
        category: e.g. "software_saas".
        is_recurring: Mark as recurring subscription.
        invoice_number: Optional reference number.
        notes: Free-form notes.
    """
    from decimal import Decimal
    from datetime import date as _date
    from src.storage.repository import create_manual_invoice

    with get_session() as session:
        inv = create_manual_invoice(
            session,
            vendor_name=vendor_name,
            total_amount=Decimal(str(total_amount)),
            direction=direction,
            invoice_date=_date.fromisoformat(invoice_date),
            currency=currency.upper(),
            category=category,
            is_recurring=is_recurring,
            invoice_number=invoice_number,
            notes=notes,
        )
        session.flush()
        return _invoice_to_dict(inv)


@mcp.tool()
def add_recurring_invoices_tool(
    vendor_name: str,
    amount_per_period: float,
    start_date: str,
    end_date: str,
    cadence_days: int = 30,
    direction: str = "incoming",
    currency: str = "USD",
    category: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    Generate a series of identical recurring invoices between two dates.

    Use to backfill a subscription history at once. Creates one invoice every
    `cadence_days` between start_date and end_date inclusive.

    Args:
        vendor_name: e.g. "Medium".
        amount_per_period: Amount of each charge.
        start_date: ISO date "YYYY-MM-DD" of the first charge.
        end_date: ISO date "YYYY-MM-DD" - last possible charge (inclusive).
        cadence_days: 30 for monthly, 7 for weekly, 365 for annual.
        direction: "incoming" (expense, default) or "outgoing".
        currency: 3-letter ISO code.
        category: e.g. "software_saas".
        notes: Free-form notes attached to every invoice.
    """
    from decimal import Decimal
    from datetime import date as _date
    from src.storage.repository import generate_recurring_invoices

    with get_session() as session:
        invoices = generate_recurring_invoices(
            session,
            vendor_name=vendor_name,
            amount=Decimal(str(amount_per_period)),
            start_date=_date.fromisoformat(start_date),
            end_date=_date.fromisoformat(end_date),
            cadence_days=cadence_days,
            direction=direction,
            currency=currency.upper(),
            category=category,
            notes=notes,
        )
        session.flush()
        return {
            "count": len(invoices),
            "vendor": vendor_name,
            "currency": currency.upper(),
            "total_amount_inserted": str(sum(i.total_amount for i in invoices)),
            "first_invoice_date": invoices[0].invoice_date.isoformat() if invoices else None,
            "last_invoice_date": invoices[-1].invoice_date.isoformat() if invoices else None,
        }



if __name__ == "__main__":
    mcp.run()
