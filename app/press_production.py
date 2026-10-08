from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.lots import lock_lots, rows
from app.production_clock import read_day_start_time, resolve_run_times, clock_display


def read_eligible_presses(cursor, product_family_id, product_code, production_date=None,
                          shift_code=None, exclude_press_production_id=None):
    if not product_family_id or not product_code:
        return []
    availability_fields = ''
    availability_params = ()
    if production_date is not None and shift_code is not None:
        if not _shift_schema_available(cursor):
            raise ValueError('Shift-aware Press Production requires database migration 027.')
        cursor.execute('''SELECT id FROM dbo.ShiftMaster
            WHERE ShiftCode=? AND IsActive=1''', str(shift_code).strip())
        shift = cursor.fetchone()
        if not shift:
            raise ValueError('Choose an active Shift.')
        availability_fields = ''',
            CAST(CASE WHEN EXISTS (
                SELECT 1 FROM dbo.PressProduction AS assigned_press
                JOIN dbo.ProductionLot AS assigned_lot
                  ON assigned_lot.ProductionID=assigned_press.ProductionID
                WHERE assigned_lot.ProdDate=?
                  AND assigned_press.MachineCode=capability.PressCode
                  AND assigned_press.ReleasedAt IS NULL
                  AND (assigned_press.ShiftMasterID=? OR assigned_press.ShiftMasterID IS NULL)
                  AND assigned_press.PressProductionID<>COALESCE(?,0)
            ) THEN 1 ELSE 0 END AS bit) AS AssignedOnProductionDate'''
        availability_params = (production_date, shift[0], exclude_press_production_id)
    cursor.execute('''SELECT capability.PressCode, capability.PressName,
            capability.CurrentLine, capability.CurrentLineName, capability.StandardSpeed
            {availability_fields}
        FROM dbo.vw_PressMcCapabilityMatrix AS capability
        JOIN dbo.EquipmentMaster AS equipment
          ON equipment.EquipmentCode=capability.PressCode
        WHERE capability.ProductFamilyID=? AND capability.ProductCode=?
          AND capability.CanProduce=1 AND equipment.IsActive=1
          AND equipment.EquipmentType='PRESS'
        ORDER BY equipment.DisplayOrder, capability.PressCode'''.format(
            availability_fields=availability_fields),
        *availability_params, product_family_id, product_code)
    return rows(cursor)


def read_active_shifts(cursor):
    cursor.execute('''SELECT ShiftCode, ShiftName
        FROM dbo.ShiftMaster
        WHERE IsActive=1
        ORDER BY ShiftCode''')
    return rows(cursor)


def _shift_schema_available(cursor):
    cursor.execute("""SELECT CASE WHEN COL_LENGTH(
        N'dbo.PressProduction', N'ShiftMasterID') IS NULL THEN 0 ELSE 1 END""")
    row = cursor.fetchone()
    return bool(row and row[0])


def read_eligible_moulds(cursor, product_family_id, product_code, production_date=None,
                         shift_code=None, exclude_press_production_id=None):
    if not product_family_id or not product_code:
        return []
    if shift_code is not None:
        if not _shift_schema_available(cursor):
            raise ValueError('Shift-aware Press Production requires database migration 027.')
        cursor.execute('''SELECT id FROM dbo.ShiftMaster
            WHERE ShiftCode=? AND IsActive=1''', str(shift_code).strip())
        shift = cursor.fetchone()
        if not shift:
            raise ValueError('Choose an active Shift.')
        shift_scope = 'AND (assigned_press.ShiftMasterID=? OR assigned_press.ShiftMasterID IS NULL)'
        shift_params = (shift[0],)
    else:
        shift_scope = ''
        shift_params = ()
    cursor.execute('''SELECT moulds.MouldID, moulds.MouldNo, moulds.MouldName,
            moulds.ProductFamilyID,moulds.ProductFamily,moulds.ProductCode,
            CAST(CASE WHEN EXISTS (
                SELECT 1
                FROM dbo.PressProduction AS assigned_press
                JOIN dbo.ProductionLot AS assigned_lot
                    ON assigned_lot.ProductionID=assigned_press.ProductionID
                WHERE assigned_lot.ProdDate=? AND assigned_lot.IsActive=1
                    AND assigned_press.MouldID=moulds.MouldID
                    AND assigned_press.ReleasedAt IS NULL
                    AND assigned_press.PressProductionID<>COALESCE(?,0)
                    {shift_scope}
            ) THEN 1 ELSE 0 END AS bit) AS AssignedOnProductionDate
        FROM dbo.vw_MouldList
        AS moulds
        WHERE moulds.ProductFamilyID=? AND moulds.ProductCode=? AND moulds.Status='ACTIVE'
        ORDER BY moulds.MouldNo'''.format(shift_scope=shift_scope),
        production_date, exclude_press_production_id, *shift_params,
        product_family_id, product_code)
    return rows(cursor)


def read_press_production(cursor, production_id):
    has_shift_schema = _shift_schema_available(cursor)
    shift_fields = (
        'pp.ShiftMasterID, shift.ShiftCode,'
        if has_shift_schema else
        'CAST(NULL AS bigint) AS ShiftMasterID, CAST(NULL AS varchar(10)) AS ShiftCode,'
    )
    shift_join = (
        'LEFT JOIN dbo.ShiftMaster AS shift ON shift.id=pp.ShiftMasterID'
        if has_shift_schema else ''
    )
    shift_group = (
        'pp.ShiftMasterID, shift.ShiftCode,'
        if has_shift_schema else ''
    )
    later_shift_filter = (
        'AND (pp.ShiftMasterID IS NULL '
        'OR later_press.ShiftMasterID IS NULL '
        'OR later_press.ShiftMasterID=pp.ShiftMasterID)'
        if has_shift_schema else ''
    )
    shift_time_filter = (
        '''AND pp.ShiftMasterID IS NOT NULL
           AND time_event.ShiftID=TRY_CONVERT(int,shift.ShiftCode)
           AND NOT EXISTS (
               SELECT 1 FROM dbo.PressProduction AS other_episode
               WHERE other_episode.ProductionID=pp.ProductionID
                 AND other_episode.MachineCode=pp.MachineCode
                 AND other_episode.PressProductionID<>pp.PressProductionID
                 AND (other_episode.ShiftMasterID=pp.ShiftMasterID
                      OR other_episode.ShiftMasterID IS NULL
                      OR pp.ShiftMasterID IS NULL))'''
        if has_shift_schema else ''
    )
    time_identity_ambiguity = (
        '''CASE WHEN pp.ShiftMasterID IS NULL OR EXISTS (
               SELECT 1 FROM dbo.PressProduction AS other_episode
               WHERE other_episode.ProductionID=pp.ProductionID
                 AND other_episode.MachineCode=pp.MachineCode
                 AND other_episode.PressProductionID<>pp.PressProductionID
                 AND (other_episode.ShiftMasterID=pp.ShiftMasterID
                      OR other_episode.ShiftMasterID IS NULL
                      OR pp.ShiftMasterID IS NULL)
           ) THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END
           AS EquipmentTimeIdentityAmbiguous,'''
        if has_shift_schema else
        'CAST(1 AS bit) AS EquipmentTimeIdentityAmbiguous,'
    )
    cursor.execute(f'''SELECT pp.PressProductionID, pp.ProductionID, {shift_fields} pp.MachineCode,
            {time_identity_ambiguity}
            equipment.EquipmentName AS MachineName, pp.DispatchQty, pp.CounterQty,
            pp.CuringQty, pp.MouldID, mould.MouldNo, mould.MouldName,
            pp.ProductionStartTime, pp.ProductionEndTime, pp.Remark, pp.CreatedAt, pp.UpdatedAt,
            pp.ReleasedAt, pp.ReleasedBy,
                        (SELECT TOP (1) later_press.MachineCode
                                FROM dbo.PressProduction AS later_press
                                JOIN dbo.ProductionLot AS later_lot
                                    ON later_lot.ProductionID=later_press.ProductionID
                                JOIN dbo.ProductionLot AS target_lot
                                    ON target_lot.ProductionID=pp.ProductionID
                                WHERE later_lot.ProdDate=target_lot.ProdDate
                                    AND later_lot.IsActive=1 AND later_press.MouldID=pp.MouldID
                                    AND later_press.PressProductionID<>pp.PressProductionID
                                            {later_shift_filter}
                                            AND later_press.CreatedAt>pp.ReleasedAt
                                        ORDER BY later_press.CreatedAt, later_press.PressProductionID) AS LaterMouldAssignmentPress,
            (SELECT TOP (1) later_press.MachineCode
                FROM dbo.PressProduction AS later_press
                JOIN dbo.ProductionLot AS later_lot
                  ON later_lot.ProductionID=later_press.ProductionID
                JOIN dbo.ProductionLot AS target_lot
                  ON target_lot.ProductionID=pp.ProductionID
                WHERE later_lot.ProdDate=target_lot.ProdDate
                  AND later_lot.IsActive=1
                  AND later_press.MachineCode=pp.MachineCode
                  AND later_press.PressProductionID<>pp.PressProductionID
                  AND later_press.ReleasedAt IS NULL
                  {later_shift_filter}
                ORDER BY later_press.CreatedAt, later_press.PressProductionID)
                AS LaterPressAssignmentMachineCode,
            usage.MouldUsageID, usage.ReconditionNo AS UsageReconditionNo,
            usage.UsageCycles, usage.UsageDateTime,
            COALESCE(SUM(CASE WHEN time_event.TimeType='SETUP' THEN time_event.DurationMin ELSE 0 END), 0) AS SetupMinutes,
            COALESCE(SUM(CASE WHEN time_event.TimeType='CHANGEOVER' THEN time_event.DurationMin ELSE 0 END), 0) AS ChgOverMinutes,
            COALESCE(SUM(CASE WHEN time_event.TimeType='IDLE' THEN time_event.DurationMin ELSE 0 END), 0) AS IdleMinutes,
            COALESCE(SUM(CASE WHEN time_event.TimeType='CLEAN' THEN time_event.DurationMin ELSE 0 END), 0) AS CleaningMinutes,
            COALESCE(SUM(CASE WHEN time_event.TimeType='BREAKDOWN' THEN time_event.DurationMin ELSE 0 END), 0) AS BreakdownMinutes,
            COALESCE(SUM(CASE WHEN time_event.TimeType='SMDT' THEN time_event.DurationMin ELSE 0 END), 0) AS SMDTMinutes
        FROM dbo.PressProduction AS pp
        JOIN dbo.EquipmentMaster AS equipment ON equipment.EquipmentCode=pp.MachineCode
        LEFT JOIN dbo.MouldMaster AS mould ON mould.MouldID=pp.MouldID
        LEFT JOIN dbo.MouldUsage AS usage ON usage.PressProductionID=pp.PressProductionID
        {shift_join}
                LEFT JOIN dbo.EquipmentTimeEvent AS time_event
                    ON time_event.ProductionID=pp.ProductionID
                 AND time_event.EquipmentCode=pp.MachineCode
                 AND time_event.SourceType='MANUAL'
                 AND time_event.TimeType IN ('SETUP','CHANGEOVER','IDLE','CLEAN','BREAKDOWN','SMDT')
                 {shift_time_filter}
        WHERE pp.ProductionID=?
                GROUP BY pp.PressProductionID, pp.ProductionID, pp.MachineCode, equipment.EquipmentName,
                        {shift_group}
                        pp.DispatchQty, pp.CounterQty, pp.CuringQty, pp.MouldID, mould.MouldNo, mould.MouldName,
                        pp.ProductionStartTime, pp.ProductionEndTime, pp.Remark, pp.CreatedAt, pp.UpdatedAt,
                        pp.ReleasedAt, pp.ReleasedBy,

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


def _ensure_manual_time_identity_has_one_episode(
        cursor, production_id, machine_code, shift_master_id,
        press_production_id, shift_code):
    cursor.execute('''SELECT TOP (1) other.PressProductionID
        FROM dbo.PressProduction AS other WITH (UPDLOCK,HOLDLOCK)
        WHERE other.ProductionID=? AND other.MachineCode=?
          AND other.PressProductionID<>?
          AND (other.ShiftMasterID=? OR other.ShiftMasterID IS NULL)''',
        production_id, machine_code, press_production_id, shift_master_id)
    if cursor.fetchone():
        return False
    return True


def _save_manual_minutes(cursor, production_id, machine_code, shift_code,
                         shift_master_id, press_production_id, data):
    shift_fields = {
        1: {'SETUP': 'Shift1SetupMinutes', 'CHANGEOVER': 'Shift1ChgOverMinutes',
            'IDLE': 'Shift1IdleMinutes',
            'SMDT': 'Shift1SmdtMinutes', 'BREAKDOWN': 'Shift1BreakdownMinutes',
            'CLEAN': 'Shift1CleaningMinutes'},
        2: {'SETUP': 'Shift2SetupMinutes', 'CHANGEOVER': 'Shift2ChgOverMinutes',
            'IDLE': 'Shift2IdleMinutes',
            'SMDT': 'Shift2SmdtMinutes', 'BREAKDOWN': 'Shift2BreakdownMinutes',
            'CLEAN': 'Shift2CleaningMinutes'},
    }
    has_shift_values = any(
        data.get(field) not in (None, '')
        for fields in shift_fields.values()
        for field in fields.values()
    )
    if has_shift_values:
        try:
            event_shift_id = int(shift_code)
        except (TypeError, ValueError):
            raise ValueError('Equipment time events require ShiftCode 1 or 2.') from None
        if event_shift_id not in shift_fields or str(event_shift_id) != str(shift_code):
            raise ValueError('Equipment time events require ShiftCode 1 or 2.')
        other_shift_id = 2 if event_shift_id == 1 else 1
        for time_type, field in shift_fields[other_shift_id].items():
            if field in data and _optional_minutes(data[field], field) != 0:
                raise ValueError('Downtime values for a different Shift cannot be saved with this assignment.')
        values = [
            (event_shift_id, time_type, _optional_minutes(data.get(field), field))
            for time_type, field in shift_fields[event_shift_id].items()
            if field in data and data[field] is not None
        ]
    else:
        manual_fields = (*TIME_FIELDS.values(), 'SmdtMinutes')
        if not any(data.get(field) not in (None, '') for field in manual_fields):
            return False
        try:
            event_shift_id = int(shift_code)
        except (TypeError, ValueError):
            raise ValueError('Equipment time events require ShiftCode 1 or 2.') from None
        if event_shift_id not in shift_fields or str(event_shift_id) != str(shift_code):
            raise ValueError('Equipment time events require ShiftCode 1 or 2.')
        manual_minutes = {
            time_type: _optional_minutes(data[field], field.replace('Minutes', ''))
            for time_type, field in TIME_FIELDS.items()
            if field in data and data[field] is not None
        }
        if data.get('SmdtMinutes') not in (None, ''):
            manual_minutes['SMDT'] = _optional_minutes(data.get('SmdtMinutes'), 'SMDT')
        values = [(event_shift_id, time_type, duration)
                  for time_type, duration in manual_minutes.items()]

    identity_is_unambiguous = _ensure_manual_time_identity_has_one_episode(
        cursor, production_id, machine_code, shift_master_id,
        press_production_id, shift_code)
    if not identity_is_unambiguous:
        if any(duration > 0 for _, _, duration in values):
            raise ValueError(
                f'Cannot save downtime for {machine_code}, Shift {shift_code}: '
                'multiple Press Production episodes share this Lot/Press/Shift, '
                'and EquipmentTimeEvent is not linked to an assignment.')
        return False
    for shift_id, time_type, duration in values:
        cursor.execute('''SELECT TimeEventID FROM dbo.EquipmentTimeEvent WITH (UPDLOCK,HOLDLOCK)
            WHERE ProductionID=? AND EquipmentCode=? AND ShiftID=?
              AND TimeType=? AND SourceType='MANUAL' ''',
            production_id, machine_code, shift_id, time_type)
        existing = cursor.fetchone()
        if existing:
            cursor.execute('''UPDATE dbo.EquipmentTimeEvent
                SET DurationMin=?, StartDateTime=NULL, EndDateTime=NULL, UpdatedAt=SYSDATETIME()
                WHERE TimeEventID=? AND ProductionID=? AND EquipmentCode=?
                  AND ShiftID=? AND TimeType=? AND SourceType='MANUAL' ''',
                duration, existing[0], production_id, machine_code, shift_id, time_type)
        else:
            cursor.execute('''INSERT INTO dbo.EquipmentTimeEvent
                (ProductionID,EquipmentCode,ShiftID,TimeType,DurationMin,SourceType)
                VALUES (?,?,?,?,?, 'MANUAL')''',
                production_id, machine_code, shift_id, time_type, duration)
    return True


def validate_press_input(data, require_mould=True, production_date=None, day_start_time=None,
                         allow_incomplete=False):
    shift_code = str(data.get('ShiftCode') or '').strip()
    if not shift_code or len(shift_code) > 10:
        raise ValueError('Choose an active Shift.')
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
    return dict(ShiftCode=shift_code, MachineCode=machine_code, MouldID=mould_id,
                DispatchQty=_optional_quantity(data.get('DispatchQty'), 'Dispatch Qty'),
                CounterQty=counter, CuringQty=curing,
                ProductionStartTime=start_time, ProductionEndTime=end_time,
                Remark=remark or None)


def _require_active_lot(cursor, production_id):
    cursor.execute('''SELECT ProductionID, ProductFamilyID, ProductCode, ProdDate
        FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK)
        WHERE ProductionID=? AND IsActive=1''', production_id)
    found = cursor.fetchone()
    if not found:
        raise ValueError('This Production Lot is no longer active.')
    if found[1] is None:
        raise ValueError('This legacy Lot has no confirmed Product Family. Resolve its product before assigning Press production.')
    return found[1], found[2], found[3]


def _require_shift_schema(cursor):
    if not _shift_schema_available(cursor):
        raise ValueError('Shift-aware Press Production requires database migration 027.')


def _resolve_active_shift(cursor, shift_code):
    cursor.execute('''SELECT id FROM dbo.ShiftMaster WITH (UPDLOCK,HOLDLOCK)
        WHERE ShiftCode=? AND IsActive=1''', shift_code)
    shift = cursor.fetchone()
    if not shift:
        raise ValueError('Choose an active Shift.')
    return shift[0]


def _read_shift_code(cursor, shift_master_id):
    if shift_master_id is None:
        return None
    cursor.execute('SELECT ShiftCode FROM dbo.ShiftMaster WITH (HOLDLOCK) WHERE id=?',
                   shift_master_id)
    shift = cursor.fetchone()
    if not shift:
        raise ValueError('The existing assignment references an unknown Shift.')
    return str(shift[0])


def _validate_press(cursor, product_family_id, product_code, machine_code):
    cursor.execute('''SELECT 1
        FROM dbo.vw_PressMcCapabilityMatrix AS capability
        JOIN dbo.EquipmentMaster AS equipment
          ON equipment.EquipmentCode=capability.PressCode
        WHERE capability.PressCode=? AND capability.ProductFamilyID=?
          AND capability.ProductCode=? AND capability.CanProduce=1
          AND equipment.IsActive=1 AND equipment.EquipmentType='PRESS' ''',
        machine_code, product_family_id, product_code)
    if not cursor.fetchone():
        raise ValueError('This Press is inactive or is not enabled for the Lot Product.')


def _lock_and_validate_mould(cursor, product_family_id, product_code, mould_id):
    cursor.execute('''SELECT MouldID, Status, ProductFamilyID, ProductCode, CurrentReconditionNo
        FROM dbo.MouldMaster WITH (UPDLOCK,HOLDLOCK) WHERE MouldID=?''', mould_id)
    mould = cursor.fetchone()
    if not mould:
        raise ValueError('Mould not found.')
    if mould[1] != 'ACTIVE':
        raise ValueError('Only ACTIVE Moulds can be assigned to Press production.')
    if (mould[2], mould[3]) != (product_family_id, product_code):
        raise ValueError('Mould Product must match the Production Lot Product.')
    return mould[4]


def _lock_existing_usage_mould(cursor, product_family_id, product_code, mould_id):
    cursor.execute('''SELECT MouldID, ProductFamilyID, ProductCode
        FROM dbo.MouldMaster WITH (UPDLOCK,HOLDLOCK) WHERE MouldID=?''', mould_id)
    mould = cursor.fetchone()
    if not mould:
        raise ValueError('Mould not found.')
    if (mould[1], mould[2]) != (product_family_id, product_code):
        raise ValueError('Mould Product must match the Production Lot Product.')


def _lock_allocation_keys(cursor, production_date, press_identities=(),
                          mould_identities=()):
    resources = set()
    for shift_master_id, machine_code in press_identities:
        if machine_code is None:
            continue
        machine_code = str(machine_code).strip().upper()
        resources.add(
            f'FittingMES.PressMachine.{production_date:%Y%m%d}.all.{machine_code}')
        if shift_master_id is not None:
            resources.add(
                f'FittingMES.PressMachine.{production_date:%Y%m%d}.'
                f'{shift_master_id}.{machine_code}')
    for shift_master_id, mould_id in mould_identities:
        if mould_id is None:
            continue
        resources.add(
            f'FittingMES.PressMould.{production_date:%Y%m%d}.all.{mould_id}')
        if shift_master_id is not None:
            resources.add(
                f'FittingMES.PressMould.{production_date:%Y%m%d}.'
                f'{shift_master_id}.{mould_id}')
    for resource in sorted(resources):
        cursor.execute('''DECLARE @result int;
            EXEC @result = sys.sp_getapplock @Resource=?, @LockMode='Exclusive',
                @LockOwner='Transaction', @LockTimeout=10000;
            SELECT @result;''', resource)
        result = cursor.fetchone()
        if not result or result[0] < 0:
            raise ValueError('Press or Mould availability is being updated. Please retry.')


def _ensure_mould_available(cursor, production_date, shift_master_id, mould_id,
                            exclude_press_production_id=None):
    cursor.execute('''SELECT TOP (1) assigned_press.PressProductionID,
                             assigned_press.ShiftMasterID
        FROM dbo.PressProduction AS assigned_press WITH (UPDLOCK,HOLDLOCK)
        JOIN dbo.ProductionLot AS assigned_lot WITH (UPDLOCK,HOLDLOCK)
          ON assigned_lot.ProductionID=assigned_press.ProductionID
        WHERE assigned_lot.ProdDate=? AND assigned_lot.IsActive=1
          AND assigned_press.MouldID=? AND assigned_press.ReleasedAt IS NULL
          AND (assigned_press.ShiftMasterID=? OR assigned_press.ShiftMasterID IS NULL)
          AND assigned_press.PressProductionID<>COALESCE(?,0)
        ORDER BY CASE WHEN assigned_press.ShiftMasterID IS NULL THEN 0 ELSE 1 END,
                 assigned_press.PressProductionID''',
        production_date, mould_id, shift_master_id, exclude_press_production_id)
    conflict = cursor.fetchone()
    if conflict:
        if conflict[1] is None:
            raise ValueError('An active legacy Mould assignment has unknown Shift; resolve or release it before allocation.')
        raise ValueError('This Mould is already assigned for the selected Production Date and Shift.')


def _ensure_press_available(cursor, production_date, machine_code, shift_master_id,
                            exclude_press_production_id=None):
    shift_scope = (
        'AND (assigned_press.ShiftMasterID=? OR assigned_press.ShiftMasterID IS NULL)'
        if shift_master_id is not None else ''
    )
    shift_args = (shift_master_id,) if shift_master_id is not None else ()
    cursor.execute(f'''SELECT TOP (1) assigned_press.PressProductionID,
                             assigned_press.ShiftMasterID
        FROM dbo.PressProduction AS assigned_press WITH (UPDLOCK,HOLDLOCK)
        JOIN dbo.ProductionLot AS assigned_lot WITH (UPDLOCK,HOLDLOCK)
          ON assigned_lot.ProductionID=assigned_press.ProductionID
        WHERE assigned_lot.ProdDate=?
          AND assigned_press.MachineCode=? AND assigned_press.ReleasedAt IS NULL
          AND assigned_press.PressProductionID<>COALESCE(?,0) {shift_scope}
        ORDER BY CASE WHEN assigned_press.ShiftMasterID IS NULL THEN 0 ELSE 1 END,
                 assigned_press.PressProductionID''',
        production_date, machine_code, exclude_press_production_id, *shift_args)
    conflict = cursor.fetchone()
    if conflict:
        if shift_master_id is None:
            raise ValueError(
                'Cannot restore a Press assignment with unknown Shift while another '
                'active assignment for this Press exists on the Production Date.')
        if conflict[1] is None:
            raise ValueError('An active legacy Press assignment has unknown Shift; resolve or release it before allocation.')
        raise ValueError(
            'This Press already has an active assignment for the selected '
            'Production Date and Shift.')


def _ensure_equipment_time_identity_safe(cursor, production_id, identities):
    for machine_code, shift_code in dict.fromkeys(identities):
        if shift_code is None:
            cursor.execute('''SELECT TOP (1) TimeEventID
                FROM dbo.EquipmentTimeEvent WITH (UPDLOCK,HOLDLOCK)
                WHERE ProductionID=? AND EquipmentCode=?''', production_id, machine_code)
            if cursor.fetchone():
                raise ValueError(
                    f'Cannot change Press or Shift: the existing assignment has unknown Shift, '
                    f'and EquipmentTimeEvent rows exist for {machine_code} in this Lot.')
            continue
        cursor.execute('''SELECT TOP (1) TimeEventID
            FROM dbo.EquipmentTimeEvent WITH (UPDLOCK,HOLDLOCK)
            WHERE ProductionID=? AND EquipmentCode=? AND ShiftID=?''',
            production_id, machine_code, shift_code)
        if cursor.fetchone():
            raise ValueError(
                f'Cannot change Press or Shift: EquipmentTimeEvent rows exist for '
                f'{machine_code}, Shift {shift_code}, and this Production Lot; '
                'those rows are not linked to PressProductionID.')


def _logger_machine_identity(cursor, machine_code):
    cursor.execute('''SELECT McId, Machine
        FROM dbo.Fitting_MainMachine WITH (HOLDLOCK)''')
    matches = []
    for mc_id, machine in cursor.fetchall():
        machine = str(machine or '').strip()
        suffix = machine_code[len(machine):] if machine_code.startswith(machine) else ''
        if machine and suffix.isascii() and suffix.isdigit() and int(suffix) > 0:
            matches.append((mc_id, int(suffix)))
    if len(matches) != 1:
        raise ValueError(
            f'Cannot safely map Press code {machine_code} to one LOGGER machine identity.')
    return matches[0]


def _ensure_logger_identity_safe(cursor, production_date, identities):
    for machine_code, shift_code in dict.fromkeys(identities):
        mc_id, instance_no = _logger_machine_identity(cursor, machine_code)
        if shift_code is None:
            cursor.execute('''SELECT TOP (1) LoggerEventID, ShiftID
                FROM dbo.LoggerEvent WITH (UPDLOCK,HOLDLOCK)
                WHERE ProductionDate=? AND McId=? AND McInstanceNo=?''',
                production_date, mc_id, instance_no)
        else:
            cursor.execute('''SELECT TOP (1) LoggerEventID, ShiftID
                FROM dbo.LoggerEvent WITH (UPDLOCK,HOLDLOCK)
                WHERE ProductionDate=? AND McId=? AND McInstanceNo=?
                  AND (ShiftID=? OR ShiftID IS NULL)''',
                production_date, mc_id, instance_no, shift_code)
        event = cursor.fetchone()
        if event:
            if event[1] is None:
                raise ValueError(
                    f'Cannot change Press or Shift: LOGGER entry {event[0]} for '
                    f'{machine_code} on {production_date} has no ShiftID, so it cannot '
                    'be safely attributed to an assignment.')
            if shift_code is None:
                raise ValueError(
                    f'Cannot change Press or Shift: LOGGER entry {event[0]} for '
                    f'{machine_code} on {production_date} cannot be matched to the '
                    'legacy assignment because its Shift is unknown.')
            raise ValueError(
                f'Cannot change Press or Shift: LOGGER entry {event[0]} exists for '
                f'{machine_code}, Shift {shift_code}, on {production_date}; '
                'LOGGER has no PressProductionID link.')


def save_press_production(conn, production_id, data, press_production_id=None):
    try:
        downtime_only = bool(data.get('DowntimeOnly'))
        is_new_press = press_production_id is None
        cursor = conn.cursor()
        _require_shift_schema(cursor)
        lock_lots(cursor)
        product_family_id, product_code, production_date = _require_active_lot(cursor, production_id)
        if isinstance(production_date, datetime):
            production_date = production_date.date()
        if not isinstance(production_date, date):
            raise ValueError('Production Lot has an invalid Production Date.')
        posted_date = str(data.get('ProductionDate') or '').strip()
        if posted_date:
            try:
                posted_date = date.fromisoformat(posted_date)
            except ValueError:
                raise ValueError('Production Date is required.') from None
            if posted_date != production_date:
                raise ValueError('Production Date does not match the selected Lot.')
        day_start_time = read_day_start_time(cursor, production_date)
        validation_data = data
        if downtime_only:
            validation_data = dict(data)
            for field in ('MouldID', 'DispatchQty', 'CounterQty', 'CuringQty',
                          'ProductionStartTime', 'ProductionEndTime', 'Remark'):
                validation_data.pop(field, None)
        values = validate_press_input(validation_data, require_mould=(
                          press_production_id is None and not downtime_only),
                          production_date=production_date, day_start_time=day_start_time,
                          allow_incomplete=True)
        shift_master_id = _resolve_active_shift(cursor, values['ShiftCode'])
        if not downtime_only:
            _validate_press(cursor, product_family_id, product_code, values['MachineCode'])

        mould_only_edit = False
        if press_production_id is None:
            _lock_allocation_keys(
                cursor, production_date,
                press_identities=[(shift_master_id, values['MachineCode'])],
                mould_identities=[(shift_master_id, values['MouldID'])])
            _ensure_press_available(
                cursor, production_date, values['MachineCode'], shift_master_id)
            _ensure_mould_available(cursor, production_date, shift_master_id, values['MouldID'])
            current_recondition_no = _lock_and_validate_mould(
                cursor, product_family_id, product_code, values['MouldID'])
            cursor.execute('''INSERT INTO dbo.PressProduction
                (ProductionID,MachineCode,ShiftMasterID,DispatchQty,CounterQty,CuringQty,MouldID,
                 ProductionStartTime,ProductionEndTime,Remark)
                OUTPUT INSERTED.PressProductionID VALUES (?,?,?,?,?,?,?,?,?,?)''',
                production_id, values['MachineCode'], shift_master_id,
                values['DispatchQty'], values['CounterQty'],
                values['CuringQty'], values['MouldID'], values['ProductionStartTime'],
                values['ProductionEndTime'], values['Remark'])
            press_production_id = cursor.fetchone()[0]
            usage_recondition_no = current_recondition_no
            has_usage = False
        else:
            cursor.execute('''SELECT PressProductionID, MachineCode, MouldID, CounterQty,
                                     ProductionStartTime, ProductionEndTime, ShiftMasterID, ReleasedAt,
                                     DispatchQty, CuringQty, Remark
                FROM dbo.PressProduction WITH (UPDLOCK,HOLDLOCK)
                WHERE PressProductionID=? AND ProductionID=?''', press_production_id, production_id)
            existing = cursor.fetchone()
            if not existing:
                raise ValueError('Press Production row not found for this Lot.')
            if existing[7] is not None:
                raise ValueError('Released Press Production rows cannot be edited; undo release first.')
            if downtime_only:
                values['MachineCode'] = existing[1]
                values['MouldID'] = existing[2]
                values['ShiftCode'] = _read_shift_code(cursor, existing[6])
                shift_master_id = existing[6]
            if 'ProductionStartTime' not in data:
                values['ProductionStartTime'] = existing[4]
            if 'ProductionEndTime' not in data:
                values['ProductionEndTime'] = existing[5]
            if 'MouldID' not in data:
                values['MouldID'] = existing[2]
            if 'DispatchQty' not in data:
                values['DispatchQty'] = existing[8]
            if 'CounterQty' not in data:
                values['CounterQty'] = existing[3]
            if 'CuringQty' not in data:
                values['CuringQty'] = existing[9]
            if 'Remark' not in data:
                values['Remark'] = existing[10]
            identity_changed = (
                existing[1] != values['MachineCode']
                or existing[6] != shift_master_id
            )
            mould_only_edit = values['MouldID'] != existing[2] and not identity_changed
            if mould_only_edit:
                values['DispatchQty'] = existing[8]
                values['CounterQty'] = existing[3]
                values['CuringQty'] = existing[9]
            if (values['CounterQty'] is not None and values['CuringQty'] is not None
                    and values['CuringQty'] > values['CounterQty']):
                raise ValueError('Curing Qty cannot exceed Counter Qty.')
            if identity_changed:
                old_shift_code = _read_shift_code(cursor, existing[6])
                _ensure_equipment_time_identity_safe(
                    cursor, production_id,
                    ((existing[1], old_shift_code),
                     (values['MachineCode'], values['ShiftCode'])))
                _ensure_logger_identity_safe(
                    cursor, production_date,
                    ((existing[1], old_shift_code),
                     (values['MachineCode'], values['ShiftCode'])))
            usage = None
            has_usage = False
            if not downtime_only:
                cursor.execute('''SELECT MouldUsageID, MouldID, ReconditionNo, UsageCycles
                    FROM dbo.MouldUsage WITH (UPDLOCK,HOLDLOCK)
                    WHERE PressProductionID=?''', press_production_id)
                usage = cursor.fetchone()
                has_usage = usage is not None
            if not downtime_only and values['MouldID'] is None and (values['CounterQty'] or 0) > 0:
                raise ValueError('An ACTIVE Mould is required when Counter Qty is greater than zero.')
            if (has_usage and values['CounterQty'] is None and not downtime_only
                    and 'CounterQty' in data):
                raise ValueError('Counter Qty is required to reconcile the existing Mould usage.')
            if has_usage and values['MouldID'] is None and not downtime_only:
                raise ValueError('An ACTIVE Mould is required to reconcile the existing Mould usage.')
            if not downtime_only:
                _lock_allocation_keys(
                    cursor, production_date,
                    press_identities=[
                        (existing[6], existing[1]),
                        (shift_master_id, values['MachineCode']),
                    ],
                    mould_identities=[
                        (existing[6], existing[2]),
                        (shift_master_id, values['MouldID']),
                    ])
                _ensure_press_available(
                    cursor, production_date, values['MachineCode'], shift_master_id,
                    exclude_press_production_id=press_production_id)
                if values['MouldID'] is not None:
                    _ensure_mould_available(
                        cursor, production_date, shift_master_id, values['MouldID'],
                        exclude_press_production_id=press_production_id)
                if has_usage and values['MouldID'] == existing[2]:
                    _lock_existing_usage_mould(cursor, product_family_id, product_code, values['MouldID'])
                    current_recondition_no = usage[2]
                else:
                    current_recondition_no = (_lock_and_validate_mould(
                        cursor, product_family_id, product_code, values['MouldID'])
                        if values['MouldID'] is not None else None)
            else:
                current_recondition_no = None
            usage_recondition_no = (
                usage[2] if has_usage and values['MouldID'] == existing[2]
                else current_recondition_no
            )
            if not downtime_only:
                cursor.execute('''UPDATE dbo.PressProduction SET MachineCode=?,ShiftMasterID=?,
                    DispatchQty=?,CounterQty=?,CuringQty=?,MouldID=?,ProductionStartTime=?,
                    ProductionEndTime=?,Remark=?,UpdatedAt=SYSDATETIME()
                    WHERE PressProductionID=? AND ProductionID=?''',
                    values['MachineCode'], shift_master_id, values['DispatchQty'],
                    values['CounterQty'], values['CuringQty'],
                    values['MouldID'], values['ProductionStartTime'], values['ProductionEndTime'],
                    values['Remark'], press_production_id, production_id)

        usage_reconciliation_requested = (
            is_new_press or 'CounterQty' in data
            or (press_production_id is not None and values['MouldID'] != existing[2])
        )
        if (not downtime_only and usage_reconciliation_requested
                and ((values['CounterQty'] or 0) > 0 or has_usage)):
            if values['MouldID'] is None:
                raise ValueError('An ACTIVE Mould is required when Counter Qty is greater than zero.')
            cursor.execute('''SELECT MouldUsageID FROM dbo.MouldUsage WITH (UPDLOCK,HOLDLOCK)
                WHERE PressProductionID=?''', press_production_id)
            usage_row = cursor.fetchone()
            if usage_row:
                if values['CounterQty'] is None:
                    raise ValueError('Counter Qty is required to reconcile the existing Mould usage.')
                cursor.execute('''UPDATE dbo.MouldUsage
                    SET MouldID=?,ReconditionNo=?,UsageCycles=?
                    WHERE PressProductionID=?''',
                    values['MouldID'], usage_recondition_no,
                    values['CounterQty'], press_production_id)
            else:
                cursor.execute('''INSERT INTO dbo.MouldUsage
                    (MouldID,PressProductionID,ReconditionNo,UsageCycles)
                    VALUES (?,?,?,?)''', values['MouldID'], press_production_id,
                    usage_recondition_no, values['CounterQty'])

        downtime_saved = False
        if not mould_only_edit or downtime_only:
            downtime_saved = _save_manual_minutes(
                cursor, production_id, values['MachineCode'], values['ShiftCode'],
                shift_master_id, press_production_id, data)
        if downtime_only and not downtime_saved:
            raise ValueError('Enter downtime values and verify the Press/Shift assignment before saving.')

        conn.commit()
        return press_production_id
    except Exception:
        conn.rollback()
        raise


def release_press_production(conn, production_id, press_production_id, released_by='FittingMES'):
    try:
        cursor = conn.cursor()
        lock_lots(cursor)
        has_shift_schema = _shift_schema_available(cursor)
        cursor.execute('''SELECT PressProductionID, ReleasedAt
            FROM dbo.PressProduction WITH (UPDLOCK,HOLDLOCK)
            WHERE PressProductionID=? AND ProductionID=?''', press_production_id, production_id)
        existing = cursor.fetchone()
        if not existing:
            raise ValueError('Press Production row not found for this Lot.')
        if existing[1] is not None:
            conn.commit()
            return 'ALREADY_RELEASED'
        if has_shift_schema:
            cursor.execute('''SELECT lot.ProdDate, pp.ShiftMasterID, pp.MachineCode, pp.MouldID
                FROM dbo.PressProduction AS pp WITH (UPDLOCK,HOLDLOCK)
                JOIN dbo.ProductionLot AS lot WITH (UPDLOCK,HOLDLOCK)
                  ON lot.ProductionID=pp.ProductionID
                WHERE pp.PressProductionID=? AND pp.ProductionID=?''',
                press_production_id, production_id)
            allocation = cursor.fetchone()
            if not allocation:
                raise ValueError('Press Production row not found for this Lot.')
            _lock_allocation_keys(
                cursor, allocation[0],
                press_identities=[(allocation[1], allocation[2])],
                mould_identities=[(allocation[1], allocation[3])])
        cursor.execute('''UPDATE dbo.PressProduction
            SET ReleasedAt=SYSDATETIME(), ReleasedBy=?, UpdatedAt=SYSDATETIME()
            WHERE PressProductionID=? AND ProductionID=? AND ReleasedAt IS NULL''',
            released_by or 'FittingMES', press_production_id, production_id)
        conn.commit()
        return 'RELEASED'
    except Exception:
        conn.rollback()
        raise


def undo_release_press_production(conn, production_id, press_production_id):
    try:
        cursor = conn.cursor()
        lock_lots(cursor)
        has_shift_schema = _shift_schema_available(cursor)
        shift_fields = ', pp.ShiftMasterID, pp.MachineCode' if has_shift_schema else ''
        cursor.execute(f'''SELECT pp.PressProductionID, pp.MouldID, pp.ReleasedAt, lot.ProdDate
                              {shift_fields}
            FROM dbo.PressProduction AS pp WITH (UPDLOCK,HOLDLOCK)
            JOIN dbo.ProductionLot AS lot WITH (UPDLOCK,HOLDLOCK)
              ON lot.ProductionID=pp.ProductionID
            WHERE pp.PressProductionID=? AND pp.ProductionID=?''',
            press_production_id, production_id)
        existing = cursor.fetchone()
        if not existing:
            raise ValueError('Press Production row not found for this Lot.')
        if existing[2] is None:
            conn.commit()
            return 'ALREADY_ACTIVE'
        if has_shift_schema:
            shift_master_id, machine_code = existing[4], existing[5]
            _lock_allocation_keys(
                cursor, existing[3],
                press_identities=[(shift_master_id, machine_code)],
                mould_identities=[(shift_master_id, existing[1])])
            _ensure_press_available(
                cursor, existing[3], machine_code, shift_master_id,
                exclude_press_production_id=press_production_id)
            if existing[1] is not None:
                shift_clause = (
                    'AND (later_press.ShiftMasterID=? OR later_press.ShiftMasterID IS NULL)'
                    if shift_master_id is not None else ''
                )
                shift_args = (shift_master_id,) if shift_master_id is not None else ()
                cursor.execute(f'''SELECT TOP (1) later_press.PressProductionID
                    FROM dbo.PressProduction AS later_press WITH (UPDLOCK,HOLDLOCK)
                    JOIN dbo.ProductionLot AS later_lot WITH (UPDLOCK,HOLDLOCK)
                      ON later_lot.ProductionID=later_press.ProductionID
                    WHERE later_lot.ProdDate=? AND later_lot.IsActive=1
                      AND later_press.MouldID=? AND later_press.PressProductionID<>?
                      AND later_press.CreatedAt>? {shift_clause}''',
                    existing[3], existing[1], press_production_id, existing[2], *shift_args)
                if cursor.fetchone():
                    conn.commit()
                    return 'MOULD_ALREADY_REASSIGNED'
                active_shift_clause = (
                    'AND (active_press.ShiftMasterID=? OR active_press.ShiftMasterID IS NULL)'
                    if shift_master_id is not None else ''
                )
                cursor.execute(f'''SELECT TOP (1) active_press.PressProductionID
                    FROM dbo.PressProduction AS active_press WITH (UPDLOCK,HOLDLOCK)
                    JOIN dbo.ProductionLot AS active_lot WITH (UPDLOCK,HOLDLOCK)
                      ON active_lot.ProductionID=active_press.ProductionID
                    WHERE active_lot.ProdDate=? AND active_lot.IsActive=1
                      AND active_press.MouldID=? AND active_press.ReleasedAt IS NULL
                      AND active_press.PressProductionID<>? {active_shift_clause}''',
                    existing[3], existing[1], press_production_id, *shift_args)
                if cursor.fetchone():
                    conn.commit()
                    return 'MOULD_ALREADY_REASSIGNED'
            press_shift_clause = (
                'AND (ShiftMasterID=? OR ShiftMasterID IS NULL)'
                if shift_master_id is not None else ''
            )
            press_shift_args = (shift_master_id,) if shift_master_id is not None else ()
            cursor.execute(f'''SELECT TOP (1) PressProductionID
                FROM dbo.PressProduction WITH (UPDLOCK,HOLDLOCK)
                WHERE ProductionID=? AND MachineCode=? AND ReleasedAt IS NULL
                  AND PressProductionID<>? {press_shift_clause}''',
                production_id, machine_code, press_production_id, *press_shift_args)
            if cursor.fetchone():
                raise ValueError('This Press already has an active assignment for the selected Shift.')
        else:
            cursor.execute('''SELECT later_press.PressProductionID
                FROM dbo.PressProduction AS later_press WITH (UPDLOCK,HOLDLOCK)
                JOIN dbo.ProductionLot AS later_lot WITH (UPDLOCK,HOLDLOCK)
                  ON later_lot.ProductionID=later_press.ProductionID
                WHERE later_lot.ProdDate=? AND later_lot.IsActive=1
                  AND later_press.MouldID=? AND later_press.PressProductionID<>?
                  AND later_press.CreatedAt>?''',
                existing[3], existing[1], press_production_id, existing[2])
            if cursor.fetchone():
                conn.commit()
                return 'MOULD_ALREADY_REASSIGNED'
        cursor.execute('''UPDATE dbo.PressProduction
            SET ReleasedAt=NULL, ReleasedBy=NULL, UpdatedAt=SYSDATETIME()
            WHERE PressProductionID=? AND ProductionID=? AND ReleasedAt IS NOT NULL''',
            press_production_id, production_id)
        conn.commit()
        return 'RESTORED'
    except Exception:
        conn.rollback()
        raise


def build_press_production_context(cursor, lot, press_form=None):
    product_family_id = lot.get('ProductFamilyID')
    product_code = lot.get('ProductCode')
    rows_for_lot = read_press_production(cursor, lot['ProductionID'])
    day_start_time = read_day_start_time(cursor, lot['ProdDate'])
    eligible_shifts = read_active_shifts(cursor)
    if product_family_id is None:
        return dict(press_production=rows_for_lot, day_start_time=day_start_time,
                    eligible_shifts=eligible_shifts, eligible_presses=[], eligible_moulds=[],
                    press_product_error='This legacy Lot has no confirmed Product Family; Press/Mould assignment is unavailable.')
    if not _shift_schema_available(cursor):
        return dict(press_production=rows_for_lot, day_start_time=day_start_time,
                    eligible_shifts=eligible_shifts, eligible_presses=[], eligible_moulds=[],
                    press_product_error='Shift-aware Press Production requires database migration 027 before use.')

    press_form = press_form or {}
    try:
        excluded_id = int(press_form.get('PressProductionID') or 0) or None
    except (TypeError, ValueError):
        excluded_id = None
    presses_by_code = {}
    moulds_by_id = {}
    for shift in eligible_shifts:
        shift_code = str(shift['ShiftCode'])
        presses = read_eligible_presses(cursor, product_family_id, product_code,
            lot['ProdDate'], shift_code, excluded_id)
        for press in presses:
            option = presses_by_code.setdefault(press['PressCode'],
                dict(press, AvailableShiftCodes=[]))
            if not press.get('AssignedOnProductionDate'):
                option['AvailableShiftCodes'].append(shift_code)
        moulds = read_eligible_moulds(cursor, product_family_id, product_code,
            lot['ProdDate'], shift_code, excluded_id)
        for mould in moulds:
            option = moulds_by_id.setdefault(mould['MouldID'],
                dict(mould, AvailableShiftCodes=[]))
            if not mould.get('AssignedOnProductionDate'):
                option['AvailableShiftCodes'].append(shift_code)

    for option_key, form_key, label_key, options in (
        ('PressCode', 'MachineCode', 'PressName', presses_by_code),
        ('MouldID', 'MouldID', 'MouldName', moulds_by_id),
    ):
        selected = press_form.get(form_key)
        if selected not in (None, ''):
            try:
                selected_key = int(selected) if option_key == 'MouldID' else str(selected)
            except (TypeError, ValueError):
                continue
            options.setdefault(selected_key, {
                option_key: selected_key, label_key: str(selected),
                'AvailableShiftCodes': [], 'SubmittedUnavailable': True})

    return dict(press_production=rows_for_lot,
                day_start_time=day_start_time,
                eligible_shifts=eligible_shifts,
                eligible_presses=list(presses_by_code.values()),
                eligible_moulds=list(moulds_by_id.values()),
                press_product_error=None)