from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.lots import lock_lots, rows
from app.production_clock import read_day_start_time, resolve_run_times, clock_display


def read_eligible_presses(cursor, product_family, product_code):
    if not product_family or not product_code:
        return []
    cursor.execute('''SELECT capability.PressCode, capability.PressName,
            capability.CurrentLine, capability.CurrentLineName, capability.StandardSpeed
        FROM dbo.vw_PressMcCapabilityMatrix AS capability
        JOIN dbo.EquipmentMaster AS equipment
          ON equipment.EquipmentCode=capability.PressCode
        WHERE capability.ProductFamily=? AND capability.ProductCode=?
          AND capability.CanProduce=1 AND equipment.IsActive=1
          AND equipment.EquipmentType='PRESS'
        ORDER BY equipment.DisplayOrder, capability.PressCode''', product_family, product_code)
    return rows(cursor)


def read_eligible_moulds(cursor, product_family, product_code, production_date=None):
    if not product_family or not product_code:
        return []
    cursor.execute('''SELECT moulds.MouldID, moulds.MouldNo, moulds.MouldName,
            moulds.ProductFamily, moulds.ProductCode,
            CAST(CASE WHEN EXISTS (
                SELECT 1
                FROM dbo.PressProduction AS assigned_press
                JOIN dbo.ProductionLot AS assigned_lot
                  ON assigned_lot.ProductionID=assigned_press.ProductionID
                WHERE assigned_lot.ProdDate=? AND assigned_lot.IsActive=1
                  AND assigned_press.MouldID=moulds.MouldID
            ) THEN 1 ELSE 0 END AS bit) AS AssignedOnProductionDate
        FROM dbo.vw_MouldList
        AS moulds
        WHERE moulds.ProductFamily=? AND moulds.ProductCode=? AND moulds.Status='ACTIVE'
        ORDER BY moulds.MouldNo''', production_date, product_family, product_code)
    return rows(cursor)


def read_press_production(cursor, production_id):
    cursor.execute('''SELECT pp.PressProductionID, pp.ProductionID, pp.MachineCode,
            equipment.EquipmentName AS MachineName, pp.DispatchQty, pp.CounterQty,
            pp.CuringQty, pp.MouldID, mould.MouldNo, mould.MouldName,
            pp.ProductionStartTime, pp.ProductionEndTime, pp.Remark, pp.CreatedAt, pp.UpdatedAt,
            usage.MouldUsageID, usage.ReconditionNo AS UsageReconditionNo,
            usage.UsageCycles, usage.UsageDateTime,
            COALESCE(SUM(CASE WHEN time_event.TimeType='SETUP' THEN time_event.DurationMin ELSE 0 END), 0) AS SetupMinutes,
            COALESCE(SUM(CASE WHEN time_event.TimeType='CHANGEOVER' THEN time_event.DurationMin ELSE 0 END), 0) AS ChgOverMinutes,
            COALESCE(SUM(CASE WHEN time_event.TimeType='IDLE' THEN time_event.DurationMin ELSE 0 END), 0) AS IdleMinutes,
            COALESCE(SUM(CASE WHEN time_event.TimeType='CLEAN' THEN time_event.DurationMin ELSE 0 END), 0) AS CleaningMinutes,
            COALESCE(SUM(CASE WHEN time_event.TimeType='BREAKDOWN' THEN time_event.DurationMin ELSE 0 END), 0) AS BreakdownMinutes
        FROM dbo.PressProduction AS pp
        JOIN dbo.EquipmentMaster AS equipment ON equipment.EquipmentCode=pp.MachineCode
        LEFT JOIN dbo.MouldMaster AS mould ON mould.MouldID=pp.MouldID
        LEFT JOIN dbo.MouldUsage AS usage ON usage.PressProductionID=pp.PressProductionID
                LEFT JOIN dbo.EquipmentTimeEvent AS time_event
                    ON time_event.ProductionID=pp.ProductionID
                 AND time_event.EquipmentCode=pp.MachineCode
                 AND time_event.SourceType='MANUAL'
                 AND time_event.TimeType IN ('SETUP','CHANGEOVER','IDLE','CLEAN','BREAKDOWN')
        WHERE pp.ProductionID=?
                GROUP BY pp.PressProductionID, pp.ProductionID, pp.MachineCode, equipment.EquipmentName,
                        pp.DispatchQty, pp.CounterQty, pp.CuringQty, pp.MouldID, mould.MouldNo, mould.MouldName,
                        pp.ProductionStartTime, pp.ProductionEndTime, pp.Remark, pp.CreatedAt, pp.UpdatedAt,
                        usage.MouldUsageID, usage.ReconditionNo, usage.UsageCycles, usage.UsageDateTime,
                        equipment.DisplayOrder
                ORDER BY equipment.DisplayOrder, pp.MachineCode''', production_id)
    return rows(cursor)


def _optional_quantity(value, label):
    text = str(value if value is not None else '').strip()
    if not text:
        return None
    if not text.isascii() or not text.isdigit() or int(text) > 2147483647:
        raise ValueError(f'{label} must be a whole number from 0 to 2147483647.')
    return int(text)


TIME_FIELDS = {
    'SETUP': 'SetupMinutes',
    'CHANGEOVER': 'ChgOverMinutes',
    'IDLE': 'IdleMinutes',
    'CLEAN': 'CleaningMinutes',
    'BREAKDOWN': 'BreakdownMinutes',
}


def calculate_smdt(start_datetime, end_datetime, manual_minutes):
    elapsed_minutes = ((end_datetime - start_datetime).total_seconds() / 60
                       if start_datetime is not None and end_datetime is not None else 0)
    downtime_minutes = sum((manual_minutes.get(time_type, Decimal('0'))
                            for time_type in TIME_FIELDS), Decimal('0'))
    return Decimal(str(elapsed_minutes)) - downtime_minutes


def _optional_minutes(value, label):
    text = str(value if value is not None else '').strip()
    if not text:
        return Decimal('0')
    try:
        minutes = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError(f'{label} must be a numeric minute value.') from None
    if not minutes.is_finite() or minutes < 0:
        raise ValueError(f'{label} must be zero or greater.')
    return minutes


def _manual_minutes(data):
    return {time_type: _optional_minutes(data.get(field), field.replace('Minutes', ''))
            for time_type, field in TIME_FIELDS.items()}


def _save_manual_minutes(cursor, production_id, machine_code, data):
    for time_type, duration in _manual_minutes(data).items():
        cursor.execute('''SELECT TimeEventID FROM dbo.EquipmentTimeEvent WITH (UPDLOCK,HOLDLOCK)
            WHERE ProductionID=? AND EquipmentCode=? AND TimeType=? AND SourceType='MANUAL' ''',
            production_id, machine_code, time_type)
        existing = cursor.fetchone()
        if existing:
            cursor.execute('''UPDATE dbo.EquipmentTimeEvent
                SET DurationMin=?, StartDateTime=NULL, EndDateTime=NULL, UpdatedAt=SYSDATETIME()
                WHERE TimeEventID=? AND ProductionID=? AND EquipmentCode=?
                  AND TimeType=? AND SourceType='MANUAL' ''',
                duration, existing[0], production_id, machine_code, time_type)
        else:
            cursor.execute('''INSERT INTO dbo.EquipmentTimeEvent
                (ProductionID,EquipmentCode,TimeType,DurationMin,SourceType)
                VALUES (?,?,?,?, 'MANUAL')''',
                production_id, machine_code, time_type, duration)


def validate_press_input(data, require_mould=True, production_date=None, day_start_time=None,
                         allow_incomplete=False):
    machine_code = str(data.get('MachineCode') or '').strip()
    if not machine_code or len(machine_code) > 20:
        raise ValueError('Choose an eligible Press.')
    mould_text = str(data.get('MouldID') or '').strip()
    if not mould_text and not require_mould:
        mould_id = None
    else:
        try:
            mould_id = int(mould_text)
        except (TypeError, ValueError):
            raise ValueError('Choose an eligible ACTIVE Mould.') from None
        if mould_id < 1:
            raise ValueError('Choose an eligible ACTIVE Mould.')
    counter = _optional_quantity(data.get('CounterQty'), 'Counter Qty')
    curing = _optional_quantity(data.get('CuringQty'), 'Curing Qty')
    if counter is None and not allow_incomplete:
        raise ValueError('Counter Qty is required for a Mould assignment.')
    if curing is not None and counter is not None and curing > counter:
        raise ValueError('Curing Qty cannot exceed Counter Qty.')
    remark = str(data.get('Remark') or '').strip()
    if len(remark) > 2000:
        raise ValueError('Remark must be at most 2000 characters.')
    if production_date is None or day_start_time is None:
        raise ValueError('Production Date is required for Start and End times.')
    start_time, end_time = resolve_run_times(
        production_date, data.get('ProductionStartTime'), data.get('ProductionEndTime'), day_start_time,
        allow_missing=allow_incomplete)
    return dict(MachineCode=machine_code, MouldID=mould_id,
                DispatchQty=_optional_quantity(data.get('DispatchQty'), 'Dispatch Qty'),
                CounterQty=counter, CuringQty=curing,
                ProductionStartTime=start_time, ProductionEndTime=end_time,
                Remark=remark or None)


def _require_active_lot(cursor, production_id):
    cursor.execute('''SELECT ProductionID, ProductFamily, ProductCode
        FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK)
        WHERE ProductionID=? AND IsActive=1''', production_id)
    found = cursor.fetchone()
    if not found:
        raise ValueError('This Production Lot is no longer active.')
    if not found[1]:
        raise ValueError('This legacy Lot has no confirmed Product Family. Resolve its product before assigning Press production.')
    return found[1], found[2]


def _validate_press(cursor, product_family, product_code, machine_code):
    cursor.execute('''SELECT 1
        FROM dbo.vw_PressMcCapabilityMatrix AS capability
        JOIN dbo.EquipmentMaster AS equipment
          ON equipment.EquipmentCode=capability.PressCode
        WHERE capability.PressCode=? AND capability.ProductFamily=?
          AND capability.ProductCode=? AND capability.CanProduce=1
          AND equipment.IsActive=1 AND equipment.EquipmentType='PRESS' ''',
        machine_code, product_family, product_code)
    if not cursor.fetchone():
        raise ValueError('This Press is inactive or is not enabled for the Lot Product.')


def _lock_and_validate_mould(cursor, product_family, product_code, mould_id):
    cursor.execute('''SELECT MouldID, Status, ProductFamily, ProductCode, CurrentReconditionNo
        FROM dbo.MouldMaster WITH (UPDLOCK,HOLDLOCK) WHERE MouldID=?''', mould_id)
    mould = cursor.fetchone()
    if not mould:
        raise ValueError('Mould not found.')
    if mould[1] != 'ACTIVE':
        raise ValueError('Only ACTIVE Moulds can be assigned to Press production.')
    if (mould[2], mould[3]) != (product_family, product_code):
        raise ValueError('Mould Product must match the Production Lot Product.')
    return mould[4]


def _lock_existing_usage_mould(cursor, product_family, product_code, mould_id):
    cursor.execute('''SELECT MouldID, ProductFamily, ProductCode
        FROM dbo.MouldMaster WITH (UPDLOCK,HOLDLOCK) WHERE MouldID=?''', mould_id)
    mould = cursor.fetchone()
    if not mould:
        raise ValueError('Mould not found.')
    if (mould[1], mould[2]) != (product_family, product_code):
        raise ValueError('Mould Product must match the Production Lot Product.')


def _ensure_mould_available_on_date(cursor, production_date, mould_id):
        cursor.execute('''SELECT TOP (1) assigned_press.PressProductionID
                FROM dbo.PressProduction AS assigned_press WITH (UPDLOCK,HOLDLOCK)
                JOIN dbo.ProductionLot AS assigned_lot WITH (UPDLOCK,HOLDLOCK)
                    ON assigned_lot.ProductionID=assigned_press.ProductionID
                WHERE assigned_lot.ProdDate=? AND assigned_lot.IsActive=1
                    AND assigned_press.MouldID=?''', production_date, mould_id)
        if cursor.fetchone():
                raise ValueError('This Mould is already assigned on the selected Production Date.')


def save_press_production(conn, production_id, data, press_production_id=None):
    try:
        cursor = conn.cursor()
        lock_lots(cursor)
        product_family, product_code = _require_active_lot(cursor, production_id)
        try:
            production_date = date.fromisoformat(str(data.get('ProductionDate') or ''))
        except ValueError:
            raise ValueError('Production Date is required.') from None
        day_start_time = read_day_start_time(cursor, production_date)
        values = validate_press_input(data, require_mould=press_production_id is None,
                          production_date=production_date, day_start_time=day_start_time,
                          allow_incomplete=press_production_id is None)
        _validate_press(cursor, product_family, product_code, values['MachineCode'])

        if press_production_id is None:
            _ensure_mould_available_on_date(cursor, production_date, values['MouldID'])
            current_recondition_no = _lock_and_validate_mould(
                cursor, product_family, product_code, values['MouldID'])
            cursor.execute('''SELECT PressProductionID FROM dbo.PressProduction WITH (UPDLOCK,HOLDLOCK)
                WHERE ProductionID=? AND MachineCode=?''', production_id, values['MachineCode'])
            if cursor.fetchone():
                raise ValueError('This Press already has a production row for this Lot.')
            cursor.execute('''INSERT INTO dbo.PressProduction
                (ProductionID,MachineCode,DispatchQty,CounterQty,CuringQty,MouldID,
                 ProductionStartTime,ProductionEndTime,Remark)
                OUTPUT INSERTED.PressProductionID VALUES (?,?,?,?,?,?,?,?,?)''',
                production_id, values['MachineCode'], values['DispatchQty'], values['CounterQty'],
                values['CuringQty'], values['MouldID'], values['ProductionStartTime'],
                values['ProductionEndTime'], values['Remark'])
            press_production_id = cursor.fetchone()[0]
            usage_recondition_no = current_recondition_no
            has_usage = False
        else:
            cursor.execute('''SELECT PressProductionID, MachineCode, MouldID, CounterQty
                FROM dbo.PressProduction WITH (UPDLOCK,HOLDLOCK)
                WHERE PressProductionID=? AND ProductionID=?''', press_production_id, production_id)
            existing = cursor.fetchone()
            if not existing:
                raise ValueError('Press Production row not found for this Lot.')
            if existing[2] != values['MouldID'] and (existing[3] or 0) > 0:
                raise ValueError('Mould assignment is locked after production usage begins.')
            cursor.execute('''SELECT ReconditionNo FROM dbo.MouldUsage WITH (UPDLOCK,HOLDLOCK)
                WHERE PressProductionID=?''', press_production_id)
            usage = cursor.fetchone()
            has_usage = usage is not None
            if has_usage and existing[2] != values['MouldID']:
                raise ValueError('Mould assignment is locked after production usage begins.')
            if values['MouldID'] is None and ((existing[3] or 0) > 0 or has_usage):
                raise ValueError('Mould assignment is locked after production usage begins.')
            if values['MouldID'] is None and (values['CounterQty'] or 0) > 0:
                raise ValueError('An ACTIVE Mould is required when Counter Qty is greater than zero.')
            if has_usage and values['MouldID'] is not None:
                _lock_existing_usage_mould(cursor, product_family, product_code, values['MouldID'])
                current_recondition_no = usage[0]
            else:
                current_recondition_no = (_lock_and_validate_mould(
                    cursor, product_family, product_code, values['MouldID'])
                    if values['MouldID'] is not None else None)
            usage_recondition_no = usage[0] if has_usage else current_recondition_no
            cursor.execute('''UPDATE dbo.PressProduction SET MachineCode=?,DispatchQty=?,CounterQty=?,
                CuringQty=?,MouldID=?,ProductionStartTime=?,ProductionEndTime=?,Remark=?,UpdatedAt=SYSDATETIME()
                WHERE PressProductionID=? AND ProductionID=?''',
                values['MachineCode'], values['DispatchQty'], values['CounterQty'], values['CuringQty'],
                values['MouldID'], values['ProductionStartTime'], values['ProductionEndTime'],
                values['Remark'], press_production_id, production_id)

        if (values['CounterQty'] or 0) > 0 or has_usage:
            if values['MouldID'] is None:
                raise ValueError('An ACTIVE Mould is required when Counter Qty is greater than zero.')
            cursor.execute('''SELECT MouldUsageID FROM dbo.MouldUsage WITH (UPDLOCK,HOLDLOCK)
                WHERE PressProductionID=?''', press_production_id)
            usage_row = cursor.fetchone()
            if usage_row:
                cursor.execute('''UPDATE dbo.MouldUsage SET UsageCycles=?
                    WHERE PressProductionID=?''', values['CounterQty'], press_production_id)
            else:
                cursor.execute('''INSERT INTO dbo.MouldUsage
                    (MouldID,PressProductionID,ReconditionNo,UsageCycles)
                    VALUES (?,?,?,?)''', values['MouldID'], press_production_id,
                    usage_recondition_no, values['CounterQty'])

            _save_manual_minutes(cursor, production_id, values['MachineCode'], data)

        conn.commit()
        return press_production_id
    except Exception:
        conn.rollback()
        raise


def build_press_production_context(cursor, lot):
    product_family = lot.get('ProductFamily')
    product_code = lot.get('ProductCode')
    rows_for_lot = read_press_production(cursor, lot['ProductionID'])
    day_start_time = read_day_start_time(cursor, lot['ProdDate'])
    for row in rows_for_lot:
        row['SMDTMinutes'] = calculate_smdt(
            row.get('ProductionStartTime'), row.get('ProductionEndTime'),
            {time_type: Decimal(str(row.get(field) or 0)) for time_type, field in TIME_FIELDS.items()})
    if not product_family:
        return dict(press_production=rows_for_lot, day_start_time=day_start_time,
                    eligible_presses=[], eligible_moulds=[],
                    press_product_error='This legacy Lot has no confirmed Product Family; Press/Mould assignment is unavailable.')
    return dict(press_production=rows_for_lot,
                day_start_time=day_start_time,
                eligible_presses=read_eligible_presses(cursor, product_family, product_code),
                eligible_moulds=read_eligible_moulds(cursor, product_family, product_code, lot['ProdDate']),
                press_product_error=None)