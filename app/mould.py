CHANGED_BY = 'FittingMES'
MOULD_COLUMNS = (
    'MouldID', 'MouldNo', 'MouldName', 'ProductFamily', 'ProductCode',
    'ProductName', 'Status', 'CurrentReconditionNo', 'CurrentAge',
    'LifetimeAge', 'UsageRecordCount', 'LastUsageDateTime', 'Remark',
    'CreatedAt', 'UpdatedAt',
)


def _rows(cursor):
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _procedure_row(cursor):
    columns = [column[0] for column in cursor.description]
    row = cursor.fetchone()
    return dict(zip(columns, row)) if row else None


def read_products(cursor):
    cursor.execute('''SELECT ProductFamily, ProductCode, ProductName
        FROM dbo.ProductCodeMaster
        WHERE IsActive=1
        ORDER BY ProductFamily, ProductCode''')
    return [dict(ProductFamily=row[0], ProductCode=row[1], ProductName=row[2])
            for row in cursor.fetchall()]


def read_mould_list(cursor, search='', family='', product='', status=''):
    search = str(search or '').strip()
    family = str(family or '').strip()
    product = str(product or '').strip()
    status = str(status or '').strip().upper()
    if status and status not in ('ACTIVE', 'RECONDITION', 'RETIRED', 'DENIED'):
        raise ValueError('Choose a valid Mould status.')
    product_family = product_code = None
    if product:
        parts = product.split('|', 1)
        if len(parts) != 2 or not all(parts):
            raise ValueError('Choose a valid Product.')
        product_family, product_code = parts
    cursor.execute('''SELECT MouldID, MouldNo, MouldName, ProductFamily, ProductCode,
            ProductName, Status, CurrentReconditionNo, CurrentAge, LifetimeAge,
            UsageRecordCount, LastUsageDateTime, Remark, CreatedAt, UpdatedAt
        FROM dbo.vw_MouldList
        WHERE (? = '' OR MouldNo LIKE ? OR MouldName LIKE ?)
                    AND (? = '' OR ProductFamily=?)
          AND (? IS NULL OR (ProductFamily=? AND ProductCode=?))
          AND (? = '' OR Status=?)
        ORDER BY MouldNo''',
        search, '%' + search + '%', '%' + search + '%',
        family, family,
        product_family, product_family, product_code, status, status)
    return _rows(cursor)


def read_mould_detail(cursor, mould_id):
    if not isinstance(mould_id, int) or mould_id < 1:
        raise ValueError('Invalid MouldID.')
    cursor.execute('''SELECT MouldID, MouldNo, MouldName, ProductFamily, ProductCode,
            ProductName, Status, CurrentReconditionNo, CurrentAge, LifetimeAge,
            UsageRecordCount, LastUsageDateTime, Remark, CreatedAt, UpdatedAt
        FROM dbo.vw_MouldList WHERE MouldID=?''', mould_id)
    rows = _rows(cursor)
    if not rows:
        raise ValueError('Mould not found.')
    mould = rows[0]
    cursor.execute('''SELECT FromStatus, ToStatus, ChangeType, Remark, ChangedBy, ChangedAt
        FROM dbo.MouldStatusHistory WHERE MouldID=? ORDER BY ChangedAt DESC, StatusHistoryID DESC''', mould_id)
    status_history = _rows(cursor)
    cursor.execute('''SELECT ReconditionNo, ReconditionDate, ReturnDate, CycleCountBefore,
            LifetimeCountAtRecondition, Remark
        FROM dbo.vw_MouldReconditionHistory WHERE MouldID=?
        ORDER BY ReconditionNo DESC''', mould_id)
    recondition_history = _rows(cursor)
    cursor.execute('''SELECT lot.LotNo, lot.ProductionID, lot.ProdDate,
            press.MachineCode, usage.ReconditionNo, usage.UsageCycles,
            usage.UsageDateTime, press.ProductionStartTime, press.ProductionEndTime
        FROM dbo.MouldUsage AS usage
        JOIN dbo.PressProduction AS press
          ON press.PressProductionID=usage.PressProductionID
        JOIN dbo.ProductionLot AS lot
          ON lot.ProductionID=press.ProductionID
        WHERE usage.MouldID=?
        ORDER BY usage.UsageDateTime DESC, usage.MouldUsageID DESC''', mould_id)
    usage_history = _rows(cursor)
    return dict(mould=mould, status_history=status_history,
                recondition_history=recondition_history, usage_history=usage_history)


def page_context(cursor, search='', family='', product='', status='', mould_id=None):
    products = read_products(cursor)
    moulds = read_mould_list(cursor, search, family, product, status)
    selected = None
    detail = None
    if mould_id is not None:
        detail = read_mould_detail(cursor, mould_id)
        if any(row['MouldID'] == mould_id for row in moulds):
            selected = detail['mould']
    return dict(products=products, moulds=moulds, selected=selected,
                status_history=(detail or {}).get('status_history', []),
                recondition_history=(detail or {}).get('recondition_history', []),
                usage_history=(detail or {}).get('usage_history', []))


def _run_mutation(conn, sql, params, refresh_id=None):
    try:
        cursor = conn.cursor()
        cursor.execute(sql, *params)
        procedure_row = _procedure_row(cursor)
        conn.commit()
        mould_id = refresh_id if refresh_id is not None else (procedure_row or {}).get('MouldID')
        if mould_id is None:
            raise RuntimeError('Mould procedure did not return the registered MouldID.')
        cursor.execute('''SELECT MouldID, MouldNo, MouldName, ProductFamily, ProductCode,
                ProductName, Status, CurrentReconditionNo, CurrentAge, LifetimeAge,
                UsageRecordCount, LastUsageDateTime, Remark, CreatedAt, UpdatedAt
            FROM dbo.vw_MouldList WHERE MouldID=?''', mould_id)
        rows = _rows(cursor)
        if not rows:
            raise RuntimeError('Mould procedure completed but the Mould could not be reloaded.')
        return rows[0]
    except Exception:
        conn.rollback()
        raise


def register_mould(conn, mould_name, product_family, product_code, remark=''):
    mould_name = str(mould_name or '').strip()
    product_family = str(product_family or '').strip()
    product_code = str(product_code or '').strip()
    remark = str(remark or '').strip()
    if not mould_name or len(mould_name) > 200:
        raise ValueError('MouldName is required and must be at most 200 characters.')
    if not product_family or len(product_family) > 30 or len(product_code) != 2:
        raise ValueError('Choose a valid Product Family and Product.')
    if len(remark) > 2000:
        raise ValueError('Remark must be at most 2000 characters.')
    return _run_mutation(conn, '''EXEC dbo.sp_Mould_Register
        @MouldName=?, @ProductFamily=?, @ProductCode=?, @Remark=?, @ChangedBy=?''',
        (mould_name, product_family, product_code, remark or None, CHANGED_BY))


def update_mould_info(conn, mould_id, mould_name, remark=''):
    mould_id = _valid_mould_id(mould_id)
    mould_name = str(mould_name or '').strip()
    remark = str(remark or '').strip()
    if not mould_name or len(mould_name) > 200:
        raise ValueError('MouldName is required and must be at most 200 characters.')
    if len(remark) > 2000:
        raise ValueError('Remark must be at most 2000 characters.')
    return _run_mutation(conn, '''EXEC dbo.sp_Mould_UpdateInfo
        @MouldID=?, @MouldName=?, @Remark=?''',
        (mould_id, mould_name, remark or None), mould_id)


def send_to_recondition(conn, mould_id, remark=''):
    return _recondition_change(conn, 'dbo.sp_Mould_SendToRecondition', mould_id, remark)


def return_from_recondition(conn, mould_id, remark=''):
    return _recondition_change(conn, 'dbo.sp_Mould_ReturnFromRecondition', mould_id, remark)


def _recondition_change(conn, procedure, mould_id, remark):
    mould_id = _valid_mould_id(mould_id)
    remark = str(remark or '').strip()
    if len(remark) > 2000:
        raise ValueError('Remark must be at most 2000 characters.')
    return _run_mutation(conn, f'''EXEC {procedure}
        @MouldID=?, @Remark=?, @ChangedBy=?''', (mould_id, remark or None, CHANGED_BY), mould_id)


def set_mould_status(conn, mould_id, new_status, remark=''):
    mould_id = _valid_mould_id(mould_id)
    new_status = str(new_status or '').strip().upper()
    remark = str(remark or '').strip()
    if new_status not in ('ACTIVE', 'RETIRED', 'DENIED'):
        raise ValueError('Choose ACTIVE, RETIRED or DENIED.')
    if len(remark) > 2000:
        raise ValueError('Remark must be at most 2000 characters.')
    return _run_mutation(conn, '''EXEC dbo.sp_Mould_SetStatus
        @MouldID=?, @NewStatus=?, @Remark=?, @ChangedBy=?''',
        (mould_id, new_status, remark or None, CHANGED_BY), mould_id)


def _valid_mould_id(mould_id):
    try:
        value = int(mould_id)
    except (TypeError, ValueError):
        raise ValueError('Invalid MouldID.') from None
    if value < 1:
        raise ValueError('Invalid MouldID.')
    return value