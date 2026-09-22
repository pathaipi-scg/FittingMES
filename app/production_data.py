"""Raw production measurements and derived reject values."""
import re
from datetime import time
from decimal import Decimal
from app.lots import lock_lots, rows, history


def calculate(counter, curing):
    if counter is None or curing is None:
        return dict(WetRejectQty=None, WetRejectPercent=None)
    reject = counter - curing
    return dict(WetRejectQty=reject,
                WetRejectPercent=(Decimal(reject) * 100 / Decimal(counter)) if counter else Decimal(0))


def validate(data):
    result = {}
    shift = str(data.get('Shift') or '').strip()
    if not shift or len(shift) > 10 or not shift.isascii():
        raise ValueError('Shift is required and must contain at most 10 ASCII characters.')
    result['Shift'] = shift
    for key in ('CounterQty', 'CuringQty'):
        value = str(data.get(key, '')).strip()
        if not re.fullmatch(r'[0-9]+', value) or len(value) > 10 or int(value) > 2147483647:
            raise ValueError('Counter and Curing Qty must be whole pieces from 0 to 2147483647.')
        result[key] = int(value)
    if result['CuringQty'] > result['CounterQty']:
        raise ValueError('Curing Qty cannot exceed Counter.')
    for key in ('ProductionStartTime', 'ProductionEndTime'):
        value = str(data.get(key) or '').strip()
        if not re.fullmatch(r'\d{2}:\d{2}(:\d{2})?', value):
            raise ValueError('Production start and end times are required (HH:MM).')
        try:
            result[key] = time.fromisoformat(value)
        except ValueError:
            raise ValueError('Enter valid production start and end times.') from None
    result['Remark'] = str(data.get('Remark') or '').strip()
    if len(result['Remark']) > 1000:
        raise ValueError('Remark must be at most 1000 characters.')
    return result


def read_production_data(cursor, production_id):
    cursor.execute('SELECT * FROM dbo.ProductionData WHERE ProductionID=?', production_id)
    found = rows(cursor)
    return found[0] if found else {}


def save_production_data(conn, production_id, raw):
    try:
        data = validate(raw)
        calculated = calculate(data['CounterQty'], data['CuringQty'])
        cursor = conn.cursor()
        lock_lots(cursor)
        cursor.execute('SELECT LotNo,PlanName FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK) WHERE ProductionID=? AND IsActive=1', production_id)
        lot = cursor.fetchone()
        if not lot:
            raise ValueError('This Lot is no longer active.')
        cursor.execute('SELECT ProductionID FROM dbo.ProductionData WITH (UPDLOCK,HOLDLOCK) WHERE ProductionID=?', production_id)
        exists = cursor.fetchone()
        values = (data['ProductionStartTime'], data['ProductionEndTime'],
                  data['CounterQty'], data['CuringQty'], data['Remark'], production_id)
        if exists:
            cursor.execute("""UPDATE dbo.ProductionData SET ProductionStartTime=?,
                ProductionEndTime=?,CounterQty=?,CuringQty=?,Remark=?,UpdatedAt=SYSDATETIME()
                WHERE ProductionID=?""", *values)
        else:
            cursor.execute("""INSERT INTO dbo.ProductionData
                (ProductionStartTime,ProductionEndTime,CounterQty,CuringQty,Remark,ProductionID)
                VALUES (?,?,?,?,?,?)""", *values)
        cursor.execute('UPDATE dbo.ProductionLot SET Shift=?,UpdatedAt=SYSDATETIME() WHERE ProductionID=?', data['Shift'], production_id)
        history(cursor, production_id, lot[0], lot[0], lot[1], lot[1], 'PRODUCTION_SAVE')
        conn.commit()
        return calculated
    except Exception:
        conn.rollback()
        raise
