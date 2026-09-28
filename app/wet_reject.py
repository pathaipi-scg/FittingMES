"""Wet Reject manual entry (pre-curing) against the existing SB23 schema.

No DDL is issued here. dbo.TR_WetReject_Audit already records
WetRejectHistory on INSERT/UPDATE/DELETE; the application must not write
WetRejectHistory directly.
"""
from app.lots import rows

MAX_QTY = 2147483647
GROUP_COUNT = 3


def split_into_groups(items, groups=GROUP_COUNT):
    """Distribute items into `groups` near-equal, order-preserving slices."""
    items = list(items)
    base, extra = divmod(len(items), groups)
    result = []
    start = 0
    for index in range(groups):
        size = base + (1 if index < extra else 0)
        result.append(items[start:start + size])
        start += size
    return result


def read_active_reasons(cursor):
    cursor.execute("""SELECT ReasonCode, ReasonNameTH, SortOrder FROM dbo.WetRejectReasonMaster
        WHERE IsActive=1 ORDER BY SortOrder, ReasonCode""")
    return rows(cursor)


def read_wet_reject_events(cursor, production_id):
    cursor.execute("""SELECT wr.WetRejectID, wr.ProductionID, wr.ReasonCode, m.ReasonNameTH,
            wr.Qty, wr.RejectDateTime, wr.Remark, wr.CreatedAt, wr.UpdatedAt
        FROM dbo.WetReject wr
        LEFT JOIN dbo.WetRejectReasonMaster m ON m.ReasonCode=wr.ReasonCode
        WHERE wr.ProductionID=? ORDER BY wr.RejectDateTime DESC, wr.WetRejectID DESC""", production_id)
    return rows(cursor)


def read_daily_reason_totals(cursor, production_date):
    cursor.execute("""SELECT wr.ReasonCode, SUM(wr.Qty) AS Qty
        FROM dbo.WetReject wr
        JOIN dbo.ProductionLot p ON p.ProductionID=wr.ProductionID AND p.IsActive=1
        WHERE p.ProdDate=? GROUP BY wr.ReasonCode""", production_date)
    return {r['ReasonCode']: int(r['Qty'] or 0) for r in rows(cursor)}


def read_production_wet_reject_total(cursor, production_id):
    cursor.execute('''SELECT CounterQty,CuringQty FROM dbo.ProductionData
        WHERE ProductionID=?''', production_id)
    found = cursor.fetchone()
    if not found or found[0] is None or found[1] is None:
        return 0
    return max(int(found[0]) - int(found[1]), 0)


def build_wet_reject_context(cursor, production_id, production_date):
    reasons = read_active_reasons(cursor)
    events = read_wet_reject_events(cursor, production_id)
    daily_totals = read_daily_reason_totals(cursor, production_date)
    production_total = read_production_wet_reject_total(cursor, production_id)
    lot_totals = {}
    for event in events:
        lot_totals[event['ReasonCode']] = lot_totals.get(event['ReasonCode'], 0) + int(event['Qty'] or 0)
    if not any(reason['ReasonCode'] == 'R99' for reason in reasons):
        reasons.append(dict(ReasonCode='R99', ReasonNameTH='อื่นๆ / Other', SortOrder=999))
    summary = [dict(ReasonCode=reason['ReasonCode'], ReasonNameTH=reason['ReasonNameTH'],
                    Qty=lot_totals.get(reason['ReasonCode'], 0),
                    QtyPerDay=daily_totals.get(reason['ReasonCode'], 0)) for reason in reasons]
    return dict(wet_reject_reasons=reasons, wet_reject_events=events,
                wet_reject_summary=summary, wet_reject_total=production_total,
                wet_reject_reason_groups=split_into_groups(reasons),
                wet_reject_summary_groups=split_into_groups(summary))


def _quantity(value, label):
    text = str(value or '').strip()
    if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= MAX_QTY:
        raise ValueError(f'{label} must be a whole number from 1 to {MAX_QTY}.')
    return int(text)


def validate_wet_reject_input(data):
    reason_code = str(data.get('ReasonCode') or '').strip()
    if not reason_code or len(reason_code) > 10:
        raise ValueError('Choose an active Wet Reject Reason.')
    remark = str(data.get('Remark') or '').strip()
    if len(remark) > 1000:
        raise ValueError('Remark must be at most 1000 characters.')
    return dict(ReasonCode=reason_code, Qty=_quantity(data.get('Qty'), 'Qty'), Remark=remark or None)


def _require_active_lot(cursor, production_id):
    cursor.execute('''SELECT ProductionID FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK)
        WHERE ProductionID=? AND IsActive=1''', production_id)
    if not cursor.fetchone():
        raise ValueError('This Production Lot is no longer active.')


def _require_active_reason(cursor, reason_code):
    cursor.execute('''SELECT ReasonCode FROM dbo.WetRejectReasonMaster WITH (UPDLOCK,HOLDLOCK)
        WHERE ReasonCode=? AND IsActive=1''', reason_code)
    if not cursor.fetchone():
        raise ValueError('Choose an active Wet Reject Reason.')


def read_active_reason_codes(cursor):
    cursor.execute('''SELECT ReasonCode FROM dbo.WetRejectReasonMaster WITH (UPDLOCK,HOLDLOCK)
        WHERE IsActive=1''')
    return {row[0] for row in cursor.fetchall()}


def _entered_quantity(reason_code, raw_value):
    """Parse a batch grid Qty cell; blank/zero means 'not entered' (skip)."""
    text = str(raw_value or '').strip()
    if not text:
        return None
    if not text.isascii() or not text.isdigit() or not 0 <= int(text) <= MAX_QTY:
        raise ValueError(f'Qty for {reason_code} must be a whole number from 0 to {MAX_QTY}.')
    qty = int(text)
    return qty or None


def validate_wet_reject_batch_input(data):
    remark = str(data.get('Remark') or '').strip()
    if len(remark) > 1000:
        raise ValueError('Remark must be at most 1000 characters.')
    entries = []
    for reason_code, raw_qty in (data.get('Quantities') or {}).items():
        reason_code = str(reason_code or '').strip()
        qty = _entered_quantity(reason_code, raw_qty)
        if qty is not None:
            entries.append((reason_code, qty))
    if not entries:
        raise ValueError('Enter Qty for at least one Reject Reason.')
    return dict(Remark=remark or None, Entries=entries)


def save_wet_reject_batch(conn, production_id, data):
    """Reconcile a Lot's editable quantities without deleting event rows."""
    values = validate_wet_reject_batch_input(data)
    try:
        cursor = conn.cursor()
        _require_active_lot(cursor, production_id)
        active_codes = read_active_reason_codes(cursor)
        production_total = read_production_wet_reject_total(cursor, production_id)
        entries = [(code, qty) for code, qty in values['Entries'] if code != 'R99']
        if any(code not in active_codes for code, _ in entries):
            raise ValueError('Choose an active Wet Reject Reason.')
        classified = sum(qty for _, qty in entries)
        if classified > production_total:
            raise ValueError('Classified Wet Reject exceeds Total Wet Reject.')
        r99 = production_total - classified
        if r99:
            entries.append(('R99', r99))
        cursor.execute('''SELECT WetRejectID,ReasonCode FROM dbo.WetReject WITH (UPDLOCK,HOLDLOCK)
            WHERE ProductionID=? ORDER BY WetRejectID''', production_id)
        existing = rows(cursor)
        by_reason = {}
        for row in existing:
            by_reason.setdefault(row['ReasonCode'], []).append(row['WetRejectID'])
        wet_reject_ids = []
        for reason_code, qty in entries:
            ids = by_reason.pop(reason_code, [])
            if ids:
                wet_reject_id = ids.pop(0)
                cursor.execute('''UPDATE dbo.WetReject SET Qty=?,Remark=?,UpdatedAt=SYSDATETIME()
                    WHERE WetRejectID=? AND ProductionID=?''', qty, values['Remark'], wet_reject_id, production_id)
                wet_reject_ids.append(wet_reject_id)
            else:
                cursor.execute("""INSERT INTO dbo.WetReject
                    (ProductionID,ReasonCode,Qty,RejectDateTime,Remark)
                    VALUES (?, ?, ?, SYSDATETIME(), ?);
                    SELECT CAST(SCOPE_IDENTITY() AS bigint);""",
                    production_id, reason_code, qty, values['Remark'])
                cursor.nextset()
                wet_reject_ids.append(cursor.fetchone()[0])
        for ids in by_reason.values():
            for wet_reject_id in ids:
                cursor.execute('''UPDATE dbo.WetReject SET Qty=0,UpdatedAt=SYSDATETIME()
                    WHERE WetRejectID=? AND ProductionID=?''', wet_reject_id, production_id)
        conn.commit()
        return wet_reject_ids
    except Exception:
        conn.rollback()
        raise


def save_wet_reject(conn, production_id, data, wet_reject_id=None):
    values = validate_wet_reject_input(data)
    try:
        cursor = conn.cursor()
        _require_active_lot(cursor, production_id)
        _require_active_reason(cursor, values['ReasonCode'])
        if wet_reject_id is None:
            # dbo.WetReject has an enabled audit trigger; SQL Server forbids OUTPUT
            # without INTO on such tables. SCOPE_IDENTITY() must run in the SAME
            # batch as the INSERT (a separate execute() would reset the scope).
            cursor.execute("""INSERT INTO dbo.WetReject
                (ProductionID,ReasonCode,Qty,RejectDateTime,Remark)
                VALUES (?, ?, ?, SYSDATETIME(), ?);
                SELECT CAST(SCOPE_IDENTITY() AS bigint);""",
                production_id, values['ReasonCode'], values['Qty'], values['Remark'])
            cursor.nextset()
            wet_reject_id = cursor.fetchone()[0]
        else:
            cursor.execute("""SELECT WetRejectID FROM dbo.WetReject WITH (UPDLOCK,HOLDLOCK)
                WHERE WetRejectID=? AND ProductionID=?""", wet_reject_id, production_id)
            if not cursor.fetchone():
                raise ValueError('Wet Reject entry not found for this Lot.')
            # UpdatedAt drives dbo.TR_WetReject_Audit; history is not written here.
            cursor.execute("""UPDATE dbo.WetReject SET ReasonCode=?,Qty=?,
                Remark=?,UpdatedAt=SYSDATETIME() WHERE WetRejectID=? AND ProductionID=?""",
                values['ReasonCode'], values['Qty'], values['Remark'], wet_reject_id, production_id)
        conn.commit()
        return wet_reject_id
    except Exception:
        conn.rollback()
        raise
