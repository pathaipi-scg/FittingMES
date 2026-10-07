"""ID-first Fitting REJECT entry and lookup operations."""
from datetime import date
import re

from app.lots import rows


WORKFLOW_TABLES = {
    "production": "ProductionRejectEntry",
    "depallet": "DepalletRejectEntry",
}

MAX_BIGINT = 9223372036854775807


class RejectValidationError(ValueError):
    """Raised when a REJECT request is invalid against current DB state."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _invalid(code, message):
    raise RejectValidationError(code, message)


def _positive_int(value, code, label, maximum=MAX_BIGINT):
    text = str(value if value is not None else "").strip()
    if not re.fullmatch(r"[0-9]+", text):
        _invalid(code, f"{label} must be a positive whole number.")
    parsed = int(text)
    if not 1 <= parsed <= maximum:
        _invalid(code, f"{label} must be a positive whole number.")
    return parsed


def _production_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        _invalid("INVALID_PRODUCTION_DATE", "Enter a valid Production Date.")


def _workflow(value):
    workflow = str(value or "").strip().lower()
    if workflow not in WORKFLOW_TABLES:
        _invalid("INVALID_WORKFLOW", "Select Production or Depallet.")
    return workflow


def _fetch_one(cursor):
    found = rows(cursor)
    return found[0] if len(found) == 1 else None


def read_reject_page_data(cursor, production_date):
    """Read active workflow choices from the authoritative masters."""
    production_date = _production_date(production_date)

    cursor.execute("""
        SELECT id AS ShiftID, ShiftCode, ShiftName
        FROM dbo.ShiftMaster
        WHERE IsActive=1
        ORDER BY ShiftCode
    """)
    shifts = rows(cursor)

    cursor.execute("""
        SELECT id AS EquipmentID, EquipmentCode, EquipmentName, DisplayOrder
        FROM dbo.EquipmentMaster
        WHERE EquipmentType='LINE' AND IsActive=1
        ORDER BY DisplayOrder,EquipmentCode
    """)
    lines = rows(cursor)

    cursor.execute("""
        SELECT press.id AS EquipmentID, press.EquipmentCode,
               press_view.PressName AS EquipmentName, line.id AS LineEquipmentID,
               line.EquipmentCode AS LineEquipmentCode, press.DisplayOrder
        FROM dbo.vw_PressMcPressList AS press_view
        JOIN dbo.EquipmentMaster AS press
          ON press.EquipmentCode=press_view.PressCode
         AND press.EquipmentType='PRESS'
        JOIN dbo.EquipmentMaster AS line
          ON line.EquipmentCode=press_view.CurrentLine
         AND line.EquipmentType='LINE'
        WHERE press.IsActive=1 AND press_view.IsActive=1 AND line.IsActive=1
        ORDER BY press.DisplayOrder,press.EquipmentCode
    """)
    presses = rows(cursor)

    cursor.execute("""
        SELECT lot.ProductionID,lot.ProdDate AS ProductionDate,
               lot.Shift AS LotShiftCode,shift.id AS ShiftID,shift.ShiftCode,
               lot.ProductFamilyID,lot.ProductCode,lot.LotNo,
               family.ProductFamily,
               COALESCE(product.ProductName,product.ProductNameTH,lot.MaterialName)
                   AS ProductName
        FROM dbo.ProductionLot AS lot
        JOIN dbo.ShiftMaster AS shift
          ON shift.ShiftCode=LTRIM(RTRIM(lot.Shift))
         AND shift.IsActive=1
        JOIN dbo.ProductFamilyMaster AS family
          ON family.ProductFamilyID=lot.ProductFamilyID
        LEFT JOIN dbo.ProductCodeMaster AS product
          ON product.ProductFamilyID=lot.ProductFamilyID
         AND product.ProductCode=lot.ProductCode
        WHERE lot.ProdDate=? AND lot.IsActive=1
          AND lot.ProductFamilyID IS NOT NULL
        ORDER BY lot.LotSequence,lot.ProductionID
    """, production_date)
    lots_for_date = rows(cursor)

    cursor.execute("""
        SELECT mapping.ProductFamilyID,reason.id AS RejectReasonID,
               reason.ReasonCode,reason.ReasonNameTH,reason.SortOrder,
               reason.RejectSourceScopeID,scope.SourceScopeCode,
               catalog.CatalogCode
        FROM dbo.RejectReason AS reason
        JOIN dbo.RejectCatalog AS catalog
          ON catalog.id=reason.RejectCatalogID AND catalog.IsActive=1
        JOIN dbo.RejectSourceScope AS scope
          ON scope.id=reason.RejectSourceScopeID AND scope.IsActive=1
        JOIN dbo.RejectReasonProductFamily AS mapping
          ON mapping.RejectReasonID=reason.id
        WHERE reason.IsActive=1
        ORDER BY mapping.ProductFamilyID,catalog.CatalogCode,
                 reason.SortOrder,reason.ReasonCode
    """)
    reasons = rows(cursor)

    return dict(
        shifts=shifts,
        lines=lines,
        presses=presses,
        lots=lots_for_date,
        reasons=reasons,
    )


def read_reject_entries(cursor, production_date, workflow):
    """Read one workflow table only for the selected global date."""
    production_date = _production_date(production_date)
    workflow = _workflow(workflow)
    table = WORKFLOW_TABLES[workflow]
    cursor.execute(f"""
        SELECT entry.id AS EntryID,entry.ProductionDate,entry.ShiftID,
               shift.ShiftCode,entry.LineEquipmentID,
               line.EquipmentCode AS LineCode,entry.SourceEquipmentID,
               source.EquipmentCode AS SourceCode,
               CASE WHEN source.EquipmentType='LINE' THEN 'LINE'
                    ELSE 'PRESS' END AS SourceType,
               entry.ProductionID,lot.LotNo,lot.ProductCode,
               lot.ProductFamilyID,family.ProductFamily,
               COALESCE(product.ProductName,product.ProductNameTH,
                        lot.MaterialName) AS ProductName,
               entry.RejectReasonID,reason.ReasonCode,reason.ReasonNameTH,
               entry.RejectSourceScopeID,entry.Qty
        FROM dbo.{table} AS entry
        JOIN dbo.ShiftMaster AS shift ON shift.id=entry.ShiftID
        JOIN dbo.EquipmentMaster AS line ON line.id=entry.LineEquipmentID
        JOIN dbo.EquipmentMaster AS source ON source.id=entry.SourceEquipmentID
        JOIN dbo.ProductionLot AS lot ON lot.ProductionID=entry.ProductionID
        JOIN dbo.ProductFamilyMaster AS family
          ON family.ProductFamilyID=lot.ProductFamilyID
        LEFT JOIN dbo.ProductCodeMaster AS product
          ON product.ProductFamilyID=lot.ProductFamilyID
         AND product.ProductCode=lot.ProductCode
        JOIN dbo.RejectReason AS reason ON reason.id=entry.RejectReasonID
        WHERE entry.ProductionDate=?
        ORDER BY entry.Rectime DESC,entry.id DESC
    """, production_date)
    result = rows(cursor)
    if workflow == "depallet":
        for item in result:
            item["LineLabel"] = f'{item["LineCode"]} (DRY)'
            item["SourceLabel"] = (
                f'{item["SourceCode"]} (DRY)'
                if item["SourceType"] == "LINE" else item["SourceCode"]
            )
    else:
        for item in result:
            item["LineLabel"] = item["LineCode"]
            item["SourceLabel"] = item["SourceCode"]
    return result


def _validate_entry(cursor, raw):
    workflow = _workflow(raw.get("workflow"))
    production_date = _production_date(raw.get("production_date"))
    shift_id = _positive_int(raw.get("shift_id"), "INVALID_SHIFT", "Shift")
    line_id = _positive_int(raw.get("line_equipment_id"), "INVALID_LINE", "Line")
    production_id = _positive_int(
        raw.get("production_id"), "INVALID_PRODUCTION_LOT", "Product / Lot",
        maximum=9223372036854775807,
    )
    source_id = _positive_int(
        raw.get("source_equipment_id"), "INVALID_SOURCE", "Source",
        maximum=9223372036854775807,
    )
    reason_id = _positive_int(
        raw.get("reject_reason_id"), "INVALID_REASON", "Reject Reason",
        maximum=9223372036854775807,
    )
    posted_scope_id = _positive_int(
        raw.get("reject_source_scope_id"), "INVALID_SOURCE_SCOPE",
        "Reject Source Scope", maximum=9223372036854775807,
    )
    qty = _positive_int(
        raw.get("qty"), "INVALID_QTY", "Qty", maximum=2147483647
    )
    entry_id = raw.get("entry_id")
    if entry_id not in (None, ""):
        entry_id = _positive_int(
            entry_id, "INVALID_ENTRY", "Selected entry",
            maximum=9223372036854775807,
        )
    else:
        entry_id = None

    cursor.execute("""
        SELECT id AS ShiftID,ShiftCode
        FROM dbo.ShiftMaster
        WHERE id=? AND IsActive=1
    """, shift_id)
    shift = _fetch_one(cursor)
    if shift is None:
        _invalid("INVALID_SHIFT", "The selected Shift is no longer active.")

    lot_shift_match = ""
    lot_params = (production_id, production_date)
    if workflow == "depallet":
        lot_shift_match = "\n          AND LTRIM(RTRIM(lot.Shift))=?"
        lot_params += (shift["ShiftCode"],)
    cursor.execute(f"""
        SELECT lot.ProductionID,lot.ProductFamilyID,
               LTRIM(RTRIM(lot.Shift)) AS LotShiftCode
        FROM dbo.ProductionLot AS lot WITH (UPDLOCK,HOLDLOCK)
        WHERE lot.ProductionID=? AND lot.ProdDate=? AND lot.IsActive=1
          {lot_shift_match}
    """, *lot_params)
    lot = _fetch_one(cursor)
    if lot is None:
        _invalid(
            "INVALID_PRODUCTION_LOT",
            "Select an active Product / Lot for this Production Date.",
        )
    if lot["ProductFamilyID"] is None:
        _invalid(
            "MISSING_PRODUCT_FAMILY",
            "This Product / Lot has no Product Family; a REJECT entry cannot be saved.",
        )

    cursor.execute("""
        SELECT reason.id AS RejectReasonID,
               reason.RejectSourceScopeID,scope.SourceScopeCode
        FROM dbo.RejectReason AS reason
        JOIN dbo.RejectCatalog AS catalog
          ON catalog.id=reason.RejectCatalogID AND catalog.IsActive=1
        JOIN dbo.RejectSourceScope AS scope
          ON scope.id=reason.RejectSourceScopeID AND scope.IsActive=1
        JOIN dbo.RejectReasonProductFamily AS mapping
          ON mapping.RejectReasonID=reason.id
        WHERE reason.id=? AND reason.IsActive=1
          AND mapping.ProductFamilyID=?
    """, reason_id, lot["ProductFamilyID"])
    reason = _fetch_one(cursor)
    if reason is None:
        _invalid(
            "INVALID_REASON",
            "The selected Reject Reason is not active or does not apply to this Product Family.",
        )
    if reason["RejectSourceScopeID"] != posted_scope_id:
        _invalid(
            "INVALID_SOURCE_SCOPE",
            "Reject Source Scope does not match the selected Reject Reason.",
        )

    cursor.execute("""
        SELECT id AS EquipmentID,EquipmentCode
        FROM dbo.EquipmentMaster
        WHERE id=? AND EquipmentType='LINE' AND IsActive=1
    """, line_id)
    line = _fetch_one(cursor)
    if line is None:
        _invalid("INVALID_LINE", "The selected Line is no longer active.")

    scope_code = reason["SourceScopeCode"]
    if scope_code == "LINE":
        if source_id != line_id:
            _invalid(
                "INVALID_SOURCE",
                "A LINE-scope reason must use the selected Line as its Source.",
            )
    elif scope_code == "PRESS":
        cursor.execute("""
            SELECT press.id AS EquipmentID
            FROM dbo.vw_PressMcPressList AS press_view
            JOIN dbo.EquipmentMaster AS press
              ON press.EquipmentCode=press_view.PressCode
             AND press.EquipmentType='PRESS'
            JOIN dbo.EquipmentMaster AS mapped_line
              ON mapped_line.EquipmentCode=press_view.CurrentLine
             AND mapped_line.EquipmentType='LINE'
            WHERE press.id=? AND mapped_line.id=?
              AND press.IsActive=1 AND press_view.IsActive=1
              AND mapped_line.IsActive=1
        """, source_id, line_id)
        if _fetch_one(cursor) is None:
            _invalid(
                "INVALID_SOURCE",
                "Select an active Press configured for the selected Line.",
            )
    else:
        _invalid(
            "INVALID_SOURCE_SCOPE",
            "The selected Reject Reason has an unsupported Source Scope.",
        )

    return dict(
        workflow=workflow,
        table=WORKFLOW_TABLES[workflow],
        production_date=production_date,
        shift_id=shift_id,
        line_equipment_id=line_id,
        source_equipment_id=source_id,
        reject_source_scope_id=reason["RejectSourceScopeID"],
        production_id=production_id,
        reject_reason_id=reason_id,
        qty=qty,
        entry_id=entry_id,
    )


def save_reject_entry(conn, raw):
    """Validate and insert/update one workflow-owned quantity entry."""
    try:
        cursor = conn.cursor()
        values = _validate_entry(cursor, raw)
        table = values["table"]
        if values["entry_id"] is None:
            cursor.execute(f"""
                INSERT INTO dbo.{table}
                    (ProductionDate,ShiftID,LineEquipmentID,SourceEquipmentID,
                     RejectSourceScopeID,ProductionID,RejectReasonID,Qty)
                OUTPUT INSERTED.id
                VALUES (?,?,?,?,?,?,?,?)
            """, values["production_date"], values["shift_id"],
                values["line_equipment_id"], values["source_equipment_id"],
                values["reject_source_scope_id"], values["production_id"],
                values["reject_reason_id"], values["qty"])
            inserted = cursor.fetchone()
            if inserted is None:
                raise RuntimeError("REJECT entry ID was not returned by the INSERT.")
            entry_id = inserted[0]
        else:
            cursor.execute(
                f"SELECT id AS EntryID FROM dbo.{table} WITH (UPDLOCK,HOLDLOCK) "
                "WHERE id=? AND ProductionDate=?",
                values["entry_id"], values["production_date"],
            )
            if _fetch_one(cursor) is None:
                _invalid(
                    "ENTRY_NOT_FOUND",
                    "The selected entry does not belong to this REJECT workflow and date.",
                )
            cursor.execute(f"""
                UPDATE dbo.{table}
                SET ProductionDate=?,ShiftID=?,LineEquipmentID=?,
                    SourceEquipmentID=?,RejectSourceScopeID=?,ProductionID=?,
                    RejectReasonID=?,Qty=?
                WHERE id=? AND ProductionDate=?
            """, values["production_date"], values["shift_id"],
                values["line_equipment_id"], values["source_equipment_id"],
                values["reject_source_scope_id"], values["production_id"],
                values["reject_reason_id"], values["qty"], values["entry_id"],
                values["production_date"])
            if cursor.rowcount != 1:
                _invalid("ENTRY_NOT_FOUND", "The selected REJECT entry no longer exists.")
            entry_id = values["entry_id"]
        conn.commit()
        return entry_id
    except Exception:
        conn.rollback()
        raise
