from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from app.lots import lock_lots, rows
from app.production_clock import read_day_start_time, resolve_run_times, clock_display
from app.resource_availability import (find_assignment_conflict,
                                       read_lot_boundaries,
                                       resolve_effective_interval)
from app.shift_schedule import (period_contains_interval, period_interval,
                                resolve_period_interval)
from app.shift_settings import read_effective_cutoff


def read_eligible_presses(cursor, product_family_id, product_code, production_date=None,
                          shift_code=None, exclude_press_production_id=None,
                          requested_interval=None):
    if not product_family_id or not product_code:
        return []
    if shift_code is not None:
        if not _shift_schema_available(cursor):
            raise ValueError('Shift-aware Press Production requires database migration 027.')
        _query_active_shift(cursor, str(shift_code).strip(), production_date)
        shift = cursor.fetchone()
        if not shift:
            raise ValueError('Choose an active Shift.')
    cursor.execute('''SELECT capability.PressCode, capability.PressName,
            capability.CurrentLine, capability.CurrentLineName, capability.StandardSpeed,
            equipment.IsActive AS EquipmentIsActive
        FROM dbo.vw_PressMcCapabilityMatrix AS capability
        JOIN dbo.EquipmentMaster AS equipment
          ON equipment.EquipmentCode=capability.PressCode
        WHERE capability.ProductFamilyID=? AND capability.ProductCode=?
          AND capability.CanProduce=1
          AND equipment.EquipmentType='PRESS'
        ORDER BY equipment.DisplayOrder, capability.PressCode''',
        product_family_id, product_code)
    presses = rows(cursor)
    for press in presses:
        reason = None
        if not press.get('EquipmentIsActive', True):
            reason = 'Inactive Press.'
        elif requested_interval is None:
            reason = 'Invalid or unresolved production interval.'
        else:
            reason = find_assignment_conflict(
                cursor, 'press', press['PressCode'], requested_interval,
                exclude_press_production_id, production_date)
        press['AvailabilityReason'] = reason
        press['Available'] = reason is None
    return presses


def read_active_shifts(cursor, production_date=None):
    if production_date is not None and _period_schema_available(cursor):
        cursor.execute('''SELECT master.id AS ShiftMasterID,version.ShiftCode,
                version.ShiftName,version.id AS ShiftMasterVersionID
            FROM dbo.ShiftMaster AS master
            CROSS APPLY (
                SELECT TOP (1) v.id,v.ShiftCode,v.ShiftName,v.IsActive
                FROM dbo.ShiftMasterVersion AS v
                WHERE v.ShiftMasterID=master.id AND v.EffectiveFromDate<=?
                ORDER BY v.EffectiveFromDate DESC,v.VersionNumber DESC
            ) AS version
            WHERE version.IsActive=1
            ORDER BY version.ShiftCode''', production_date)
        return rows(cursor)
    cursor.execute('''SELECT ShiftCode, ShiftName
        FROM dbo.ShiftMaster
        WHERE IsActive=1
        ORDER BY ShiftCode''')
    return rows(cursor)


def _period_schema_available(cursor):
    cursor.execute("""SELECT CASE WHEN COL_LENGTH(
        N'dbo.PressProduction', N'ShiftPeriodID') IS NOT NULL
        AND OBJECT_ID(N'dbo.ShiftPeriodMaster', N'U') IS NOT NULL
        AND OBJECT_ID(N'dbo.ShiftPeriodVersion', N'U') IS NOT NULL
        AND OBJECT_ID(N'dbo.ShiftMasterVersion', N'U') IS NOT NULL
        THEN 1 ELSE 0 END""")
    row = cursor.fetchone()
    return bool(row and row[0])


def _require_period_schema(cursor):
    if not _period_schema_available(cursor):
        raise ValueError('Shift Period assignments require database migration 029.')


def read_active_periods(cursor, production_date):
    if not _period_schema_available(cursor):
        return []
    cursor.execute('''SELECT period.id AS ShiftPeriodID,period.ShiftMasterID,
            shift_version.id AS ShiftMasterVersionID,shift_version.ShiftCode,
            period_version.id AS ShiftPeriodVersionID,period_version.PeriodLabel,
            period_version.DisplayOrder,period_version.StartTime,period_version.EndTime
        FROM dbo.ShiftPeriodMaster AS period
        CROSS APPLY (
            SELECT TOP (1) version.id,version.PeriodLabel,version.DisplayOrder,
                version.StartTime,version.EndTime,version.IsActive
            FROM dbo.ShiftPeriodVersion AS version
            WHERE version.ShiftPeriodID=period.id
              AND version.EffectiveFromDate<=?
            ORDER BY version.EffectiveFromDate DESC,version.VersionNumber DESC
        ) AS period_version
        CROSS APPLY (
            SELECT TOP (1) version.id,version.ShiftCode,version.IsActive
            FROM dbo.ShiftMasterVersion AS version
            WHERE version.ShiftMasterID=period.ShiftMasterID
              AND version.EffectiveFromDate<=?
            ORDER BY version.EffectiveFromDate DESC,version.VersionNumber DESC
        ) AS shift_version
        WHERE period_version.IsActive=1 AND shift_version.IsActive=1
        ORDER BY shift_version.ShiftCode,period_version.DisplayOrder,period.id''',
        production_date, production_date)
    return rows(cursor)


def _shift_schema_available(cursor):
    cursor.execute("""SELECT CASE WHEN COL_LENGTH(
        N'dbo.PressProduction', N'ShiftMasterID') IS NULL THEN 0 ELSE 1 END""")
    row = cursor.fetchone()
    return bool(row and row[0])


def read_eligible_moulds(cursor, product_family_id, product_code, production_date=None,
                         shift_code=None, exclude_press_production_id=None,
                         requested_interval=None):
    if not product_family_id or not product_code:
        return []
    if shift_code is not None:
        if not _shift_schema_available(cursor):
            raise ValueError('Shift-aware Press Production requires database migration 027.')
        _query_active_shift(cursor, str(shift_code).strip(), production_date)
        shift = cursor.fetchone()
        if not shift:
            raise ValueError('Choose an active Shift.')
    cursor.execute('''SELECT moulds.MouldID, moulds.MouldNo, moulds.MouldName,
            moulds.ProductFamilyID,moulds.ProductFamily,moulds.ProductCode,moulds.Status
        FROM dbo.vw_MouldList
        AS moulds
        WHERE moulds.ProductFamilyID=? AND moulds.ProductCode=?
        ORDER BY moulds.MouldNo''', product_family_id, product_code)
    moulds = rows(cursor)
    for mould in moulds:
        status = str(mould.get('Status') or '').strip().upper()
        if status != 'ACTIVE':
            status_reason = {
                'REPAIR': 'Mould under repair.',
                'UNDER_REPAIR': 'Mould under repair.',
                'RECONDITION': 'Mould under reconditioning.',
                'RETIRED': 'Mould retired.',
            }
            reason = status_reason.get(status, f'Mould is not production-ready (status: {status or "unknown"}).')
        elif requested_interval is None:
            reason = 'Invalid or unresolved production interval.'
        else:
            reason = find_assignment_conflict(
                cursor, 'mould', mould['MouldID'], requested_interval,
                exclude_press_production_id, production_date)
        mould['AvailabilityReason'] = reason
        mould['Available'] = reason is None
    return moulds


def read_press_production(cursor, production_id):
    has_shift_schema = _shift_schema_available(cursor)
    has_period_schema = _period_schema_available(cursor)
    shift_fields = (
        ('pp.ShiftMasterID, COALESCE(pp.ShiftCodeSnapshot,shift.ShiftCode) AS ShiftCode,'
         if has_period_schema else 'pp.ShiftMasterID, shift.ShiftCode,')
        if has_shift_schema else
        'CAST(NULL AS bigint) AS ShiftMasterID, CAST(NULL AS varchar(10)) AS ShiftCode,'
    )
    period_fields = (
        'pp.ShiftPeriodID,pp.PeriodLabelSnapshot,pp.PeriodStartTimeSnapshot,pp.PeriodEndTimeSnapshot,'
        if has_period_schema else
        'CAST(NULL AS bigint) AS ShiftPeriodID,CAST(NULL AS nvarchar(100)) AS PeriodLabelSnapshot,'
        'CAST(NULL AS time(0)) AS PeriodStartTimeSnapshot,CAST(NULL AS time(0)) AS PeriodEndTimeSnapshot,'
    )
    shift_join = (
        'LEFT JOIN dbo.ShiftMaster AS shift ON shift.id=pp.ShiftMasterID'
        if has_shift_schema else ''
    )
    shift_group = (
        ('pp.ShiftMasterID,pp.ShiftCodeSnapshot,shift.ShiftCode,'
         if has_period_schema else 'pp.ShiftMasterID,shift.ShiftCode,')
        if has_shift_schema else ''
    )
    period_group = (
        'pp.ShiftPeriodID,pp.PeriodLabelSnapshot,pp.PeriodStartTimeSnapshot,pp.PeriodEndTimeSnapshot,'
        if has_period_schema else ''
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
    cursor.execute(f'''SELECT pp.PressProductionID, pp.ProductionID, {shift_fields}
            {period_fields} pp.MachineCode,
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
                        {period_group}
                        pp.DispatchQty, pp.CounterQty, pp.CuringQty, pp.MouldID, mould.MouldNo, mould.MouldName,
                        pp.ProductionStartTime, pp.ProductionEndTime, pp.Remark, pp.CreatedAt, pp.UpdatedAt,
                        pp.ReleasedAt, pp.ReleasedBy,

                        usage.MouldUsageID, usage.ReconditionNo, usage.UsageCycles, usage.UsageDateTime,
                        equipment.DisplayOrder
                ORDER BY equipment.DisplayOrder, pp.MachineCode''', production_id)
    return rows(cursor)


def read_assigned_press_codes(cursor, production_id):
    """Read the press equipment assigned to one exact Production Lot."""
    cursor.execute('''SELECT DISTINCT pp.MachineCode
        FROM dbo.PressProduction AS pp
        JOIN dbo.EquipmentMaster AS equipment
          ON equipment.EquipmentCode=pp.MachineCode
        WHERE pp.ProductionID=?
          AND equipment.EquipmentType='PRESS'
        ORDER BY pp.MachineCode''', production_id)
    return [row[0] for row in cursor.fetchall()]


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
                         allow_incomplete=False, require_period=False,
                         period_config=None, cutoff_time=None):
    shift_code = str(data.get('ShiftCode') or '').strip()
    if not shift_code or len(shift_code) > 10:
        raise ValueError('Choose an active Shift.')
    period_text = str(data.get('ShiftPeriodID') or '').strip()
    if require_period and (not period_text or not period_text.isdigit()):
        raise ValueError('Choose an active Shift Period.')
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
    if period_config:
        start_time, end_time = resolve_period_interval(
            production_date, period_config['StartTime'], period_config['EndTime'],
            data.get('ProductionStartTime'), data.get('ProductionEndTime'),
            cutoff_time or day_start_time)
    else:
        start_time, end_time = resolve_run_times(
            production_date, data.get('ProductionStartTime'), data.get('ProductionEndTime'),
            cutoff_time or day_start_time, allow_missing=allow_incomplete)
    return dict(ShiftCode=shift_code,
                ShiftPeriodID=int(period_text) if period_text.isdigit() else None,
                MachineCode=machine_code, MouldID=mould_id,
                DispatchQty=_optional_quantity(data.get('DispatchQty'), 'Dispatch Qty'),
                CounterQty=counter, CuringQty=curing,
                ProductionStartTime=start_time, ProductionEndTime=end_time,
                Remark=remark or None)


def _resolve_saved_lot_interval(production_date, cutoff_time, lot_start, lot_end):
    if lot_start is None or lot_end is None:
        raise ValueError(
            'กรุณากรอกและบันทึกเวลาเริ่มต้นและเวลาสิ้นสุดของ Lot ก่อนเพิ่ม Fitting')
    return resolve_effective_interval(
        production_date, cutoff_time, None, None, lot_start, lot_end)


def _resolve_new_assignment_interval(production_date, cutoff_time, lot_interval,
                                     period_config, actual_start, actual_end):
    lot_interval_start, lot_interval_end = lot_interval
    has_start = bool(str(actual_start or '').strip())
    has_end = bool(str(actual_end or '').strip())
    if not has_start and not has_end:
        if period_config:
            period_start, period_end = period_interval(
                production_date, period_config['StartTime'],
                period_config['EndTime'], cutoff_time)
            start = max(lot_interval_start, period_start)
            end = min(lot_interval_end, period_end)
            if end <= start:
                raise ValueError('The saved Lot interval does not overlap the selected Shift Period.')
            return start, end
        return lot_interval
    if not has_start or not has_end:
        raise ValueError('Enter both actual Start and End times.')

    if period_config:
        return resolve_period_interval(
            production_date, period_config['StartTime'], period_config['EndTime'],
            actual_start, actual_end, cutoff_time)
    return resolve_run_times(
        production_date, actual_start, actual_end, cutoff_time)


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


def _query_active_shift(cursor, shift_code, production_date=None):
    if production_date is not None and _period_schema_available(cursor):
        cursor.execute('''SELECT master.id
            FROM dbo.ShiftMaster AS master
            CROSS APPLY (
                SELECT TOP (1) version.ShiftCode,version.IsActive
                FROM dbo.ShiftMasterVersion AS version
                WHERE version.ShiftMasterID=master.id
                  AND version.EffectiveFromDate<=?
                ORDER BY version.EffectiveFromDate DESC,version.VersionNumber DESC
            ) AS current_version
            WHERE current_version.ShiftCode=? AND current_version.IsActive=1''',
            production_date, shift_code)
    else:
        cursor.execute('''SELECT id FROM dbo.ShiftMaster
            WHERE ShiftCode=? AND IsActive=1''', shift_code)


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


def _resolve_assignment_period(cursor, period_id, shift_code, production_date):
    cursor.execute('''SELECT period.ShiftMasterID,shift_version.id,shift_version.ShiftCode,
            period_version.id,period_version.PeriodLabel,period_version.StartTime,
            period_version.EndTime
        FROM dbo.ShiftPeriodMaster AS period
        CROSS APPLY (
            SELECT TOP (1) v.id,v.PeriodLabel,v.StartTime,v.EndTime,v.IsActive
            FROM dbo.ShiftPeriodVersion AS v
            WHERE v.ShiftPeriodID=period.id AND v.EffectiveFromDate<=?
            ORDER BY v.EffectiveFromDate DESC,v.VersionNumber DESC
        ) AS period_version
        CROSS APPLY (
            SELECT TOP (1) v.id,v.ShiftCode,v.IsActive
            FROM dbo.ShiftMasterVersion AS v
            WHERE v.ShiftMasterID=period.ShiftMasterID AND v.EffectiveFromDate<=?
            ORDER BY v.EffectiveFromDate DESC,v.VersionNumber DESC
        ) AS shift_version
        WHERE period.id=? AND period_version.IsActive=1
          AND shift_version.IsActive=1 AND shift_version.ShiftCode=?''',
        production_date, production_date, period_id, shift_code)
    found = cursor.fetchone()
    if not found:
        raise ValueError('Choose an active Shift Period belonging to the selected Shift.')
    return dict(ShiftMasterID=found[0], ShiftMasterVersionID=found[1],
                ShiftCode=found[2], ShiftPeriodVersionID=found[3],
                PeriodLabel=found[4], StartTime=found[5], EndTime=found[6])


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
        status_reason = {
            'REPAIR': 'Mould is under repair.',
            'UNDER_REPAIR': 'Mould is under repair.',
            'RECONDITION': 'Mould is under reconditioning.',
            'RETIRED': 'Mould is retired.',
        }
        raise ValueError(status_reason.get(
            mould[1], 'Only ACTIVE Moulds can be assigned to Press production.'))
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
    for _, machine_code in press_identities:
        if machine_code is None:
            continue
        machine_code = str(machine_code).strip().upper()
        resources.add(f'FittingMES.PressMachine.{machine_code}')
    for _, mould_id in mould_identities:
        if mould_id is None:
            continue
        resources.add(f'FittingMES.PressMould.{mould_id}')
    for resource in sorted(resources):
        cursor.execute('''DECLARE @result int;
            EXEC @result = sys.sp_getapplock @Resource=?, @LockMode='Exclusive',
                @LockOwner='Transaction', @LockTimeout=10000;
            SELECT @result;''', resource)
        result = cursor.fetchone()
        if not result or result[0] < 0:
            raise ValueError('Press or Mould availability is being updated. Please retry.')


def _ensure_mould_available(cursor, requested_interval, mould_id,
                            production_date, exclude_press_production_id=None):
    reason = find_assignment_conflict(cursor, 'mould', mould_id,
                                      requested_interval, exclude_press_production_id,
                                      production_date)
    if reason:
        raise ValueError(reason)


def _ensure_press_available(cursor, requested_interval, machine_code,
                            production_date, exclude_press_production_id=None):
    reason = find_assignment_conflict(cursor, 'press', machine_code,
                                      requested_interval, exclude_press_production_id,
                                      production_date)
    if reason:
        raise ValueError(reason)


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
        has_period_schema = _period_schema_available(cursor)
        cutoff_config = (
            read_effective_cutoff(cursor, production_date, day_start_time)
            if has_period_schema else
            dict(ProductionDateCutoffVersionID=None, CutoffTime=day_start_time)
        )
        lot_start, lot_end = (None, None)
        lot_interval = None
        if is_new_press:
            lot_start, lot_end = read_lot_boundaries(cursor, production_id)
            lot_interval = _resolve_saved_lot_interval(
                production_date, cutoff_config['CutoffTime'], lot_start, lot_end)
        validation_data = data
        if downtime_only:
            validation_data = dict(data)
            for field in ('MouldID', 'DispatchQty', 'CounterQty', 'CuringQty',
                          'ProductionStartTime', 'ProductionEndTime', 'Remark',
                          'ShiftPeriodID'):
                validation_data.pop(field, None)
        period_config = None
        if (has_period_schema and not downtime_only
                and validation_data.get('ShiftPeriodID') not in (None, '')):
            period_config = _resolve_assignment_period(
                cursor, int(validation_data['ShiftPeriodID']),
                validation_data.get('ShiftCode'), production_date)
        values = validate_press_input(validation_data, require_mould=(
                          press_production_id is None and not downtime_only),
                          production_date=production_date, day_start_time=day_start_time,
                          allow_incomplete=True,
                          require_period=(has_period_schema and press_production_id is None
                                          and not downtime_only),
                          period_config=period_config,
                          cutoff_time=cutoff_config['CutoffTime'])
        new_requested_interval = None
        if is_new_press:
            new_requested_interval = _resolve_new_assignment_interval(
                production_date, cutoff_config['CutoffTime'], lot_interval,
                period_config,
                data.get('ProductionStartTime'), data.get('ProductionEndTime'))
            values['ProductionStartTime'], values['ProductionEndTime'] = new_requested_interval
        if period_config:
            shift_master_id = period_config['ShiftMasterID']
            values['ShiftCode'] = period_config['ShiftCode']
        else:
            shift_master_id = _resolve_active_shift(cursor, values['ShiftCode'])
        values['PeriodConfig'] = period_config
        values['CutoffConfig'] = cutoff_config
        if not downtime_only:
            _validate_press(cursor, product_family_id, product_code, values['MachineCode'])

        mould_only_edit = False
        if press_production_id is None:
            requested_interval = new_requested_interval
            _lock_allocation_keys(
                cursor, production_date,
                press_identities=[(shift_master_id, values['MachineCode'])],
                mould_identities=[(shift_master_id, values['MouldID'])])
            _ensure_press_available(
                cursor, requested_interval, values['MachineCode'], production_date)
            _ensure_mould_available(
                cursor, requested_interval, values['MouldID'], production_date)
            current_recondition_no = _lock_and_validate_mould(
                cursor, product_family_id, product_code, values['MouldID'])
            if has_period_schema:
                period = values['PeriodConfig']
                cursor.execute('''INSERT INTO dbo.PressProduction
                    (ProductionID,MachineCode,ShiftMasterID,DispatchQty,CounterQty,CuringQty,MouldID,
                     ProductionStartTime,ProductionEndTime,Remark,ShiftPeriodID,
                     ShiftMasterVersionID,ShiftPeriodVersionID,ShiftCodeSnapshot,
                     PeriodLabelSnapshot,PeriodStartTimeSnapshot,PeriodEndTimeSnapshot,
                     ProductionDateCutoffVersionID,ProductionDateCutoffSnapshot)
                    OUTPUT INSERTED.PressProductionID
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    production_id, values['MachineCode'], shift_master_id,
                    values['DispatchQty'], values['CounterQty'], values['CuringQty'],
                    values['MouldID'], values['ProductionStartTime'], values['ProductionEndTime'],
                    values['Remark'], period['ShiftPeriodID'], period['ShiftMasterVersionID'],
                    period['ShiftPeriodVersionID'], period['ShiftCode'], period['PeriodLabel'],
                    period['StartTime'], period['EndTime'],
                    cutoff_config['ProductionDateCutoffVersionID'],
                    cutoff_config['CutoffTime'])
            else:
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
            cursor.execute(f'''SELECT PressProductionID, MachineCode, MouldID, CounterQty,
                                     ProductionStartTime, ProductionEndTime, ShiftMasterID, ReleasedAt,
                                     DispatchQty, CuringQty, Remark
                                     {',ShiftPeriodID,ShiftMasterVersionID,ShiftPeriodVersionID,'
                                      'ShiftCodeSnapshot,PeriodLabelSnapshot,PeriodStartTimeSnapshot,'
                                      'PeriodEndTimeSnapshot,ProductionDateCutoffVersionID,'
                                      'ProductionDateCutoffSnapshot' if has_period_schema else ''}
                FROM dbo.PressProduction WITH (UPDLOCK,HOLDLOCK)
                WHERE PressProductionID=? AND ProductionID=?''', press_production_id, production_id)
            existing = cursor.fetchone()
            if not existing:
                raise ValueError('Press Production row not found for this Lot.')
            if existing[7] is not None:
                raise ValueError('Released Press Production rows cannot be edited; undo release first.')
            if (not downtime_only
                    and not str(data.get('ProductionStartTime') or '').strip()
                    and not str(data.get('ProductionEndTime') or '').strip()):
                values['ProductionStartTime'] = existing[4]
                values['ProductionEndTime'] = existing[5]
            if has_period_schema and not downtime_only and period_config is None:
                if existing[11] is not None:
                    period_config = _resolve_assignment_period(
                        cursor, existing[11], values['ShiftCode'], production_date)
                    values['PeriodConfig'] = period_config
                else:
                    shift_master_id = existing[6]
                    values['ShiftPeriodID'] = None
            if downtime_only:
                values['MachineCode'] = existing[1]
                values['MouldID'] = existing[2]
                values['ShiftCode'] = _read_shift_code(cursor, existing[6])
                shift_master_id = existing[6]
            if 'ProductionStartTime' not in data:
                values['ProductionStartTime'] = existing[4]
            if 'ProductionEndTime' not in data:
                values['ProductionEndTime'] = existing[5]
            if (not period_config and isinstance(existing[4], datetime)
                    and str(data.get('ProductionStartTime') or '').strip()
                    == existing[4].strftime('%H:%M')):
                values['ProductionStartTime'] = existing[4]
            if (not period_config and isinstance(existing[5], datetime)
                    and str(data.get('ProductionEndTime') or '').strip()
                    == existing[5].strftime('%H:%M')):
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
                lot_start, lot_end = read_lot_boundaries(cursor, production_id)
                requested_interval = resolve_effective_interval(
                    production_date, day_start_time,
                    values['ProductionStartTime'], values['ProductionEndTime'],
                    lot_start, lot_end)
                _ensure_press_available(
                    cursor, requested_interval, values['MachineCode'],
                    production_date,
                    exclude_press_production_id=press_production_id)
                if values['MouldID'] is not None:
                    _ensure_mould_available(
                        cursor, requested_interval, values['MouldID'],
                        production_date,
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
                if has_period_schema and period_config:
                    cursor.execute('''UPDATE dbo.PressProduction SET MachineCode=?,ShiftMasterID=?,
                        DispatchQty=?,CounterQty=?,CuringQty=?,MouldID=?,ProductionStartTime=?,
                        ProductionEndTime=?,Remark=?,ShiftPeriodID=?,ShiftMasterVersionID=?,
                        ShiftPeriodVersionID=?,ShiftCodeSnapshot=?,PeriodLabelSnapshot=?,
                        PeriodStartTimeSnapshot=?,PeriodEndTimeSnapshot=?,
                        ProductionDateCutoffVersionID=?,ProductionDateCutoffSnapshot=?,
                        UpdatedAt=SYSDATETIME()
                        WHERE PressProductionID=? AND ProductionID=?''',
                        values['MachineCode'], shift_master_id, values['DispatchQty'],
                        values['CounterQty'], values['CuringQty'], values['MouldID'],
                        values['ProductionStartTime'], values['ProductionEndTime'], values['Remark'],
                        period_config['ShiftPeriodID'], period_config['ShiftMasterVersionID'],
                        period_config['ShiftPeriodVersionID'], period_config['ShiftCode'],
                        period_config['PeriodLabel'], period_config['StartTime'],
                        period_config['EndTime'], cutoff_config['ProductionDateCutoffVersionID'],
                        cutoff_config['CutoffTime'], press_production_id, production_id)
                else:
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


def release_press_production(conn, production_id, press_production_id, released_by=None):
    try:
        cursor = conn.cursor()
        lock_lots(cursor)
        has_shift_schema = _shift_schema_available(cursor)
        cursor.execute('''SELECT PressProductionID, ReleasedAt,ProductionStartTime,ProductionEndTime
            FROM dbo.PressProduction WITH (UPDLOCK,HOLDLOCK)
            WHERE PressProductionID=? AND ProductionID=?''', press_production_id, production_id)
        existing = cursor.fetchone()
        if not existing:
            raise ValueError('Press Production row not found for this Lot.')
        if existing[1] is not None:
            conn.commit()
            return 'ALREADY_RELEASED'
        if not isinstance(existing[2], datetime) or not isinstance(existing[3], datetime):
            raise ValueError(
                'Cannot release a Press Production assignment without valid actual start and end times.')
        release_at = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
        end_time = existing[3]
        if release_at <= existing[2]:
            raise ValueError('An assignment cannot be released before its actual start time.')
        if end_time > release_at:
            end_time = release_at
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
            SET ProductionEndTime=?,ReleasedAt=?,ReleasedBy=?,UpdatedAt=SYSDATETIME()
            WHERE PressProductionID=? AND ProductionID=? AND ReleasedAt IS NULL''',
            end_time, release_at, released_by, press_production_id, production_id)
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
        cursor.execute(f'''SELECT pp.PressProductionID, pp.MouldID, pp.ReleasedAt, lot.ProdDate,
                              pp.ProductionStartTime, pp.ProductionEndTime
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
            shift_master_id, machine_code = existing[6], existing[7]
            day_start_time = read_day_start_time(cursor, existing[3])
            lot_start, lot_end = read_lot_boundaries(cursor, production_id)
            requested_interval = resolve_effective_interval(
                existing[3], day_start_time, existing[4], existing[5],
                lot_start, lot_end)
            _lock_allocation_keys(
                cursor, existing[3],
                press_identities=[(shift_master_id, machine_code)],
                mould_identities=[(shift_master_id, existing[1])])
            _ensure_press_available(
                cursor, requested_interval, machine_code,
                existing[3],
                exclude_press_production_id=press_production_id)
            if existing[1] is not None:
                try:
                    _ensure_mould_available(
                        cursor, requested_interval, existing[1],
                        existing[3],
                        exclude_press_production_id=press_production_id)
                except ValueError:
                    conn.commit()
                    return 'MOULD_ALREADY_REASSIGNED'
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
            if existing[1] is None:
                raise ValueError('Released assignment has no Mould; cannot restore it.')
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
    eligible_shifts = read_active_shifts(cursor, lot['ProdDate'])
    eligible_periods = read_active_periods(cursor, lot['ProdDate'])
    if product_family_id is None:
        return dict(press_production=rows_for_lot, day_start_time=day_start_time,
                    eligible_shifts=eligible_shifts, eligible_periods=eligible_periods,
                    eligible_presses=[], eligible_moulds=[],
                    press_product_error='This legacy Lot has no confirmed Product Family; Press/Mould assignment is unavailable.')
    if not _shift_schema_available(cursor):
        return dict(press_production=rows_for_lot, day_start_time=day_start_time,
                    eligible_shifts=eligible_shifts, eligible_periods=eligible_periods,
                    eligible_presses=[], eligible_moulds=[],
                    press_product_error='Shift-aware Press Production requires database migration 027 before use.')

    press_form = press_form or {}
    try:
        excluded_id = int(press_form.get('PressProductionID') or 0) or None
    except (TypeError, ValueError):
        excluded_id = None
    requested_interval = None
    interval_error = None
    lot_interval_error = None
    cutoff_config = (
        read_effective_cutoff(cursor, lot['ProdDate'], day_start_time)
        if _period_schema_available(cursor) else
        dict(ProductionDateCutoffVersionID=None, CutoffTime=day_start_time)
    )
    lot_start = lot_end = None
    try:
        day_start_time = read_day_start_time(cursor, lot['ProdDate'])
        lot_start, lot_end = read_lot_boundaries(cursor, lot['ProductionID'])
        lot_interval = _resolve_saved_lot_interval(
            lot['ProdDate'], cutoff_config['CutoffTime'], lot_start, lot_end)
        assignment_start = press_form.get('ProductionStartTime') or None
        assignment_end = press_form.get('ProductionEndTime') or None
        if excluded_id is not None:
            cursor.execute('''SELECT ProductionStartTime, ProductionEndTime
                FROM dbo.PressProduction
                WHERE PressProductionID=? AND ProductionID=?''',
                excluded_id, lot['ProductionID'])
            existing_times = cursor.fetchone()
            if not existing_times:
                raise ValueError('Press Production row not found for this Lot.')
            if 'ProductionStartTime' not in press_form:
                assignment_start = existing_times[0]
            if 'ProductionEndTime' not in press_form:
                assignment_end = existing_times[1]
        if not eligible_periods:
            if excluded_id is None:
                requested_interval = _resolve_new_assignment_interval(
                    lot['ProdDate'], cutoff_config['CutoffTime'], lot_interval,
                    None, assignment_start, assignment_end)
            else:
                requested_interval = resolve_effective_interval(
                    lot['ProdDate'], cutoff_config['CutoffTime'],
                    assignment_start, assignment_end, lot_start, lot_end)
    except (TypeError, ValueError) as exc:
        interval_error = str(exc)
        if lot_start is None or lot_end is None:
            lot_interval_error = (
                'กรุณากรอกและบันทึกเวลาเริ่มต้นและเวลาสิ้นสุดของ Lot ก่อนเพิ่ม Fitting')
    if interval_error:
        return dict(press_production=rows_for_lot, day_start_time=day_start_time,
                    eligible_shifts=eligible_shifts, eligible_periods=eligible_periods,
                    eligible_presses=[],
                    eligible_moulds=[],
                    press_product_error=None if lot_interval_error else interval_error,
                    lot_interval_error=lot_interval_error)

    presses_by_code = {}
    moulds_by_id = {}
    if eligible_periods:
        selected_period_id = str(press_form.get('ShiftPeriodID') or '')
        for period in eligible_periods:
            period_id = str(period['ShiftPeriodID'])
            try:
                default_interval = _resolve_new_assignment_interval(
                    lot['ProdDate'], cutoff_config['CutoffTime'], lot_interval,
                    period, None, None)
                interval = _resolve_new_assignment_interval(
                    lot['ProdDate'], cutoff_config['CutoffTime'], lot_interval,
                    period,
                    press_form.get('ProductionStartTime') if selected_period_id == period_id else None,
                    press_form.get('ProductionEndTime') if selected_period_id == period_id else None)
                period['PeriodLabelDisplay'] = (
                    f"{period['ShiftCode']} ({period['StartTime']:%H:%M}-"
                    f"{period['EndTime']:%H:%M}"
                    f"{' +1 day' if period['EndTime'] <= period['StartTime'] else ''})"
                )
                period['IntervalError'] = None
            except ValueError as exc:
                interval = None
                period['IntervalError'] = str(exc)
            period['Available'] = interval is not None
            period['AvailabilityReason'] = period['IntervalError']
            if interval is None:
                continue
            shift_code = str(period['ShiftCode'])
            period['ProductionStartTime'] = interval[0]
            period['ProductionEndTime'] = interval[1]
            period['DefaultStartTime'] = default_interval[0].strftime('%H:%M')
            period['DefaultEndTime'] = default_interval[1].strftime('%H:%M')
            presses = read_eligible_presses(cursor, product_family_id, product_code,
                lot['ProdDate'], shift_code, excluded_id, interval)
            for press in presses:
                option = presses_by_code.setdefault(press['PressCode'],
                    dict(press, AvailableShiftCodes=[], AvailablePeriodIDs=[]))
                if press['Available'] and shift_code not in option['AvailableShiftCodes']:
                    option['AvailableShiftCodes'].append(shift_code)
                if press['Available']:
                    option['AvailablePeriodIDs'].append(period_id)
            moulds = read_eligible_moulds(cursor, product_family_id, product_code,
                lot['ProdDate'], shift_code, excluded_id, interval)
            for mould in moulds:
                option = moulds_by_id.setdefault(mould['MouldID'],
                    dict(mould, AvailableShiftCodes=[], AvailablePeriodIDs=[]))
                if mould['Available'] and shift_code not in option['AvailableShiftCodes']:
                    option['AvailableShiftCodes'].append(shift_code)
                if mould['Available']:
                    option['AvailablePeriodIDs'].append(period_id)
    else:
        for shift in eligible_shifts:
            shift_code = str(shift['ShiftCode'])
            presses = read_eligible_presses(cursor, product_family_id, product_code,
                lot['ProdDate'], shift_code, excluded_id, requested_interval)
            for press in presses:
                option = presses_by_code.setdefault(press['PressCode'],
                    dict(press, AvailableShiftCodes=[]))
                if press['Available']:
                    option['AvailableShiftCodes'].append(shift_code)
            moulds = read_eligible_moulds(cursor, product_family_id, product_code,
                lot['ProdDate'], shift_code, excluded_id, requested_interval)
            for mould in moulds:
                option = moulds_by_id.setdefault(mould['MouldID'],
                    dict(mould, AvailableShiftCodes=[]))
                if mould['Available']:
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
                'AvailableShiftCodes': [], 'AvailabilityReason':
                    'Not eligible for the selected Product or inactive.',
                'Available': False, 'SubmittedUnavailable': True})

    return dict(press_production=rows_for_lot,
                day_start_time=day_start_time,
                eligible_shifts=eligible_shifts,
                eligible_periods=eligible_periods,
                eligible_presses=list(presses_by_code.values()),
                eligible_moulds=list(moulds_by_id.values()),
                press_product_error=None,
                lot_interval_error=None)