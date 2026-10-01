"""Material usage page backed by the existing authoritative SQL views."""
from decimal import Decimal, InvalidOperation
import re
from app.lots import rows
from app.prod_api import read_prod_records
from app.production_data import read_shift_rules, resolve_shift


def _effective_production_totals(cursor, production_date, lots):
    rules = read_shift_rules(cursor, production_date)
    totals = {shift: dict(CounterQty=0, CuringQty=0, LotCount=0) for shift in ('1', '2')}
    has_valid_start = False
    for lot in lots:
        try:
            has_valid_start = bool(lot.get('ProductionStartTime')) or has_valid_start
            lot['Shift'] = resolve_shift(production_date, lot.get('ProductionStartTime'),
                                         lot.get('Shift'), rules)
        except (TypeError, ValueError):
            pass
        shift = str(lot.get('Shift'))
        if shift not in totals or lot.get('CounterQty') is None or lot.get('CuringQty') is None:
            continue
        totals[shift]['CounterQty'] += lot['CounterQty']
        totals[shift]['CuringQty'] += lot['CuringQty']
        totals[shift]['LotCount'] += 1
    return totals if has_valid_start else None


def _ratio(raw_qty, denominator, scale=1000):
    if raw_qty is None or not denominator:
        return None
    return raw_qty * scale / denominator


def _counter_per_unit(raw_qty, counter):
    if raw_qty is None or not raw_qty:
        return None
    return counter / raw_qty


def read_usage_context(cursor, production_date):
    cursor.execute("""SELECT MaterialUsageCode,MaterialNameTH,MaterialNameEN,Unit,SortOrder,UsageType
        FROM dbo.MaterialUsageMaster WHERE IsActive=1 ORDER BY SortOrder,MaterialUsageCode""")
    materials = rows(cursor)
    lots = read_prod_records(cursor, production_date)
    production_totals = _effective_production_totals(cursor, production_date, lots)
    cursor.execute('SELECT * FROM dbo.vw_DailyProductionQty WHERE ReportDate=? ORDER BY Shift', production_date)
    quantities = {str(row['Shift']): row for row in rows(cursor)}
    cursor.execute('SELECT * FROM dbo.vw_DailyMaterialUsageCalc WHERE ReportDate=? ORDER BY Shift,SortOrder,MaterialUsageCode', production_date)
    shift_values = {}
    for row in rows(cursor):
        key = (str(row['Shift']), row['MaterialUsageCode'])
        if key in shift_values:
            raise ValueError('Duplicate usage records exist for this date and shift. Resolve them before editing.')
        shift_values[key] = row
    cursor.execute('SELECT * FROM dbo.vw_DailyMaterialUsageTotalCalc WHERE ReportDate=? ORDER BY SortOrder,MaterialUsageCode', production_date)
    daily_values = {row['MaterialUsageCode']: row for row in rows(cursor)}
    effective_totals = production_totals or {shift: quantities.get(shift, {}) for shift in ('1', '2')}
    shifts = [dict(shift=shift, totals=effective_totals[shift], materials=[
        dict(material, **{key: shift_values.get((shift, material['MaterialUsageCode']), {}).get(key)
             for key in ('RawQty', 'QtyPer1000Counter', 'QtyPer1000Curing', 'CounterPerUnit', 'SourceType')})
        for material in materials]) for shift in ('1', '2')]
    daily = [dict(material, **{key: daily_values.get(material['MaterialUsageCode'], {}).get(key)
             for key in ('RawQty', 'QtyPer1000Counter', 'QtyPer1000Curing', 'CounterPerUnit')}) for material in materials]
    if production_totals:
        for section in shifts:
            for material in section['materials']:
                material['QtyPer1000Counter'] = _ratio(material['RawQty'], section['totals']['CounterQty'])
                material['QtyPer1000Curing'] = _ratio(material['RawQty'], section['totals']['CuringQty'])
                material['CounterPerUnit'] = _counter_per_unit(material['RawQty'], section['totals']['CounterQty'])
        daily_totals = {key: sum(section['totals'][key] for section in shifts) for key in ('CounterQty', 'CuringQty', 'LotCount')}
        for material in daily:
            material['QtyPer1000Counter'] = _ratio(material['RawQty'], daily_totals['CounterQty'])
            material['QtyPer1000Curing'] = _ratio(material['RawQty'], daily_totals['CuringQty'])
            material['CounterPerUnit'] = _counter_per_unit(material['RawQty'], daily_totals['CounterQty'])
    return dict(lots=lots, shifts=shifts, daily=daily)


def validate_quantities(raw, active_codes):
    if set(raw) - set(active_codes):
        raise ValueError('Material list changed. Refresh before saving.')
    values = {}
    for code, value in raw.items():
        text = str(value).strip()
        if not text:
            values[code] = None
            continue
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,3})?', text):
            raise ValueError('Usage quantities must be nonnegative numbers with at most 3 decimal places.')
        try:
            qty = Decimal(text)
        except InvalidOperation:
            raise ValueError('Invalid usage quantity.') from None
        if qty > Decimal('999999999999999.999'):
            raise ValueError('Usage quantity exceeds the supported range.')
        values[code] = qty
    return values


def save_usage(conn, production_date, shift, raw):
    if shift not in ('1', '2'):
        raise ValueError('Select Shift 1 or Shift 2.')
    try:
        cursor = conn.cursor()
        cursor.execute("""DECLARE @result int;
            EXEC @result = sys.sp_getapplock @Resource='FittingMES.MaterialUsage',
            @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=10000;
            SELECT @result;""")
        if cursor.fetchone()[0] < 0:
            raise ValueError('Material usage is being updated. Please retry.')
        cursor.execute('SELECT MaterialUsageCode FROM dbo.MaterialUsageMaster WHERE IsActive=1')
        active_codes = [r['MaterialUsageCode'] for r in rows(cursor)]
        values = validate_quantities(raw, active_codes)
        cursor.execute("""SELECT MaterialUsageID FROM dbo.DailyMaterialUsage WITH (UPDLOCK,HOLDLOCK)
            WHERE ReportDate=? AND Shift=?""", production_date, shift)
        headers = rows(cursor)
        if len(headers) > 1:
            raise ValueError('Duplicate usage headers exist for this date and shift.')
        if not headers and not any(value is not None for value in values.values()):
            conn.rollback()
            return
        if headers:
            usage_id = headers[0]['MaterialUsageID']
        else:
            cursor.execute("""INSERT INTO dbo.DailyMaterialUsage (ReportDate,Shift)
                OUTPUT INSERTED.MaterialUsageID VALUES (?,?)""", production_date, shift)
            usage_id = cursor.fetchone()[0]
        cursor.execute('SELECT MaterialUsageCode,SourceType FROM dbo.DailyMaterialUsageDetail WHERE MaterialUsageID=?', usage_id)
        details = rows(cursor)
        if len({r['MaterialUsageCode'] for r in details}) != len(details):
            raise ValueError('Duplicate usage material rows exist. Resolve them before saving.')
        existing = {r['MaterialUsageCode']: r for r in details}
        for code, qty in values.items():
            if code in existing and existing[code]['SourceType'] != 'MANUAL':
                raise ValueError('A material quantity is managed by another source. Refresh before editing.')
            if qty is None:
                cursor.execute('DELETE FROM dbo.DailyMaterialUsageDetail WHERE MaterialUsageID=? AND MaterialUsageCode=?', usage_id, code)
            elif code in existing:
                cursor.execute("""UPDATE dbo.DailyMaterialUsageDetail SET Qty=?,UpdatedAt=SYSDATETIME()
                    WHERE MaterialUsageID=? AND MaterialUsageCode=?""", qty, usage_id, code)
            else:
                # SourceType uses the existing database default MANUAL.
                cursor.execute('INSERT INTO dbo.DailyMaterialUsageDetail (MaterialUsageID,MaterialUsageCode,Qty) VALUES (?,?,?)', usage_id, code, qty)
        cursor.execute('UPDATE dbo.DailyMaterialUsage SET UpdatedAt=SYSDATETIME() WHERE MaterialUsageID=?', usage_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
