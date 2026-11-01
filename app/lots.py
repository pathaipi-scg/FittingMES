"""Production lot transactions. All writers share a transaction-owned SQL lock."""
from datetime import datetime
import re
from app.products import lot_prefix, month_start, require_product, read_mapping


RUNNING_SUFFIX_PATTERN = re.compile(r"[0-9]{2}\Z")


def rows(cursor):
    return [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]


def day(value):
    return value.date() if isinstance(value, datetime) else value


def lock_lots(cursor):
    cursor.execute("""DECLARE @result int;
        EXEC @result = sys.sp_getapplock @Resource='FittingMES.ProductionLot',
        @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=10000;
        SELECT @result;""")
    if cursor.fetchone()[0] < 0:
        raise ValueError('Lots are being updated. Please retry.')


def read_lots(cursor):
    cursor.execute("""SELECT p.*, CASE WHEN EXISTS (
        SELECT 1 FROM dbo.ProductionLot later
        WHERE ((p.ProductFamilyID IS NULL AND later.ProductFamilyID IS NULL
                AND later.LotPrefix=p.LotPrefix)
          OR (p.ProductFamilyID IS NOT NULL AND later.LotPrefix=p.LotPrefix
              AND later.SequenceMonth=p.SequenceMonth))
        AND later.RunningNo>p.RunningNo
        ) THEN 0 ELSE 1 END AS CanVoid
        FROM dbo.ProductionLot p WHERE p.IsActive=1
        ORDER BY p.ProdDate DESC, p.LotSequence, p.ProductionID""")
    return rows(cursor)


def require_available(cursor, selected, exclude_id=0):
    cursor.execute("""SELECT LotNo FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK)
        WHERE IsActive=1 AND ProdDate=? AND PlanName=? AND ProductionID<>?""",
        day(selected['StartTime']), selected['PlanName'], exclude_id)
    if cursor.fetchone():
        raise ValueError('This plan is already assigned to another active Lot.')


def next_running_no(cursor, prefix=None, product_family_id=None, product_code=None, plan_date=None):
    if product_family_id is None:
        cursor.execute('SELECT COALESCE(MAX(RunningNo), 0) + 1 FROM dbo.ProductionLot WHERE LotPrefix = ? AND ProductFamilyID IS NULL', prefix)
    else:
        if prefix is None:
            prefix = lot_prefix(cursor, product_family_id, product_code, day(plan_date))
        cursor.execute('''SELECT COALESCE(MAX(RunningNo), 0) + 1 FROM dbo.ProductionLot
            WHERE LotPrefix=? AND SequenceMonth=?''',
            prefix, month_start(day(plan_date)))
    return int(cursor.fetchone()[0])


def history(cursor, production_id, old_lot, new_lot, old_plan, new_plan, change):
    cursor.execute("""INSERT INTO dbo.ProductionLotHistory
        (ProductionID,OldLotNo,NewLotNo,OldPlanName,NewPlanName,ChangeType)
        VALUES (?,?,?,?,?,?)""", production_id, old_lot, new_lot, old_plan, new_plan, change)


def insert_lot(conn, selected, product_code, prefix, running_no, product_family_id=None):
    try:
        if not isinstance(running_no, str) or not RUNNING_SUFFIX_PATTERN.fullmatch(running_no):
            raise ValueError('Running No must contain exactly two ASCII digits from 01 to 99.')
        if not 1 <= int(running_no) <= 99:
            raise ValueError('Running No must be between 01 and 99.')
        running_no = int(running_no)
        cursor = conn.cursor()
        if prefix != lot_prefix(cursor, product_family_id, product_code, day(selected['StartTime'])):
            raise ValueError('Lot prefix does not match the selected family/product and Plan Date.')
        lock_lots(cursor)
        family_name = require_product(cursor, product_family_id, product_code)
        if read_mapping(cursor, selected['MaterialCode'][:8]) != (product_family_id, product_code):
            raise ValueError('Material mapping changed. Refresh before creating a lot.')
        require_available(cursor, selected)
        maximum = next_running_no(cursor, prefix, product_family_id, product_code, selected["StartTime"]) - 1
        if maximum >= 99:
            raise ValueError('Running number sequence is exhausted for this Product and month.')
        if running_no <= maximum:
            raise ValueError('Running number is no longer available. Refresh MAX and select a number greater than it.')
        lot_no = f'{prefix}{running_no:02d}'
        cursor.execute('''SELECT 1 FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK)
            WHERE LotNo=?''', lot_no)
        if cursor.fetchone():
            raise ValueError('This Lot No. already exists. Refresh MAX and select another number.')
        cursor.execute('''SELECT ISNULL(MAX(LotSequence),0)+1
            FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK) WHERE ProdDate=? AND IsActive=1''',
            day(selected['StartTime']))
        lot_sequence = int(cursor.fetchone()[0])
        cursor.execute("""INSERT INTO dbo.ProductionLot
            (ProdDate,Shift,PlanName,MaterialCode,MaterialName,ProductCode,LotPrefix,RunningNo,LotNo,
             PlanQty,ProductFamily,ProductFamilyID,LotSequence)
            OUTPUT INSERTED.ProductionID VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            day(selected['StartTime']), selected['Shift'], selected['PlanName'],
            selected['MaterialCode'], selected['MaterialName'], product_code,
            prefix, running_no, lot_no, selected['PlanCount'], family_name, product_family_id, lot_sequence)
        production_id = cursor.fetchone()[0]
        history(cursor, production_id, None, lot_no, None, selected['PlanName'], 'CREATE')
        conn.commit()
        return production_id
    except Exception:
        conn.rollback()
        raise


def reorder_lot(conn, production_date, production_id, direction):
    try:
        selected_date = day(production_date)
        if direction not in ('up', 'down'):
            raise ValueError('Direction must be up or down.')
        cursor = conn.cursor()
        lock_lots(cursor)
        cursor.execute("""SELECT ProductionID,LotSequence FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK)
            WHERE ProdDate=? AND IsActive=1 ORDER BY LotSequence,ProductionID""", selected_date)
        lots = rows(cursor)
        index = next((i for i, lot in enumerate(lots) if lot['ProductionID'] == production_id), None)
        if index is None:
            raise ValueError('This Production Lot is no longer active for the selected date.')
        neighbor_index = index - 1 if direction == 'up' else index + 1
        if neighbor_index < 0 or neighbor_index >= len(lots):
            conn.commit()
            return dict(moved=False, ProductionID=production_id, LotSequence=lots[index]['LotSequence'])
        lots[index], lots[neighbor_index] = lots[neighbor_index], lots[index]
        cursor.execute('SELECT ISNULL(MAX(LotSequence),0) FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK) WHERE ProdDate=?', selected_date)
        temporary_base = int(cursor.fetchone()[0]) + len(lots) + 1
        for offset, lot in enumerate(lots, start=1):
            cursor.execute('UPDATE dbo.ProductionLot SET LotSequence=? WHERE ProductionID=? AND ProdDate=?',
                           temporary_base + offset, lot['ProductionID'], selected_date)
        for sequence, lot in enumerate(lots, start=1):
            cursor.execute('UPDATE dbo.ProductionLot SET LotSequence=? WHERE ProductionID=? AND ProdDate=?',
                           sequence, lot['ProductionID'], selected_date)
        conn.commit()
        return dict(moved=True, ProductionID=production_id, LotSequence=neighbor_index + 1)
    except Exception:
        conn.rollback()
        raise


def update_lot(conn, production_id, selected=None, void=False):
    try:
        cursor = conn.cursor()
        lock_lots(cursor)
        cursor.execute('SELECT * FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK) WHERE ProductionID=? AND IsActive=1', production_id)
        found = rows(cursor)
        if not found:
            raise ValueError('This Lot is no longer active.')
        lot = found[0]
        if void:
            cursor.execute('''SELECT TOP (1) press.PressProductionID
                FROM dbo.PressProduction AS press
                LEFT JOIN dbo.MouldUsage AS usage
                  ON usage.PressProductionID=press.PressProductionID
                WHERE press.ProductionID=?
                  AND (usage.MouldUsageID IS NOT NULL
                       OR (press.MouldID IS NOT NULL AND press.CounterQty>0))
                ORDER BY press.PressProductionID''', production_id)
            if cursor.fetchone():
                raise ValueError('This Lot cannot be VOID because Press Production records exist; preserve their Mould usage attribution.')
            if next_running_no(cursor, lot['LotPrefix'], lot.get('ProductFamilyID'), lot['ProductCode'], lot['ProdDate']) - 1 != lot['RunningNo']:
                raise ValueError('Only the latest active running number can be VOID.')
            cursor.execute('UPDATE dbo.ProductionLot SET IsActive=0, UpdatedAt=SYSDATETIME() WHERE ProductionID=?', production_id)
            change, new_plan = 'VOID', lot['PlanName']
        else:
            if selected is None or day(selected['StartTime']) != day(lot['ProdDate']):
                raise ValueError('Replacement Plan must belong to the original Plan Date.')
            require_available(cursor, selected, production_id)
            cursor.execute("""UPDATE dbo.ProductionLot SET PlanName=?,MaterialCode=?,
                MaterialName=?,PlanQty=?,UpdatedAt=SYSDATETIME() WHERE ProductionID=?""",
                selected['PlanName'], selected['MaterialCode'],
                selected['MaterialName'], selected['PlanCount'], production_id)
            change, new_plan = 'PLAN_CHANGE', selected['PlanName']
        history(cursor, production_id, lot['LotNo'], lot['LotNo'], lot['PlanName'], new_plan, change)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
