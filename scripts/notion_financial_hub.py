"""Notion Financial Command Center + Action Items builder.

Creates databases under the Control Hub with pre-populated data
from master-operations-key.md.

Usage:
    python scripts/notion_financial_hub.py --control-hub-id <PAGE_ID> [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from scripts.integrations.notion_api import (
    create_page, create_database, add_database_row, query_database,
    search, append_blocks, blocks_from_markdown,
    build_title_prop, build_rich_text_prop, build_select_prop,
    build_number_prop, build_date_prop, build_checkbox_prop,
)

# ── Schema Definitions ────────────────────────────────────────────

def irs_debt_schema() -> dict:
    return {
        "Tax Year": {"title": {}},
        "Principal": {"number": {"format": "dollar"}},
        "Interest": {"number": {"format": "dollar"}},
        "Penalties": {"number": {"format": "dollar"}},
        "Total": {"number": {"format": "dollar"}},
        "Monthly Interest": {"number": {"format": "dollar"}},
        "Status": {"select": {"options": [
            {"name": "Paid", "color": "green"},
            {"name": "Unpaid", "color": "red"},
            {"name": "Levy Block", "color": "orange"},
            {"name": "Balance Due", "color": "yellow"},
        ]}},
        "Notes": {"rich_text": {}},
    }

def tax_deadlines_schema() -> dict:
    return {
        "Event": {"title": {}},
        "Date": {"date": {}},
        "Action": {"rich_text": {}},
        "Amount": {"number": {"format": "dollar"}},
        "Status": {"select": {"options": [
            {"name": "Upcoming", "color": "blue"},
            {"name": "MISSED", "color": "red"},
            {"name": "Done", "color": "green"},
            {"name": "OVERDUE", "color": "orange"},
        ]}},
    }

def debt_settlements_schema() -> dict:
    return {
        "Creditor": {"title": {}},
        "Collector": {"rich_text": {}},
        "Amount": {"number": {"format": "dollar"}},
        "Status": {"select": {"options": [
            {"name": "Litigation", "color": "red"},
            {"name": "Settlement Expired", "color": "orange"},
            {"name": "Served Papers", "color": "yellow"},
            {"name": "Settlement Offered", "color": "blue"},
            {"name": "Collections", "color": "purple"},
        ]}},
        "Notes": {"rich_text": {}},
    }

def amendment_schema() -> dict:
    return {
        "Category": {"title": {}},
        "Amount": {"number": {"format": "dollar"}},
        "Business %": {"rich_text": {}},
        "Deductible": {"number": {"format": "dollar"}},
        "Source": {"rich_text": {}},
    }

def action_items_schema() -> dict:
    return {
        "Item": {"title": {}},
        "Category": {"select": {"options": [
            {"name": "IRS/Tax", "color": "red"},
            {"name": "Legal", "color": "orange"},
            {"name": "License", "color": "yellow"},
            {"name": "Financial", "color": "blue"},
            {"name": "Business", "color": "green"},
            {"name": "Property", "color": "purple"},
            {"name": "Vehicle", "color": "gray"},
            {"name": "Insurance", "color": "pink"},
        ]}},
        "Priority": {"select": {"options": [
            {"name": "URGENT", "color": "red"},
            {"name": "High", "color": "orange"},
            {"name": "Medium", "color": "yellow"},
            {"name": "Low", "color": "blue"},
        ]}},
        "Due Date": {"date": {}},
        "Status": {"select": {"options": [
            {"name": "Not Started", "color": "gray"},
            {"name": "In Progress", "color": "blue"},
            {"name": "Waiting", "color": "yellow"},
            {"name": "OVERDUE", "color": "red"},
            {"name": "Done", "color": "green"},
        ]}},
        "Notes": {"rich_text": {}},
        "Completed": {"checkbox": {}},
    }

# ── Data Functions ────────────────────────────────────────────────

def irs_debt_rows() -> list[dict]:
    return [
        {"Tax Year": build_title_prop("2016"), "Status": build_select_prop("Balance Due"),
         "Notes": build_rich_text_prop("Amount unknown — balance due per IRS")},
        {"Tax Year": build_title_prop("2017"), "Total": build_number_prop(8701.65),
         "Status": build_select_prop("Balance Due"),
         "Notes": build_rich_text_prop("CP 71C notice received")},
        {"Tax Year": build_title_prop("2019"), "Status": build_select_prop("Balance Due"),
         "Notes": build_rich_text_prop("Amount unknown — balance due per IRS")},
        {"Tax Year": build_title_prop("2020"), "Principal": build_number_prop(0),
         "Interest": build_number_prop(0), "Penalties": build_number_prop(0),
         "Total": build_number_prop(0), "Status": build_select_prop("Paid"),
         "Notes": build_rich_text_prop("Fully paid")},
        {"Tax Year": build_title_prop("2021"), "Principal": build_number_prop(5168),
         "Interest": build_number_prop(881), "Penalties": build_number_prop(153),
         "Total": build_number_prop(6201), "Monthly Interest": build_number_prop(34),
         "Status": build_select_prop("Unpaid")},
        {"Tax Year": build_title_prop("2022"), "Principal": build_number_prop(17053),
         "Interest": build_number_prop(1526), "Penalties": build_number_prop(1863),
         "Total": build_number_prop(20442), "Monthly Interest": build_number_prop(117),
         "Status": build_select_prop("Levy Block"),
         "Notes": build_rich_text_prop("ACTIVE LEVY — highest priority")},
        {"Tax Year": build_title_prop("2023"), "Principal": build_number_prop(18091),
         "Interest": build_number_prop(139), "Penalties": build_number_prop(80),
         "Total": build_number_prop(18310), "Monthly Interest": build_number_prop(69),
         "Status": build_select_prop("Unpaid")},
    ]

def tax_deadline_rows() -> list[dict]:
    return [
        {"Event": build_title_prop("Q4 2024 Estimated Tax"),
         "Date": build_date_prop("2025-01-15"), "Amount": build_number_prop(4384),
         "Action": build_rich_text_prop("Was due Jan 15 2025"), "Status": build_select_prop("MISSED")},
        {"Event": build_title_prop("Q4 2025 Estimated Tax"),
         "Date": build_date_prop("2026-01-15"), "Amount": build_number_prop(4400),
         "Action": build_rich_text_prop("Pay ~$4,400"), "Status": build_select_prop("MISSED")},
        {"Event": build_title_prop("Cosmetology License Renewal"),
         "Date": build_date_prop("2026-02-28"),
         "Action": build_rich_text_prop("Renew Ashley license #108628"), "Status": build_select_prop("Upcoming")},
        {"Event": build_title_prop("2025 Return/Extension + Q1 Est"),
         "Date": build_date_prop("2026-04-15"), "Amount": build_number_prop(4400),
         "Action": build_rich_text_prop("File Form 4868 + pay Q1 est"), "Status": build_select_prop("Upcoming")},
        {"Event": build_title_prop("F-250 Plate Renewal"),
         "Date": build_date_prop("2026-06-30"),
         "Action": build_rich_text_prop("Renew plate 667BMKT"), "Status": build_select_prop("Upcoming")},
        {"Event": build_title_prop("Q2 2026 Estimated Tax"),
         "Date": build_date_prop("2026-06-15"), "Amount": build_number_prop(4400),
         "Action": build_rich_text_prop("Pay ~$4,400"), "Status": build_select_prop("Upcoming")},
        {"Event": build_title_prop("Q3 2026 Estimated Tax"),
         "Date": build_date_prop("2026-09-15"), "Amount": build_number_prop(4400),
         "Action": build_rich_text_prop("Pay ~$4,400"), "Status": build_select_prop("Upcoming")},
        {"Event": build_title_prop("Extended 2025 Return Due"),
         "Date": build_date_prop("2026-10-15"),
         "Action": build_rich_text_prop("File full 2025 return"), "Status": build_select_prop("Upcoming")},
    ]

def debt_settlement_rows() -> list[dict]:
    return [
        {"Creditor": build_title_prop("Synchrony/Havertys"),
         "Collector": build_rich_text_prop("Portfolio Recovery"),
         "Amount": build_number_prop(1312), "Status": build_select_prop("Litigation"),
         "Notes": build_rich_text_prop("Active litigation")},
        {"Creditor": build_title_prop("Navy Federal"),
         "Collector": build_rich_text_prop("Brock & Scott"),
         "Amount": build_number_prop(24909), "Status": build_select_prop("Settlement Expired"),
         "Notes": build_rich_text_prop("Previous settlement offer expired")},
        {"Creditor": build_title_prop("Synchrony/TJX"),
         "Collector": build_rich_text_prop("Portfolio Recovery"),
         "Amount": build_number_prop(594), "Status": build_select_prop("Served Papers"),
         "Notes": build_rich_text_prop("Papers served")},
        {"Creditor": build_title_prop("Wells Fargo"),
         "Collector": build_rich_text_prop("Direct"),
         "Amount": build_number_prop(8483), "Status": build_select_prop("Settlement Offered"),
         "Notes": build_rich_text_prop("Settlement offer on table")},
        {"Creditor": build_title_prop("AmeriCredit/GM Financial"),
         "Collector": build_rich_text_prop("FMA Alliance"),
         "Amount": build_number_prop(6621), "Status": build_select_prop("Collections"),
         "Notes": build_rich_text_prop("2021 Ram (wrecked)")},
    ]

def amendment_rows() -> list[dict]:
    return [
        {"Category": build_title_prop("Labor/Contractors (Teller Checks)"),
         "Amount": build_number_prop(23577.73), "Business %": build_rich_text_prop("100%"),
         "Deductible": build_number_prop(23577.73), "Source": build_rich_text_prop("Bank statements")},
        {"Category": build_title_prop("SCP Distributors"),
         "Amount": build_number_prop(5359.82), "Business %": build_rich_text_prop("100%"),
         "Deductible": build_number_prop(5359.82), "Source": build_rich_text_prop("Bank statements")},
        {"Category": build_title_prop("Home Depot"),
         "Amount": build_number_prop(4070.31), "Business %": build_rich_text_prop("100%"),
         "Deductible": build_number_prop(4070.31), "Source": build_rich_text_prop("Bank statements")},
        {"Category": build_title_prop("AT&T"),
         "Amount": build_number_prop(2296.15), "Business %": build_rich_text_prop("70%"),
         "Deductible": build_number_prop(1607.31), "Source": build_rich_text_prop("AT&T statements")},
        {"Category": build_title_prop("Insurance"),
         "Amount": build_number_prop(2905.06), "Business %": build_rich_text_prop("50%"),
         "Deductible": build_number_prop(1452.53), "Source": build_rich_text_prop("Bank statements")},
        {"Category": build_title_prop("Vehicle/Gas"),
         "Amount": build_number_prop(271.59), "Business %": build_rich_text_prop("80%"),
         "Deductible": build_number_prop(217.27), "Source": build_rich_text_prop("Bank statements")},
        {"Category": build_title_prop("Business Meals"),
         "Amount": build_number_prop(178.99), "Business %": build_rich_text_prop("50%"),
         "Deductible": build_number_prop(89.50), "Source": build_rich_text_prop("Bank statements")},
    ]

def action_item_rows() -> list[dict]:
    items = [
        # URGENT
        ("Alabama Ticket U6938326 (69 in 55)", "Legal", "URGENT", "2026-01-13", "OVERDUE",
         "Was due 01/13/2026 — handle immediately"),
        ("Call IRS: 1-800-829-1040", "IRS/Tax", "URGENT", None, "Not Started",
         "Set up payment plan — $1,500/mo recommended"),
        ("Q4 2024 Estimated Tax — MISSED", "IRS/Tax", "URGENT", "2025-01-15", "OVERDUE",
         "$4,384 + penalties accruing"),
        ("Business Insurance LAPSED", "Insurance", "URGENT", None, "Not Started",
         "Kellen/Vertigo policy lapsed — operating uninsured"),
        # High
        ("Set up IRS payment plan ($1,500/mo)", "IRS/Tax", "High", "2026-01-31", "Not Started",
         "Call 1-800-829-1040, request installment agreement"),
        ("Open dedicated tax savings account", "Financial", "High", "2026-01-31", "Not Started",
         "Separate from operating — auto-transfer $2,900/mo"),
        ("Auto-transfer $2,900/mo to tax account", "Financial", "High", "2026-01-31", "Not Started",
         "Set up after opening tax savings account"),
        ("Contact CPA Dean at Atlas", "IRS/Tax", "High", "2026-01-31", "Not Started",
         "Discuss 2023 amendment + 2024 filing strategy"),
        ("Renew Ashley cosmetology license #108628", "License", "High", "2026-02-28", "Not Started",
         "Expires 02/28/2026 — cannot work without it"),
        ("Export Venmo data for labor payments", "Financial", "High", None, "Not Started",
         "Need for 2023/2024 contractor 1099 reconciliation"),
        ("Export Cash App data (2024-2025)", "Financial", "High", None, "Not Started",
         "2023 done — need 2024-2025 for ongoing tracking"),
        ("Amend 2023 return (+$36K deductions)", "IRS/Tax", "High", "2026-03-31", "Not Started",
         "$36,374 in deductions + $8,600 unreported rental income"),
        ("File 2024 extension (Form 4868)", "IRS/Tax", "High", "2026-04-15", "Not Started",
         "Must file before April 15 to avoid failure-to-file penalty"),
        # Medium
        ("Fix MDX title (odometer disclosure)", "Vehicle", "Medium", "2026-03-31", "Not Started",
         "2018 Acura MDX — needs odometer disclosure for title transfer"),
        ("Address TN Dept Revenue $37.38", "IRS/Tax", "Medium", "2026-03-31", "Not Started",
         "Case 252-3134 — small balance but clean it up"),
        ("Research S-Corp election for 2026", "Business", "Medium", "2026-03-31", "Not Started",
         "Could save significant self-employment tax"),
        ("Pay 670 Landis delinquent property taxes", "Property", "Medium", None, "Not Started",
         "Delinquent 2023/2024/2025 — risk of tax sale"),
        ("Issue 1099s for 2024 contractors", "IRS/Tax", "Medium", "2026-01-31", "Not Started",
         "MD, Luke, Barrett, Beau, James Hopper if >$600"),
        ("Q1 2026 Estimated Tax", "IRS/Tax", "Medium", "2026-04-15", "Not Started",
         "~$4,400 due with extension"),
        ("Get business insurance quote", "Insurance", "Medium", None, "Not Started",
         "General liability + commercial auto for pool work"),
        # Low
        ("Q2 2026 Estimated Tax", "IRS/Tax", "Low", "2026-06-15", "Not Started", "~$4,400"),
        ("Q3 2026 Estimated Tax", "IRS/Tax", "Low", "2026-09-15", "Not Started", "~$4,400"),
        ("F-250 plate renewal", "Vehicle", "Low", "2026-06-30", "Not Started", "Plate 667BMKT"),
        ("File full 2025 return", "IRS/Tax", "Low", "2026-10-15", "Not Started",
         "After extension — need all data compiled"),
        ("Reconcile Navy Federal settlement", "Financial", "Low", None, "Not Started",
         "$24,909 — settlement expired, check new options"),
        ("Respond to Wells Fargo settlement offer", "Financial", "Low", None, "Not Started",
         "$8,483 — offer on table"),
        ("Address Portfolio Recovery (Havertys $1,312)", "Financial", "Low", None, "Not Started",
         "Active litigation"),
        ("Address Portfolio Recovery (TJX $594)", "Financial", "Low", None, "Not Started",
         "Served papers"),
        ("Address FMA Alliance (AmeriCredit $6,621)", "Financial", "Low", None, "Not Started",
         "2021 Ram — wrecked vehicle debt"),
        ("Compile Memphis Pool 2025 income docs", "Business", "Low", None, "Not Started",
         "~$73,674 YTD from 1099-NEC"),
    ]
    rows = []
    for item, cat, pri, due, status, notes in items:
        row: dict = {
            "Item": build_title_prop(item),
            "Category": build_select_prop(cat),
            "Priority": build_select_prop(pri),
            "Status": build_select_prop(status),
            "Notes": build_rich_text_prop(notes),
            "Completed": build_checkbox_prop(False),
        }
        if due:
            row["Due Date"] = build_date_prop(due)
        rows.append(row)
    return rows

# ── Revenue Dashboard Content (Markdown) ──────────────────────────

REVENUE_MD = """## Artesian Pools Revenue History

| Year | Gross Revenue | Net Income | Source |
|------|---------------|------------|--------|
| 2020 | $68,264 | $11,389 | IRS Transcript |
| 2021 | $96,076 | $32,843 | IRS Transcript |
| 2022 | $150,170 | $71,773 | IRS Transcript |
| 2023 | $167,852 | $70,144 | IRS Transcript |
| 2024 | ~$38,000 | TBD | 1099s on file |
| 2025 | ~$113,700+ | TBD | Square + Memphis Pool |

> Revenue Growth (2020-2023): +146% (CAGR 35.3%)
> Profit Margin (2023): 41.8%

---

## Style Therapy Revenue (Square)

| Year | Gross Sales | Tips | Fees | Net | Transactions |
|------|-------------|------|------|-----|--------------|
| 2023 | $26,887 | $4,984 | $845 | $26,042 | 269 |
| 2024 | $30,717 | $5,148 | $934 | $29,783 | 272 |
| 2025 | $40,052 | $6,652 | $1,260 | $38,793 | 330 |

> Revenue Growth (2023-2025): +49%
> Tips Ratio: ~16% of gross

---

## Key Metrics

- **Total IRS Debt:** $44,952
- **Monthly Interest Burn:** $150-200
- **Recommended Payment Plan:** $1,500/month
- **Monthly Tax Reserve Needed:** $2,900
- **Quarterly Estimated Tax:** ~$4,400
- **2023 Amendment Deductions:** ~$36,000
- **2023 Unreported Rental Income:** $8,600
"""

# ── Orchestration ─────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(f"[notion-fin] {msg}", file=sys.stderr)


def _find_existing_page(title: str) -> str | None:
    """Search Notion for an existing page by title. Returns page ID or None."""
    res = search(title, limit=5)
    if not res.get("ok"):
        return None
    for item in (res.get("data", {}) or {}).get("results", []):
        if item.get("object") != "page":
            continue
        props = item.get("properties", {})
        title_prop = props.get("title", {})
        if isinstance(title_prop, dict):
            title_arr = title_prop.get("title", [])
        else:
            title_arr = []
        for t in title_arr:
            if t.get("plain_text", "").strip().lower() == title.lower():
                return item["id"]
    return None


def _create_and_populate(
    parent_id: str,
    db_title: str,
    schema: dict,
    rows: list[dict],
    dry_run: bool = False,
) -> dict:
    """Create a database and populate it with rows."""
    result = {"database": db_title, "rows_attempted": len(rows), "rows_created": 0, "errors": []}

    if dry_run:
        _log(f"  [DRY RUN] Would create DB '{db_title}' with {len(schema)} columns, {len(rows)} rows")
        result["rows_created"] = len(rows)
        return result

    _log(f"  Creating database: {db_title}")
    db_res = create_database(parent_id, db_title, schema)
    if not db_res.get("ok"):
        err = db_res.get("error", "unknown error")
        _log(f"  ERROR creating DB: {err}")
        result["errors"].append(f"DB creation failed: {err}")
        return result

    db_id = (db_res.get("data", {}) or {}).get("id", "")
    result["database_id"] = db_id
    _log(f"  Database created: {db_id}")

    for i, row in enumerate(rows):
        time.sleep(0.35)  # rate limit safety
        row_res = add_database_row(db_id, row)
        if row_res.get("ok"):
            result["rows_created"] += 1
        else:
            err = row_res.get("error", "unknown")
            _log(f"  ERROR row {i}: {err}")
            result["errors"].append(f"Row {i}: {err}")

    _log(f"  Populated {result['rows_created']}/{len(rows)} rows")
    return result


def build_financial_hub(control_hub_id: str, dry_run: bool = False) -> dict:
    """Create the Financial Command Center parent page and all databases."""
    _log("Building Financial Command Center...")
    summary = {"page": "Financial Command Center", "databases": []}

    if dry_run:
        _log("[DRY RUN] Would create page 'Financial Command Center'")
        hub_id = "dry-run-id"
    else:
        existing = _find_existing_page("Financial Command Center")
        if existing:
            _log(f"Found existing page: {existing}")
            hub_id = existing
        else:
            res = create_page(control_hub_id, "Financial Command Center",
                              "# Financial Command Center\nCentral tracking for IRS debt, tax deadlines, settlements, and revenue.")
            if not res.get("ok"):
                return {"ok": False, "error": res.get("error", ""), "summary": summary}
            hub_id = (res.get("data", {}) or {}).get("id", "")
            _log(f"Created page: {hub_id}")

    summary["page_id"] = hub_id

    # Create each database
    dbs = [
        ("IRS Debt Tracker", irs_debt_schema(), irs_debt_rows()),
        ("Tax Deadlines", tax_deadlines_schema(), tax_deadline_rows()),
        ("Debt Settlements", debt_settlements_schema(), debt_settlement_rows()),
        ("2023 Amendment Tracker", amendment_schema(), amendment_rows()),
    ]
    for title, schema, rows in dbs:
        r = _create_and_populate(hub_id, title, schema, rows, dry_run)
        summary["databases"].append(r)

    # Revenue Dashboard as a rich content page
    if dry_run:
        _log("[DRY RUN] Would create Revenue Dashboard page")
        summary["databases"].append({"database": "Revenue Dashboard", "rows_created": 0, "type": "page"})
    else:
        _log("  Creating Revenue Dashboard page...")
        rev_res = create_page(hub_id, "Revenue Dashboard", REVENUE_MD)
        ok = rev_res.get("ok", False)
        summary["databases"].append({
            "database": "Revenue Dashboard", "type": "page",
            "ok": ok, "error": rev_res.get("error", "") if not ok else "",
        })

    return {"ok": True, "summary": summary}


def build_action_items(control_hub_id: str, dry_run: bool = False) -> dict:
    """Create the Action Items parent page and database."""
    _log("Building Action Items...")
    summary = {"page": "Action Items", "databases": []}

    if dry_run:
        _log("[DRY RUN] Would create page 'Action Items'")
        hub_id = "dry-run-id"
    else:
        existing = _find_existing_page("Action Items")
        if existing:
            _log(f"Found existing page: {existing}")
            hub_id = existing
        else:
            res = create_page(control_hub_id, "Action Items",
                              "# Action Items\nAll open loops, deadlines, and tasks from the Godman operations.")
            if not res.get("ok"):
                return {"ok": False, "error": res.get("error", ""), "summary": summary}
            hub_id = (res.get("data", {}) or {}).get("id", "")
            _log(f"Created page: {hub_id}")

    summary["page_id"] = hub_id
    r = _create_and_populate(hub_id, "Action Items", action_items_schema(), action_item_rows(), dry_run)
    summary["databases"].append(r)
    return {"ok": True, "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Notion Financial Command Center")
    parser.add_argument("--control-hub-id", required=True, help="Notion page ID of the Control Hub")
    parser.add_argument("--dry-run", action="store_true", help="Validate schemas without API calls")
    args = parser.parse_args()

    _log(f"Control Hub ID: {args.control_hub_id}")
    _log(f"Dry run: {args.dry_run}")

    fin = build_financial_hub(args.control_hub_id, args.dry_run)
    act = build_action_items(args.control_hub_id, args.dry_run)

    output = {
        "financial_command_center": fin.get("summary", {}),
        "action_items": act.get("summary", {}),
    }
    print(json.dumps(output, indent=2))

    # Summary counts
    total_rows = 0
    total_errors = 0
    for section in [fin, act]:
        for db in section.get("summary", {}).get("databases", []):
            total_rows += db.get("rows_created", 0)
            total_errors += len(db.get("errors", []))

    _log(f"Done. {total_rows} rows created, {total_errors} errors.")


if __name__ == "__main__":
    main()
