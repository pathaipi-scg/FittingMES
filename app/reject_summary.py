"""Workflow-isolated quantity totals for the new Fitting REJECT CAL."""
from datetime import date
import re

from app.reject import WORKFLOW_TABLES, RejectValidationError


def _positive_id(value, label, maximum=9223372036854775807):
    text = str(value if value is not None else "").strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise RejectValidationError(
            "INVALID_CAL_CONTEXT", f"Select a valid {label} for REJECT CAL."
        )
    parsed = int(text)
    if not 1 <= parsed <= maximum:
        raise RejectValidationError(
            "INVALID_CAL_CONTEXT", f"Select a valid {label} for REJECT CAL."
        )
    return parsed


def read_reject_cal(cursor, production_date, workflow, shift_id, production_id):
    """Aggregate only the selected workflow's CAL-indexed transaction table."""
    workflow = str(workflow or "").strip().lower()
    if workflow not in WORKFLOW_TABLES:
        raise RejectValidationError(
            "INVALID_WORKFLOW", "Select Production or Depallet for REJECT CAL."
        )
    if not isinstance(production_date, date):
        try:
            production_date = date.fromisoformat(str(production_date or "").strip())
        except ValueError:
            raise RejectValidationError(
                "INVALID_PRODUCTION_DATE", "Enter a valid Production Date."
            ) from None
    shift_id = _positive_id(shift_id, "Shift")
    production_id = _positive_id(production_id, "Product / Lot")
    table = WORKFLOW_TABLES[workflow]
    cursor.execute(f"""
        SELECT reason.id AS RejectReasonID,reason.ReasonCode,
               reason.ReasonNameTH,reason.SortOrder,
               SUM(entry.Qty) AS Qty,COUNT_BIG(*) AS EntryCount
        FROM dbo.{table} AS entry
        JOIN dbo.RejectReason AS reason
          ON reason.id=entry.RejectReasonID
        WHERE entry.ProductionDate=? AND entry.ShiftID=?
          AND entry.ProductionID=?
        GROUP BY reason.id,reason.ReasonCode,reason.ReasonNameTH,
                 reason.SortOrder
        ORDER BY reason.SortOrder,reason.ReasonCode
    """, production_date, shift_id, production_id)
    totals = [
        dict(zip(
            [column[0] for column in cursor.description],
            row,
        ))
        for row in cursor.fetchall()
    ]
    return dict(
        workflow=workflow,
        table=table,
        production_date=production_date,
        shift_id=shift_id,
        production_id=production_id,
        totals=totals,
        total_qty=sum(int(row["Qty"] or 0) for row in totals),
        entry_count=sum(int(row["EntryCount"] or 0) for row in totals),
    )
