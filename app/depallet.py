"""Depallet entry using the existing schema; no DDL or PIS writes."""
import re
from datetime import date
from decimal import Decimal
from app.lots import rows, lock_lots

MAX_QTY = 2147483647


def read_reasons(cursor):
    cursor.execute("""SELECT ReasonCode,ReasonNameTH,SortOrder FROM dbo.RejectReasonMaster
        WHERE IsActive=1 ORDER BY SortOrder,ReasonCode""")
    return rows(cursor)


def summary(quantity, good, rejects):
    total = sum(rejects.values())
    accounted = good + total
    return dict(RejectQty=total, RejectPct=Decimal(total) * 100 / quantity if quantity else Decimal(0),
                AccountedQty=accounted, DifferenceQty=quantity-accounted, IsBalanced=quantity == accounted)


def default_entry(lot, depallet_date):
    return dict(ProductionID=lot['ProductionID'], DepalletDate=depallet_date,
                Shift=lot.get('Shift') or '', LotNo=lot['LotNo'],
                DepalletQty='', GoodQty='', Remark='')


def read_rejects(cursor, depallet_id):
    cursor.execute("""SELECT r.ReasonCode,r.Qty,m.ReasonNameTH,m.IsActive,m.SortOrder
        FROM dbo.DepalletReject r LEFT JOIN dbo.RejectReasonMaster m ON m.ReasonCode=r.ReasonCode
        WHERE r.DepalletID=? ORDER BY m.SortOrder,r.ReasonCode""", depallet_id)
    return rows(cursor)


def read_context(cursor, lot, depallet_date):
    reasons = read_reasons(cursor)
    cursor.execute("""SELECT * FROM dbo.vw_DepalletValidation
        WHERE ProductionID=? AND DepalletDate=? ORDER BY DepalletID""", lot['ProductionID'], depallet_date)
    found = rows(cursor)
    if len(found) > 1:
        raise ValueError('Multiple Depallet records exist for this Lot and date. Resolve the duplicate before editing.')
    entry = found[0] if found else default_entry(lot, depallet_date)
    rejects = read_rejects(cursor, entry['DepalletID']) if found else []
    return dict(depallet=entry, reject_reasons=reasons,
                reject_values={r['ReasonCode']: r['Qty'] for r in rejects},
                inactive_rejects=[r for r in rejects if not r['IsActive']])


def quantity(value, label, blank_zero=False):
    text = str(value if value is not None else '').strip()
    if not text and blank_zero:
        return 0
    if not re.fullmatch(r'[0-9]+', text) or len(text) > 10 or int(text) > MAX_QTY:
        raise ValueError(label + ' must be whole pieces from 0 to 2147483647.')
    return int(text)


def validate(raw, active_codes, retained=None):
    retained = retained or {}
    try:
        depallet_date = date.fromisoformat(str(raw.get('DepalletDate', '')))
    except ValueError:
        raise ValueError('Enter a valid Depallet Date.') from None
    shift = str(raw.get('Shift') or '').strip()
    lot_no = str(raw.get('LotNo') or '').strip()
    remark = str(raw.get('Remark') or '').strip()
    if not shift or not shift.isascii() or len(shift) > 10:
        raise ValueError('Depallet Shift is required (maximum 10 ASCII characters).')
    if not lot_no or not lot_no.isascii() or len(lot_no) > 50:
        raise ValueError('Depallet Lot is required (maximum 50 ASCII characters).')
    if len(remark.encode('utf-16-le')) // 2 > 500:
        raise ValueError('Depallet Remark must be at most 500 characters.')
    supplied = raw.get('rejects', {})
    if not isinstance(supplied, dict):
        raise ValueError('Invalid reject quantities.')
    if set(supplied) - set(active_codes):
        raise ValueError('Reject reasons changed or are invalid. Reload the Depallet date.')
    rejects = {code: quantity(supplied.get(code, ''), code, blank_zero=True) for code in active_codes}
    rejects = {code: qty for code, qty in rejects.items() if qty}
    rejects.update(retained)
    data = dict(DepalletDate=depallet_date, Shift=shift, LotNo=lot_no,
                DepalletQty=quantity(raw.get('DepalletQty'), 'Depallet Qty'),
                GoodQty=quantity(raw.get('GoodQty'), 'Good Qty'), Remark=remark)
    calculated = summary(data['DepalletQty'], data['GoodQty'], rejects)
    if not calculated['IsBalanced']:
        raise ValueError('NOT BALANCED: Depallet Qty must equal Good Qty + Reject Qty.')
    return data, rejects


def save_depallet(conn, production_id, raw):
    try:
        cursor = conn.cursor()
        # Shares the established lot writer lock, including concurrent VOID.
        lock_lots(cursor)
        cursor.execute('SELECT * FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK) WHERE ProductionID=? AND IsActive=1', production_id)
        lots = rows(cursor)
        if not lots:
            raise ValueError('This Production Lot is no longer active.')
        lot = lots[0]
        reasons = read_reasons(cursor)
        active_codes = {reason['ReasonCode'] for reason in reasons}
        try:
            selected_date = date.fromisoformat(str(raw.get('DepalletDate', '')))
        except ValueError:
            raise ValueError('Enter a valid Depallet Date.') from None
        cursor.execute("""SELECT DepalletID FROM dbo.Depallet WITH (UPDLOCK,HOLDLOCK)
            WHERE ProductionID=? AND DepalletDate=?""", production_id, selected_date)
        existing = cursor.fetchall()
        if len(existing) > 1:
            raise ValueError('Multiple Depallet records exist for this Lot and date. Resolve the duplicate before saving.')
        depallet_id = existing[0][0] if existing else None
        old_rejects = read_rejects(cursor, depallet_id) if depallet_id is not None else []
        retained = {r['ReasonCode']: r['Qty'] for r in old_rejects if r['ReasonCode'] not in active_codes}
        data, rejects = validate(raw, active_codes, retained)
        if depallet_id is None:
            cursor.execute("""INSERT INTO dbo.Depallet
                (ProductionID,DepalletDate,Shift,LotNo,ProductFamily,ProductCode,MaterialCode,
                 MaterialName,DepalletQty,GoodQty,Remark)
                OUTPUT INSERTED.DepalletID VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                production_id, data['DepalletDate'], data['Shift'], data['LotNo'],
                lot.get('ProductFamily'), lot['ProductCode'], lot['MaterialCode'], lot.get('MaterialName'),
                data['DepalletQty'], data['GoodQty'], data['Remark'])
            depallet_id = cursor.fetchone()[0]
        else:
            cursor.execute("""UPDATE dbo.Depallet SET Shift=?,LotNo=?,DepalletQty=?,GoodQty=?,
                Remark=?,UpdatedAt=SYSDATETIME() WHERE DepalletID=?""",
                data['Shift'], data['LotNo'], data['DepalletQty'], data['GoodQty'], data['Remark'], depallet_id)
        old_codes = {r['ReasonCode'] for r in old_rejects}
        for code in sorted(active_codes):
            qty = rejects.get(code, 0)
            if not qty:
                if code in old_codes:
                    cursor.execute('DELETE FROM dbo.DepalletReject WHERE DepalletID=? AND ReasonCode=?', depallet_id, code)
            elif code in old_codes:
                cursor.execute('UPDATE dbo.DepalletReject SET Qty=?,UpdatedAt=SYSDATETIME() WHERE DepalletID=? AND ReasonCode=?', qty, depallet_id, code)
            else:
                cursor.execute('INSERT INTO dbo.DepalletReject (DepalletID,ReasonCode,Qty) VALUES (?,?,?)', depallet_id, code, qty)
        cursor.execute('SELECT * FROM dbo.vw_DepalletValidation WHERE DepalletID=?', depallet_id)
        saved = rows(cursor)
        if not saved or not saved[0]['IsBalanced']:
            raise ValueError('Depallet validation failed. Nothing was saved.')
        conn.commit()
        return saved[0]
    except Exception:
        conn.rollback()
        raise
