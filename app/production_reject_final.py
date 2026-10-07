"""Whole-Lot Production REJECT reconciliation persistence."""
import re

from app.lots import rows


MAX_BIGINT = 9223372036854775807
MAX_QTY = 2147483647


def _positive_id(value, label):
    text = str(value if value is not None else "").strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise ValueError(f"Select a valid {label}.")
    result = int(text)
    if not 1 <= result <= MAX_BIGINT:
        raise ValueError(f"Select a valid {label}.")
    return result


def _active_lot(cursor, production_id, lock=False):
    lock_hint = " WITH (UPDLOCK,HOLDLOCK)" if lock else ""
    cursor.execute(f"""
        SELECT ProductionID,ProdDate AS ProductionDate,ProductFamilyID,LotNo
        FROM dbo.ProductionLot{lock_hint}
        WHERE ProductionID=? AND IsActive=1
    """, production_id)
    found = rows(cursor)
    if len(found) != 1:
        raise ValueError("This Production Lot is no longer active.")
    lot = found[0]
    if lot["ProductFamilyID"] is None:
        raise ValueError("This Production Lot has no Product Family.")
    return lot


def _applicable_reasons(cursor, product_family_id, lock=False):
    lock_hint = " WITH (HOLDLOCK)" if lock else ""
    cursor.execute(f"""
        SELECT reason.id AS RejectReasonID,reason.ReasonCode,
               reason.ReasonNameTH,reason.SortOrder
        FROM dbo.RejectReason AS reason{lock_hint}
        JOIN dbo.RejectCatalog AS catalog
          ON catalog.id=reason.RejectCatalogID AND catalog.IsActive=1
        JOIN dbo.RejectSourceScope AS scope
          ON scope.id=reason.RejectSourceScopeID AND scope.IsActive=1
        JOIN dbo.RejectReasonProductFamily AS mapping
          ON mapping.RejectReasonID=reason.id
        WHERE reason.IsActive=1 AND mapping.ProductFamilyID=?
        ORDER BY catalog.CatalogCode,reason.SortOrder,reason.ReasonCode
    """, product_family_id)
    return rows(cursor)


def _total_wet_reject(cursor, production_id, lock=False):
    lock_hint = " WITH (HOLDLOCK)" if lock else ""
    cursor.execute(f"""
        SELECT CounterQty,CuringQty
        FROM dbo.ProductionData{lock_hint}
        WHERE ProductionID=?
    """, production_id)
    found = rows(cursor)
    if len(found) != 1:
        raise ValueError(
            "Save Production Counter and Curing quantities before saving REJECT."
        )
    counter, curing = found[0]["CounterQty"], found[0]["CuringQty"]
    if counter is None or curing is None:
        raise ValueError(
            "Production Counter and Curing quantities are required to calculate Total Wet Reject."
        )
    counter, curing = int(counter), int(curing)
    if counter < 0 or curing < 0:
        raise ValueError("Production Counter and Curing quantities cannot be negative.")
    if curing > counter:
        raise ValueError(
            "Production data is inconsistent: Curing Qty exceeds Counter Qty."
        )
    return counter - curing


def _read_raw_totals(cursor, production_id, production_date, lock=False):
    lock_hint = " WITH (HOLDLOCK)" if lock else ""
    cursor.execute(f"""
        SELECT COUNT_BIG(*) AS MismatchedDateCount
        FROM dbo.ProductionRejectEntry{lock_hint}
        WHERE ProductionID=? AND ProductionDate<>?
    """, production_id, production_date)
    mismatched = rows(cursor)
    if mismatched and int(mismatched[0]["MismatchedDateCount"] or 0):
        raise ValueError(
            "RAW REJECT entries for this Production Lot have a Production Date "
            "that does not match the active Lot."
        )

    cursor.execute(f"""
        SELECT RejectReasonID,SUM(CONVERT(bigint,Qty)) AS RawQty
        FROM dbo.ProductionRejectEntry{lock_hint}
        WHERE ProductionID=? AND ProductionDate=?
        GROUP BY RejectReasonID
    """, production_id, production_date)
    return {
        int(item["RejectReasonID"]): int(item["RawQty"] or 0)
        for item in rows(cursor)
    }


def _validate_raw_reasons(raw_by_reason, applicable_ids):
    stale_ids = sorted(set(raw_by_reason) - applicable_ids)
    if stale_ids:
        reason_ids = ", ".join(str(reason_id) for reason_id in stale_ids)
        raise ValueError(
            "RAW REJECT data contains RejectReasonID(s) "
            f"{reason_ids} that are no longer valid/applicable for this "
            "Production Lot."
        )


def read_production_reject_cal(cursor, production_id, expected_date=None):
    """Read RAW totals for the whole active Lot, across all shifts and sources."""
    production_id = _positive_id(production_id, "Production Lot")
    lot = _active_lot(cursor, production_id)
    production_date = lot["ProductionDate"]
    if expected_date is not None and production_date != expected_date:
        raise ValueError(
            "The selected Production Lot does not belong to the requested Production Date."
        )
    reasons = _applicable_reasons(cursor, lot["ProductFamilyID"])
    applicable_ids = {int(reason["RejectReasonID"]) for reason in reasons}
    totals = _read_raw_totals(cursor, production_id, production_date)
    _validate_raw_reasons(totals, applicable_ids)
    total_wet_reject = None
    wet_reject_error = None
    try:
        total_wet_reject = _total_wet_reject(cursor, production_id)
    except ValueError as exc:
        wet_reject_error = str(exc)
    return dict(
        production_id=production_id,
        production_date=production_date,
        quantities=totals,
        raw_total=sum(totals.values()),
        total_wet_reject=total_wet_reject,
        wet_reject_error=wet_reject_error,
    )


def read_production_reject_context(cursor, production_id):
    """Load applicable reasons, saved FINAL values, daily totals, and wet total."""
    production_id = _positive_id(production_id, "Production Lot")
    lot = _active_lot(cursor, production_id)
    reasons = _applicable_reasons(cursor, lot["ProductFamilyID"])
    cursor.execute("""
        SELECT ProductionRejectFinalID,Remark
        FROM dbo.ProductionRejectFinal
        WHERE ProductionID=?
    """, production_id)
    headers = rows(cursor)
    if len(headers) > 1:
        raise RuntimeError("More than one Production REJECT FINAL exists for this Lot.")
    header = headers[0] if headers else None
    saved_qty = {}
    if header:
        cursor.execute("""
            SELECT RejectReasonID,RawQtyAtSave,FinalQty
            FROM dbo.ProductionRejectFinalDetail
            WHERE ProductionRejectFinalID=?
        """, header["ProductionRejectFinalID"])
        saved_qty = {
            int(item["RejectReasonID"]): item
            for item in rows(cursor)
        }

    cursor.execute("""
        SELECT detail.RejectReasonID,SUM(detail.FinalQty) AS QtyPerDay
        FROM dbo.ProductionLot AS lot
        JOIN dbo.ProductionRejectFinal AS final
          ON final.ProductionID=lot.ProductionID
        JOIN dbo.ProductionRejectFinalDetail AS detail
          ON detail.ProductionRejectFinalID=final.ProductionRejectFinalID
        WHERE lot.ProdDate=? AND lot.IsActive=1
        GROUP BY detail.RejectReasonID
    """, lot["ProductionDate"])
    daily = {
        int(item["RejectReasonID"]): int(item["QtyPerDay"] or 0)
        for item in rows(cursor)
    }

    wet_reject_error = None
    total_wet_reject = None
    try:
        total_wet_reject = _total_wet_reject(cursor, production_id)
    except ValueError as exc:
        wet_reject_error = str(exc)

    for reason in reasons:
        reason_id = int(reason["RejectReasonID"])
        saved = saved_qty.get(reason_id)
        reason["FinalQty"] = int(saved["FinalQty"]) if saved else 0
        reason["QtyPerDay"] = daily.get(reason_id, 0)
        reason["RawQtyAtSave"] = int(saved["RawQtyAtSave"]) if saved else 0

    final_classified = sum(int(reason["FinalQty"]) for reason in reasons)
    return dict(
        production_reject_reasons=reasons,
        production_reject_has_final=header is not None,
        production_reject_remark=(header or {}).get("Remark") or "",
        production_reject_total=total_wet_reject,
        production_reject_final_classified=final_classified,
        production_reject_difference=(
            total_wet_reject - final_classified
            if total_wet_reject is not None else None
        ),
        production_reject_error=wet_reject_error,
    )


def _submitted_quantities(raw, applicable_ids):
    submitted = raw.get("Quantities")
    if not isinstance(submitted, dict):
        raise ValueError("Submit the Production REJECT quantities.")
    quantities = {}
    for key, value in submitted.items():
        match = re.fullmatch(r"qty_([0-9]+)", str(key))
        if not match:
            raise ValueError("The submitted Production REJECT form is invalid.")
        reason_id = _positive_id(match.group(1), "Reject Reason")
        if reason_id not in applicable_ids:
            raise ValueError(
                "A submitted Reject Reason is inactive or does not apply to this Product Family."
            )
        text = str(value if value is not None else "").strip()
        if not text.isascii() or not text.isdigit() or len(text) > 19:
            raise ValueError(
                "Every Reject Qty must be a non-negative whole number."
            )
        qty = int(text)
        if qty > MAX_QTY:
            raise ValueError(
                f"Reject Qty must not exceed {MAX_QTY}."
            )
        quantities[reason_id] = qty
    if set(quantities) != applicable_ids:
        raise ValueError(
            "Submit a Qty for every active Reject Reason applicable to this Lot."
        )
    return quantities


def save_production_reject_final(conn, production_id, raw):
    """Atomically replace the whole-Lot FINAL snapshot without modifying RAW."""
    production_id = _positive_id(production_id, "Production Lot")
    remark = str(raw.get("Remark") or "").strip()
    if len(remark) > 1000:
        raise ValueError("Remark must be at most 1000 characters.")
    try:
        cursor = conn.cursor()
        lot = _active_lot(cursor, production_id, lock=True)
        reasons = _applicable_reasons(cursor, lot["ProductFamilyID"], lock=True)
        if not reasons:
            raise ValueError(
                "No active Reject Reasons are configured for this Product Family."
            )
        applicable_ids = {int(reason["RejectReasonID"]) for reason in reasons}
        quantities = _submitted_quantities(raw, applicable_ids)
        total_wet_reject = _total_wet_reject(cursor, production_id, lock=True)
        raw_by_reason = _read_raw_totals(
            cursor, production_id, lot["ProductionDate"], lock=True
        )
        _validate_raw_reasons(raw_by_reason, applicable_ids)
        raw_total = sum(
            raw_by_reason.get(reason_id, 0)
            for reason_id in applicable_ids
        )
        final_total = sum(quantities.values())
        if final_total > total_wet_reject:
            raise ValueError(
                "Final Classified Reject exceeds Total Wet Reject."
            )
        unclassified = total_wet_reject - final_total

        cursor.execute("""
            SELECT ProductionRejectFinalID
            FROM dbo.ProductionRejectFinal WITH (UPDLOCK,HOLDLOCK)
            WHERE ProductionID=?
        """, production_id)
        existing = rows(cursor)
        if len(existing) > 1:
            raise RuntimeError("More than one Production REJECT FINAL exists for this Lot.")
        if existing:
            final_id = int(existing[0]["ProductionRejectFinalID"])
            cursor.execute("""
                UPDATE dbo.ProductionRejectFinal
                SET ProductionDate=?,Remark=?,TotalWetRejectAtSave=?,
                    RawTotalQtyAtSave=?,FinalClassifiedQtyAtSave=?,
                    UnclassifiedQtyAtSave=?,UpdatedAt=SYSDATETIME()
                WHERE ProductionRejectFinalID=?
            """, lot["ProductionDate"], remark or None, total_wet_reject,
                raw_total, final_total, unclassified, final_id)
        else:
            cursor.execute("""
                INSERT INTO dbo.ProductionRejectFinal
                    (ProductionID,ProductionDate,Remark,TotalWetRejectAtSave,
                     RawTotalQtyAtSave,FinalClassifiedQtyAtSave,
                     UnclassifiedQtyAtSave)
                OUTPUT INSERTED.ProductionRejectFinalID
                VALUES (?,?,?,?,?,?,?)
            """, production_id, lot["ProductionDate"], remark or None,
                total_wet_reject, raw_total, final_total, unclassified)
            inserted = cursor.fetchone()
            if inserted is None:
                raise RuntimeError("Production REJECT FINAL ID was not returned.")
            final_id = int(inserted[0])

        cursor.execute("""
            DELETE FROM dbo.ProductionRejectFinalDetail
            WHERE ProductionRejectFinalID=?
        """, final_id)
        for reason in reasons:
            reason_id = int(reason["RejectReasonID"])
            cursor.execute("""
                INSERT INTO dbo.ProductionRejectFinalDetail
                    (ProductionRejectFinalID,RejectReasonID,RawQtyAtSave,FinalQty)
                VALUES (?,?,?,?)
            """, final_id, reason_id, raw_by_reason.get(reason_id, 0),
                quantities[reason_id])
        conn.commit()
        return dict(
            production_reject_final_id=final_id,
            production_id=production_id,
            production_date=lot["ProductionDate"],
            total_wet_reject=total_wet_reject,
            raw_total_qty_at_save=raw_total,
            final_classified_qty_at_save=final_total,
            unclassified_qty_at_save=unclassified,
        )
    except Exception:
        conn.rollback()
        raise
