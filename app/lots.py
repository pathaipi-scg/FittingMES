"""Production lot transactions. All writers share a transaction-owned SQL lock."""
from datetime import datetime
from app.products import lot_prefix, month_start, require_product, read_mapping


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
        SELECT 1 FROM dbo.ProductionLot later WHERE later.IsActive=1
        AND ((p.ProductFamily IS NULL AND later.ProductFamily IS NULL AND later.LotPrefix=p.LotPrefix)
          OR (later.ProductFamily=p.ProductFamily AND later.ProductCode=p.ProductCode
              AND later.SequenceMonth=p.SequenceMonth))
        AND later.RunningNo>p.RunningNo
        ) THEN 0 ELSE 1 END AS CanVoid
        FROM dbo.ProductionLot p WHERE p.IsActive=1
        ORDER BY p.UpdatedAt DESC, p.ProductionID DESC""")
    return rows(cursor)


def require_available(cursor, selected, exclude_id=0):
    cursor.execute("""SELECT LotNo FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK)
        WHERE IsActive=1 AND ProdDate=? AND PlanName=? AND ProductionID<>?""",
        day(selected['StartTime']), selected['PlanName'], exclude_id)
    if cursor.fetchone():
        raise ValueError('This plan is already assigned to another active Lot.')


def next_running_no(cursor, prefix=None, product_family=None, product_code=None, plan_date=None):
    if product_family is None:
        # Unresolved historic lots keep their existing sequence for VOID only.
        cursor.execute('SELECT COALESCE(MAX(RunningNo), 0) + 1 FROM dbo.ProductionLot WHERE LotPrefix = ? AND IsActive=1 AND ProductFamily IS NULL', prefix)
    else:
        cursor.execute('''SELECT COALESCE(MAX(RunningNo), 0) + 1 FROM dbo.ProductionLot
            WHERE ProductFamily=? AND ProductCode=? AND SequenceMonth=? AND IsActive=1''',
            product_family, product_code, month_start(day(plan_date)))
    return int(cursor.fetchone()[0])


def history(cursor, production_id, old_lot, new_lot, old_plan, new_plan, change):
    cursor.execute("""INSERT INTO dbo.ProductionLotHistory
        (ProductionID,OldLotNo,NewLotNo,OldPlanName,NewPlanName,ChangeType)
        VALUES (?,?,?,?,?,?)""", production_id, old_lot, new_lot, old_plan, new_plan, change)


def insert_lot(conn, selected, product_code, prefix, running_no, product_family=None):
    try:
        if running_no is None or not 1 <= running_no <= 2147483647:
            raise ValueError('Running No must be a positive whole number.')
        if prefix != lot_prefix(product_family, product_code, day(selected['StartTime'])):
            raise ValueError('Lot prefix does not match the selected family/product and Plan Date.')
        cursor = conn.cursor()
        lock_lots(cursor)
        require_product(cursor, product_family, product_code)
        if read_mapping(cursor, selected['MaterialCode'][:8]) != (product_family, product_code):
            raise ValueError('Material mapping changed. Refresh before creating a lot.')
        require_available(cursor, selected)
        if running_no != next_running_no(cursor, prefix, product_family, product_code, selected["StartTime"]):
            raise ValueError('Running number has changed. Refresh and use the next suggested number.')
        lot_no = f'{prefix}{running_no:02d}'
        cursor.execute("""INSERT INTO dbo.ProductionLot
            (ProdDate,Shift,PlanName,MaterialCode,MaterialName,ProductCode,LotPrefix,RunningNo,LotNo,PlanQty,ProductFamily)
            OUTPUT INSERTED.ProductionID VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            day(selected['StartTime']), selected['Shift'], selected['PlanName'],
            selected['MaterialCode'], selected['MaterialName'], product_code,
            prefix, running_no, lot_no, selected['PlanCount'], product_family)
        production_id = cursor.fetchone()[0]
        history(cursor, production_id, None, lot_no, None, selected['PlanName'], 'CREATE')
        conn.commit()
        return production_id
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
            if next_running_no(cursor, lot['LotPrefix'], lot.get('ProductFamily'), lot['ProductCode'], lot['ProdDate']) - 1 != lot['RunningNo']:
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
