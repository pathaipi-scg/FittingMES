"""Run-level Depallet REJECT CAL and FINAL snapshot persistence."""
import re

from app.lots import rows, lock_lots


MAX_BIGINT = 9223372036854775807
MAX_QTY = 2147483647


def _positive_id(value, label, maximum=MAX_BIGINT):
    text = str(value if value is not None else "").strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise ValueError(f"Select a valid {label}.")
    result = int(text)
    if not 1 <= result <= maximum:
        raise ValueError(f"Select a valid {label}.")
    return result


def _run(cursor, depallet_id, production_date=None, shift_id=None, lock=False):
    depallet_id = _positive_id(depallet_id, "Depallet Run")
    lock_hint = " WITH (UPDLOCK,HOLDLOCK)" if lock else ""
    cursor.execute(f"""
        SELECT d.DepalletID,d.ProductionID,d.DepalletDate,d.Shift,
               d.DepalletQty,d.GoodQty,d.LotNo,
               lot.ProdDate AS ProductionLotDate,lot.ProductFamilyID,lot.IsActive,
               shift.id AS ShiftID,shift.ShiftCode
        FROM dbo.Depallet AS d{lock_hint}
        JOIN dbo.ProductionLot AS lot
          ON lot.ProductionID=d.ProductionID
        LEFT JOIN dbo.ShiftMaster AS shift
          ON shift.ShiftCode=LTRIM(RTRIM(d.Shift)) AND shift.IsActive=1
        WHERE d.DepalletID=?
    """, depallet_id)
    found = rows(cursor)
    if len(found) != 1:
        raise ValueError("Select an existing Depallet run.")
    run = found[0]
    if not run["IsActive"]:
        raise ValueError("The Production Lot for this Depallet run is no longer active.")
    if run["ProductFamilyID"] is None:
        raise ValueError("The Production Lot has no Product Family.")
    if production_date is not None and run["DepalletDate"] != production_date:
        raise ValueError("The selected Depallet run does not belong to this Depallet Date.")
    if shift_id is not None and (
        run["ShiftID"] is None or int(run["ShiftID"]) != int(shift_id)
    ):
        raise ValueError("The selected Shift does not match this Depallet run.")
    if run["ShiftID"] is None:
        raise ValueError("This Depallet run has no active matching Shift.")
    return run


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


def _physical_total(run):
    depallet_qty, good_qty = run["DepalletQty"], run["GoodQty"]
    if depallet_qty is None or good_qty is None:
        raise ValueError("Save Depallet Qty and Good Qty before saving REJECT.")
    depallet_qty, good_qty = int(depallet_qty), int(good_qty)
    if depallet_qty < 0 or good_qty < 0:
        raise ValueError("Depallet Qty and Good Qty cannot be negative.")
    if good_qty > depallet_qty:
        raise ValueError("Production data is inconsistent: Good Qty exceeds Depallet Qty.")
    return depallet_qty - good_qty


def _raw_totals(cursor, run, lock=False):
    lock_hint = " WITH (HOLDLOCK)" if lock else ""
    cursor.execute(f"""
        SELECT COUNT_BIG(*) AS MismatchedRows
        FROM dbo.DepalletRejectEntry{lock_hint}
        WHERE DepalletID=? AND
              (ProductionDate<>? OR ProductionID<>? OR ShiftID<>?)
    """, run["DepalletID"], run["DepalletDate"], run["ProductionID"], run["ShiftID"])
    mismatch = rows(cursor)
    if mismatch and int(mismatch[0]["MismatchedRows"] or 0):
        raise ValueError("RAW REJECT entries do not match the selected Depallet run context.")
    cursor.execute(f"""
        SELECT RejectReasonID,SUM(CONVERT(bigint,Qty)) AS RawQty
        FROM dbo.DepalletRejectEntry{lock_hint}
        WHERE DepalletID=? AND ProductionDate=? AND ProductionID=? AND ShiftID=?
        GROUP BY RejectReasonID
    """, run["DepalletID"], run["DepalletDate"], run["ProductionID"], run["ShiftID"])
    return {
        int(item["RejectReasonID"]): int(item["RawQty"] or 0)
        for item in rows(cursor)
    }


def _validate_raw_reasons(raw_by_reason, applicable_ids):
    stale_ids = sorted(set(raw_by_reason) - applicable_ids)
    if stale_ids:
        raise ValueError(
            "RAW REJECT data contains Reject Reason IDs that are no longer "
            "active/applicable to this Product Family: "
            + ", ".join(str(reason_id) for reason_id in stale_ids)
        )


def read_depallet_reject_cal(cursor, depallet_id, production_date=None,
                             shift_id=None):
    """Read fresh RAW quantities for one Depallet run, regardless of Source."""
    run = _run(cursor, depallet_id, production_date, shift_id)
    reasons = _applicable_reasons(cursor, run["ProductFamilyID"])
    if not reasons:
        raise ValueError("No active Reject Reasons are configured for this Product Family.")
    quantities = _raw_totals(cursor, run)
    applicable_ids = {int(reason["RejectReasonID"]) for reason in reasons}
    _validate_raw_reasons(quantities, applicable_ids)
    return dict(
        depallet_id=int(run["DepalletID"]),
        production_id=int(run["ProductionID"]),
        depallet_date=run["DepalletDate"],
        shift_id=int(run["ShiftID"]),
        quantities=quantities,
        raw_total=sum(quantities.values()),
        total_reject=_physical_total(run),
    )


def read_depallet_reject_context(cursor, depallet_id):
    """Load applicable reasons, saved FINAL, Qty/Day and physical total."""
    run = _run(cursor, depallet_id)
    reasons = _applicable_reasons(cursor, run["ProductFamilyID"])
    cursor.execute("""
        SELECT DepalletRejectFinalID,Remark
        FROM dbo.DepalletRejectFinal
        WHERE DepalletID=?
    """, run["DepalletID"])
    headers = rows(cursor)
    if len(headers) > 1:
        raise RuntimeError("More than one Depallet REJECT FINAL exists for this run.")
    header = headers[0] if headers else None
    saved_qty = {}
    if header:
        cursor.execute("""
            SELECT RejectReasonID,RawQtyAtSave,FinalQty
            FROM dbo.DepalletRejectFinalDetail
            WHERE DepalletRejectFinalID=?
        """, header["DepalletRejectFinalID"])
        saved_qty = {int(item["RejectReasonID"]): item for item in rows(cursor)}

    cursor.execute("""
        SELECT detail.RejectReasonID,SUM(detail.FinalQty) AS QtyPerDay
        FROM dbo.Depallet AS run
        JOIN dbo.DepalletRejectFinal AS final ON final.DepalletID=run.DepalletID
        JOIN dbo.DepalletRejectFinalDetail AS detail
          ON detail.DepalletRejectFinalID=final.DepalletRejectFinalID
        WHERE run.DepalletDate=?
        GROUP BY detail.RejectReasonID
    """, run["DepalletDate"])
    daily = {
        int(item["RejectReasonID"]): int(item["QtyPerDay"] or 0)
        for item in rows(cursor)
    }

    for reason in reasons:
        reason_id = int(reason["RejectReasonID"])
        saved = saved_qty.get(reason_id)
        reason["FinalQty"] = int(saved["FinalQty"]) if saved else 0
        reason["RawQtyAtSave"] = int(saved["RawQtyAtSave"]) if saved else 0
        reason["QtyPerDay"] = daily.get(reason_id, 0)

    final_total = sum(reason["FinalQty"] for reason in reasons)
    total_reject = _physical_total(run)
    return dict(
        depallet_reject_reasons=reasons,
        depallet_reject_has_final=header is not None,
        depallet_reject_remark=(header or {}).get("Remark") or "",
        depallet_reject_total=total_reject,
        depallet_reject_final_classified=final_total,
        depallet_reject_difference=total_reject - final_total,
    )


def _submitted_quantities(raw, applicable_ids):
    submitted = raw.get("Quantities")
    if not isinstance(submitted, dict):
        raise ValueError("Submit the Depallet REJECT quantities.")
    quantities = {}
    for key, value in submitted.items():
        match = re.fullmatch(r"qty_([0-9]+)", str(key))
        if not match:
            raise ValueError("The submitted Depallet REJECT form is invalid.")
        reason_id = _positive_id(match.group(1), "Reject Reason")
        if reason_id not in applicable_ids:
            raise ValueError(
                "A submitted Reject Reason is inactive or does not apply to this Product Family."
            )
        text = str(value if value is not None else "").strip()
        if not text.isascii() or not text.isdigit() or len(text) > 19:
            raise ValueError("Every Reject Qty must be a non-negative whole number.")
        qty = int(text)
        if qty > MAX_QTY:
            raise ValueError(f"Reject Qty must not exceed {MAX_QTY}.")
        quantities[reason_id] = qty
    if set(quantities) != applicable_ids:
        raise ValueError("Submit a Qty for every active Reject Reason applicable to this run.")
    return quantities


def save_depallet_reject_final(conn, depallet_id, raw):
    """Atomically replace one run's FINAL snapshot without changing RAW."""
    depallet_id = _positive_id(depallet_id, "Depallet Run")
    remark = str(raw.get("Remark") or "").strip()
    if len(remark) > 1000:
        raise ValueError("Remark must be at most 1000 characters.")
    try:
        cursor = conn.cursor()
        lock_lots(cursor)
        run = _run(cursor, depallet_id, lock=True)
        reasons = _applicable_reasons(cursor, run["ProductFamilyID"], lock=True)
        if not reasons:
            raise ValueError("No active Reject Reasons are configured for this Product Family.")
        applicable_ids = {int(reason["RejectReasonID"]) for reason in reasons}
        quantities = _submitted_quantities(raw, applicable_ids)
        total_reject = _physical_total(run)
        raw_by_reason = _raw_totals(cursor, run, lock=True)
        _validate_raw_reasons(raw_by_reason, applicable_ids)
        raw_total = sum(raw_by_reason.get(reason_id, 0) for reason_id in applicable_ids)
        final_total = sum(quantities.values())
        if final_total > total_reject:
            raise ValueError("Final Classified Reject exceeds Total Reject.")
        unclassified = total_reject - final_total

        cursor.execute("""
            SELECT DepalletRejectFinalID
            FROM dbo.DepalletRejectFinal WITH (UPDLOCK,HOLDLOCK)
            WHERE DepalletID=?
        """, depallet_id)
        existing = rows(cursor)
        if len(existing) > 1:
            raise RuntimeError("More than one Depallet REJECT FINAL exists for this run.")
        if existing:
            final_id = int(existing[0]["DepalletRejectFinalID"])
            cursor.execute("""
                UPDATE dbo.DepalletRejectFinal
                SET ProductionID=?,DepalletDate=?,Remark=?,TotalRejectAtSave=?,
                    RawTotalQtyAtSave=?,FinalClassifiedQtyAtSave=?,
                    UnclassifiedQtyAtSave=?,UpdatedAt=SYSDATETIME()
                WHERE DepalletRejectFinalID=?
            """, run["ProductionID"], run["DepalletDate"], remark or None,
                total_reject, raw_total, final_total, unclassified, final_id)
        else:
            cursor.execute("""
                INSERT INTO dbo.DepalletRejectFinal
                    (DepalletID,ProductionID,DepalletDate,Remark,TotalRejectAtSave,
                     RawTotalQtyAtSave,FinalClassifiedQtyAtSave,UnclassifiedQtyAtSave)
                OUTPUT INSERTED.DepalletRejectFinalID
                VALUES (?,?,?,?,?,?,?,?)
            """, depallet_id, run["ProductionID"], run["DepalletDate"],
                remark or None, total_reject, raw_total, final_total, unclassified)
            inserted = cursor.fetchone()
            if inserted is None:
                raise RuntimeError("Depallet REJECT FINAL ID was not returned.")
            final_id = int(inserted[0])

        cursor.execute("""
            DELETE FROM dbo.DepalletRejectFinalDetail
            WHERE DepalletRejectFinalID=?
        """, final_id)
        for reason in reasons:
            reason_id = int(reason["RejectReasonID"])
            cursor.execute("""
                INSERT INTO dbo.DepalletRejectFinalDetail
                    (DepalletRejectFinalID,RejectReasonID,RawQtyAtSave,FinalQty)
                VALUES (?,?,?,?)
            """, final_id, reason_id, raw_by_reason.get(reason_id, 0),
                quantities[reason_id])
        conn.commit()
        return dict(
            depallet_reject_final_id=final_id,
            depallet_id=depallet_id,
            production_id=int(run["ProductionID"]),
            depallet_date=run["DepalletDate"],
            total_reject=total_reject,
            raw_total_qty_at_save=raw_total,
            final_classified_qty_at_save=final_total,
            unclassified_qty_at_save=unclassified,
        )
    except Exception:
        conn.rollback()
        raise
