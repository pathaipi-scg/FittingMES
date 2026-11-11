"""Material usage page backed by the existing authoritative SQL views."""
from decimal import Decimal, InvalidOperation
import re
from app.lots import rows
from app.prod_api import read_prod_records
from app.production_data import read_shift_rules, resolve_shift


def _effective_production_totals(cursor, production_date, lots):
    rules = read_shift_rules(cursor, production_date)
    totals = {}
    has_valid_start = False
    for lot in lots:
        has_valid_start = bool(lot.get('ProductionStartTime')) or has_valid_start
        master_id = lot.get('ShiftMasterID')
        if master_id is not None:
            lot['Shift'] = lot.get('ShiftCodeSnapshot') or lot.get('Shift')
        else:
            try:
                lot['Shift'] = resolve_shift(production_date, lot.get('ProductionStartTime'),
                                             lot.get('Shift'), rules)
            except (TypeError, ValueError):
                pass
        shift = str(lot.get('Shift'))
        if lot.get('CounterQty') is None or lot.get('CuringQty') is None:
            continue
        key = ('MASTER', master_id) if master_id is not None else ('LEGACY', shift)
        total = totals.setdefault(key, dict(
            ShiftMasterID=master_id, ShiftCode=shift,
            CounterQty=0, CuringQty=0, LotCount=0))
        total['CounterQty'] += lot['CounterQty']
        total['CuringQty'] += lot['CuringQty']
        total['LotCount'] += 1
    return totals if has_valid_start else None


def read_reporting_shifts(cursor, production_date):
    cursor.execute("SELECT OBJECT_ID(N'dbo.ShiftMasterVersion', N'U')")
    versioned = bool((cursor.fetchone() or (None,))[0])
    if versioned:
        cursor.execute("""WITH Ranked AS (
            SELECT ShiftMasterID,ShiftCode,ShiftName,IsActive,
                   ROW_NUMBER() OVER (
                       PARTITION BY ShiftMasterID
                       ORDER BY EffectiveFromDate DESC,VersionNumber DESC
                   ) AS VersionRank
            FROM dbo.ShiftMasterVersion
            WHERE EffectiveFromDate<=?
              AND (EffectiveToDate IS NULL OR EffectiveToDate>=?)
        )
        SELECT ShiftMasterID,ShiftCode,ShiftName
        FROM Ranked WHERE VersionRank=1 AND IsActive=1
        ORDER BY TRY_CONVERT(int,ShiftCode),ShiftCode,ShiftMasterID""",
            production_date, production_date)
    else:
        cursor.execute("""SELECT id AS ShiftMasterID,ShiftCode,ShiftName
            FROM dbo.ShiftMaster WHERE IsActive=1
            ORDER BY TRY_CONVERT(int,ShiftCode),ShiftCode,id""")
    return rows(cursor)


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
    shifts = read_reporting_shifts(cursor, production_date)
    cursor.execute("""SELECT CASE WHEN OBJECT_ID(N'dbo.vw_DailyProductionQtyLogical',N'V') IS NULL
        THEN 0 ELSE 1 END,
        CASE WHEN OBJECT_ID(N'dbo.vw_DailyMaterialUsageLogical',N'V') IS NULL
        THEN 0 ELSE 1 END,
        CASE WHEN OBJECT_ID(N'dbo.vw_DailyMaterialUsageCalcLogical',N'V') IS NULL
        THEN 0 ELSE 1 END""")
    logical_views = cursor.fetchone() or (0, 0, 0)
    lots = read_prod_records(cursor, production_date)
    production_totals = _effective_production_totals(cursor, production_date, lots)
    production_view = ('vw_DailyProductionQtyLogical' if logical_views[0]
                       else 'vw_DailyProductionQty')
    calc_view = ('vw_DailyMaterialUsageCalcLogical' if logical_views[2]
                 else 'vw_DailyMaterialUsageCalc')
    cursor.execute(f"""SELECT * FROM dbo.{production_view}
        WHERE ReportDate=? ORDER BY Shift""", production_date)
    quantities = {}
    quantity_by_code = {}
    for row in rows(cursor):
        code = str(row['Shift'])
        identity = row.get('ShiftMasterID')
        quantities[('MASTER', identity) if identity is not None else ('LEGACY', code)] = row
        quantity_by_code[code] = row
    cursor.execute(f'SELECT * FROM dbo.{calc_view} WHERE ReportDate=? ORDER BY Shift,SortOrder,MaterialUsageCode', production_date)
    shift_values = {}
    for row in rows(cursor):
        identity = row.get('ShiftMasterID')
        key = ((('MASTER', identity) if identity is not None else
                ('LEGACY', str(row['Shift']))), row['MaterialUsageCode'])
        if key in shift_values:
            raise ValueError('Duplicate usage records exist for this date and shift. Resolve them before editing.')
        shift_values[key] = row
    cursor.execute('''SELECT * FROM dbo.vw_DailyMaterialUsageTotalCalc
        WHERE ReportDate=? ORDER BY SortOrder,MaterialUsageCode''', production_date)
    daily_values = {row['MaterialUsageCode']: row for row in rows(cursor)}
    production_totals = production_totals or {}
    known_codes = {str(shift['ShiftCode']) for shift in shifts}
    for total in production_totals.values():
        code = str(total['ShiftCode'])
        if code not in known_codes:
            shifts.append(dict(
                ShiftMasterID=total['ShiftMasterID'],
                ShiftCode=code, ShiftName=code))
            known_codes.add(code)
    for code in quantity_by_code:
        if code not in known_codes:
            shifts.append(dict(ShiftMasterID=None, ShiftCode=code, ShiftName=code))
            known_codes.add(code)
    shift_sections = []
    for shift_config in shifts:
        shift_code = str(shift_config['ShiftCode'])
        identity = shift_config.get('ShiftMasterID')
        key = ('MASTER', identity) if identity is not None else ('LEGACY', shift_code)
        totals = production_totals.get(key)
        if totals is None:
            totals = production_totals.get(('LEGACY', shift_code))
        if totals is None:
            totals = quantity_by_code.get(shift_code, {})
        totals = (
            {field: 0 for field in ('CounterQty', 'CuringQty', 'LotCount')}
            if not totals else
            {field: totals.get(field) for field in (
                'CounterQty', 'CuringQty', 'LotCount')}
        )
        section_materials = []
        for material in materials:
            values = shift_values.get((key, material['MaterialUsageCode']))
            if values is None:
                values = shift_values.get(
                    (('LEGACY', shift_code), material['MaterialUsageCode']), {})
            section_materials.append(dict(material, **{
                field: values.get(field) for field in (
                    'RawQty', 'QtyPer1000Counter', 'QtyPer1000Curing',
                    'CounterPerUnit', 'SourceType')
            }))
        shift_sections.append(dict(
            shift=shift_code, ShiftMasterID=identity,
            ShiftName=shift_config.get('ShiftName'),
            totals=totals, materials=section_materials))
    shifts = shift_sections
    daily = [dict(material, **{key: daily_values.get(material['MaterialUsageCode'], {}).get(key)
             for key in ('RawQty', 'QtyPer1000Counter', 'QtyPer1000Curing', 'CounterPerUnit')}) for material in materials]
    if any(production_totals.values()):
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
    shift = str(shift).strip()
    if not shift:
        raise ValueError('Select a Shift.')
    try:
        cursor = conn.cursor()
        cursor.execute("""DECLARE @result int;
            EXEC @result = sys.sp_getapplock @Resource='FittingMES.MaterialUsage',
            @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=10000;
            SELECT @result;""")
        if cursor.fetchone()[0] < 0:
            raise ValueError('Material usage is being updated. Please retry.')
        shift_matches = [
            item for item in read_reporting_shifts(cursor, production_date)
            if str(item['ShiftCode']) == shift
        ]
        if len(shift_matches) != 1:
            raise ValueError('Select an active Shift configured for this Production Date.')
        shift_master_id = shift_matches[0]['ShiftMasterID']
        cursor.execute("""SELECT CASE WHEN COL_LENGTH(
            N'dbo.DailyMaterialUsage',N'ShiftMasterID') IS NULL
            THEN 0 ELSE 1 END""")
        has_shift_identity = bool((cursor.fetchone() or (0,))[0])
        cursor.execute('SELECT MaterialUsageCode FROM dbo.MaterialUsageMaster WHERE IsActive=1')
        active_codes = [r['MaterialUsageCode'] for r in rows(cursor)]
        values = validate_quantities(raw, active_codes)
        if has_shift_identity:
            cursor.execute("""SELECT MaterialUsageID FROM dbo.DailyMaterialUsage
                WITH (UPDLOCK,HOLDLOCK)
                WHERE ReportDate=? AND ShiftMasterID=?""",
                production_date, shift_master_id)
            headers = rows(cursor)
            if not headers:
                cursor.execute("""SELECT MaterialUsageID FROM dbo.DailyMaterialUsage
                    WITH (UPDLOCK,HOLDLOCK)
                    WHERE ReportDate=? AND ShiftMasterID IS NULL AND Shift=?""",
                    production_date, shift)
                headers = rows(cursor)
        else:
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
            if has_shift_identity:
                cursor.execute("""INSERT INTO dbo.DailyMaterialUsage
                    (ReportDate,Shift,ShiftMasterID)
                    OUTPUT INSERTED.MaterialUsageID VALUES (?,?,?)""",
                    production_date, shift, shift_master_id)
            else:
                cursor.execute("""INSERT INTO dbo.DailyMaterialUsage (ReportDate,Shift)
                    OUTPUT INSERTED.MaterialUsageID VALUES (?,?)""",
                    production_date, shift)
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
