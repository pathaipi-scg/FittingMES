"""Read-only Press OEE report assembled from existing FittingMES sources."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from app.lots import rows
from app.production_clock import clock_display, read_day_start_time, resolve_run_times
from app.production_data import read_shift_rules, resolve_shift
from app.print_prod import read_plan_week


LOSS_FIELDS = (
    ('SETUP', 'SetupMinutes'),
    ('CHANGEOVER', 'ChangeoverMinutes'),
    ('IDLE', 'IdleMinutes'),
    ('CLEAN', 'CleaningMinutes'),
    ('BREAKDOWN', 'BreakdownMinutes'),
)


def _decimal(value):
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _clock_value(value):
    if isinstance(value, datetime):
        return value.strftime('%H:%M')
    if isinstance(value, time):
        return value.strftime('%H:%M')
    text = str(value or '').strip()
    if ' ' in text:
        text = text.rsplit(' ', 1)[-1]
    return text[:5] if len(text) >= 5 else text


def _shift_interval(production_date, shift_code, shift_rules):
    if not shift_rules:
        raise ValueError('No configured Shift boundaries are available.')
    schedule = []
    for rule in shift_rules:
        start_value = rule['StartTime']
        if isinstance(start_value, datetime):
            start_value = start_value.time()
        elif not isinstance(start_value, time):
            start_value = time.fromisoformat(str(start_value))
        schedule.append((start_value, str(rule['ShiftID'])))
    schedule.sort(key=lambda item: (item[0], item[1]))
    matches = [index for index, (_, shift_id) in enumerate(schedule)
               if shift_id == str(shift_code)]
    if len(matches) != 1:
        raise ValueError(f'No unique configured boundary exists for Shift {shift_code}.')
    index = matches[0]
    start_time = schedule[index][0]
    end_time = schedule[(index + 1) % len(schedule)][0]
    end_date = production_date + timedelta(days=1) if end_time <= start_time else production_date
    return (datetime.combine(production_date, start_time),
            datetime.combine(end_date, end_time))


def calculate_oee_row(row, production_date, day_start_time, shift_rules=None):
    result = dict(row)
    status = []
    if row.get('TimeIdentityAmbiguous'):
        status.append('Ambiguous Press/Shift downtime')
    if row.get('AssignmentShiftUnknown'):
        status.append('Assignment Shift unknown')
    try:
        lot_start, lot_end = resolve_run_times(
            production_date, _clock_value(row.get('LotStartTime')),
            _clock_value(row.get('LotEndTime')), day_start_time, allow_missing=True)
    except ValueError:
        lot_start = lot_end = None
        status.append('Invalid production time')
    start = end = None
    planned = None
    if lot_start is None or lot_end is None:
        if 'Invalid production time' not in status:
            status.append('Invalid production time')
    elif not row.get('AssignmentShiftUnknown'):
        shift_code = row.get('AssignmentShiftCode') or row.get('Shift')
        try:
            shift_start, shift_end = _shift_interval(
                production_date, shift_code, shift_rules or ())
        except (TypeError, ValueError):
            status.append('Shift schedule unavailable')
        else:
            start = max(lot_start, shift_start)
            end = min(lot_end, shift_end)
            if end <= start:
                start = end = None
                status.append('No production time overlaps assigned Shift')
            else:
                planned = Decimal(str((end - start).total_seconds())) / Decimal('60')
    result['StartDateTime'] = start
    result['EndDateTime'] = end
    result['Start'] = clock_display(start)
    result['End'] = clock_display(end)
    result['PlannedTime'] = planned

    losses = {}
    for code, field in LOSS_FIELDS:
        value = _decimal(row.get(field))
        losses[field] = value if value is not None else Decimal('0')
        if value is None or value < 0:
            status.append('Invalid loss time')
    result.update(losses)
    total_loss = sum(losses.values(), Decimal('0'))
    runtime = planned - total_loss if planned is not None else None
    result['TotalLoss'] = total_loss
    result['RunTime'] = runtime
    if planned is not None and total_loss > planned:
        status.append('Downtime exceeds allocated Shift time')
    elif planned is not None and runtime is not None and runtime <= 0:
        status.append('Invalid production time')

    counter = _decimal(row.get('CounterQty'))
    curing = _decimal(row.get('CuringQty'))
    result['Counter'] = counter
    result['Curing'] = curing
    counts_valid = counter is not None and counter >= 0 and curing is not None and curing >= 0 and curing <= counter
    if not counts_valid:
        status.append('Invalid count')

    speed = _decimal(row.get('StandardSpeed'))
    result['StandardSpeed'] = speed
    speed_valid = bool(row.get('CapabilityIsActive')) and speed is not None and speed > 0
    if not speed_valid:
        status.append('Speed not configured' if row.get('CapabilityIsActive') else 'Missing capability')

    time_valid = (planned is not None and planned > 0 and runtime is not None
                  and runtime > 0 and total_loss <= planned)
    result['Availability'] = _ratio(runtime, planned) if time_valid else None
    result['Quality'] = _ratio(curing, counter) if counts_valid and counter > 0 else None
    theoretical = speed * runtime if speed_valid and time_valid else None
    result['TheoreticalOutput'] = theoretical
    result['Performance'] = _ratio(counter, theoretical) if counts_valid and theoretical is not None else None
    result['OEE'] = (result['Availability'] * result['Performance'] * result['Quality']
                     if time_valid and counts_valid and theoretical is not None
                     and result['Quality'] is not None
                     and not row.get('TimeIdentityAmbiguous')
                     and not row.get('AssignmentShiftUnknown') else None)
    result['Eligible'] = not status
    result['Status'] = 'OK' if result['Eligible'] else '; '.join(dict.fromkeys(status))
    return result


def summarize(rows_for_summary):
    eligible = [row for row in rows_for_summary if row['Eligible']]
    planned = sum((row['PlannedTime'] for row in eligible), Decimal('0'))
    runtime = sum((row['RunTime'] for row in eligible), Decimal('0'))
    counter = sum((row['Counter'] for row in eligible), Decimal('0'))
    curing = sum((row['Curing'] for row in eligible), Decimal('0'))
    theoretical = sum((row['StandardSpeed'] * row['RunTime'] for row in eligible), Decimal('0'))
    availability = _ratio(runtime, planned)
    performance = _ratio(counter, theoretical)
    quality = _ratio(curing, counter)
    return dict(PlannedTime=planned, RunTime=runtime, TotalCount=counter,
                GoodCount=curing, Availability=availability,
                Performance=performance, Quality=quality,
                OEE=(availability * performance * quality
                     if availability is not None and performance is not None and quality is not None else None),
                EligibleCount=len(eligible), ExcludedCount=len(rows_for_summary) - len(eligible))


def _query_rows(cursor, production_date):
    cursor.execute("""SELECT CASE WHEN COL_LENGTH(
        N'dbo.PressProduction', N'ShiftMasterID') IS NULL THEN 0 ELSE 1 END""")
    shift_schema = bool((cursor.fetchone() or (0,))[0])
    shift_fields = (
        'pp.ShiftMasterID, shift.ShiftCode AS AssignmentShiftCode,'
        if shift_schema else
        'CAST(NULL AS bigint) AS ShiftMasterID, '
        'CAST(NULL AS varchar(10)) AS AssignmentShiftCode,'
    )
    shift_join = (
        'LEFT JOIN dbo.ShiftMaster AS shift ON shift.id=pp.ShiftMasterID'
        if shift_schema else ''
    )
    episode_match = '''other.ProductionID=pp.ProductionID
         AND other.MachineCode=pp.MachineCode
         AND other.PressProductionID<>pp.PressProductionID
         AND (other.ShiftMasterID=pp.ShiftMasterID
              OR other.ShiftMasterID IS NULL
              OR pp.ShiftMasterID IS NULL)'''
    ambiguity_field = (
        f'''CASE WHEN EXISTS (
                 SELECT 1 FROM dbo.PressProduction AS other WHERE {episode_match}
             ) THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END AS TimeIdentityAmbiguous,'''
        if shift_schema else
        'CAST(0 AS bit) AS TimeIdentityAmbiguous,'
    )
    unknown_shift_field = (
        'CASE WHEN pp.ShiftMasterID IS NULL THEN CAST(1 AS bit) '
        'ELSE CAST(0 AS bit) END AS AssignmentShiftUnknown,'
        if shift_schema else
        'CAST(0 AS bit) AS AssignmentShiftUnknown,'
    )
    event_scope = (
        f'''AND pp.ShiftMasterID IS NOT NULL
             AND event.ShiftID=TRY_CONVERT(int,shift.ShiftCode)
             AND NOT EXISTS (
                 SELECT 1 FROM dbo.PressProduction AS other WHERE {episode_match})'''
        if shift_schema else ''
    )
    cursor.execute(f'''
        SELECT pp.PressProductionID, pp.ProductionID, lot.ProdDate, lot.Shift,
               lot.LotNo, lot.ProductFamily, lot.ProductCode,
               {shift_fields}
               {ambiguity_field}
               {unknown_shift_field}
               pp.MachineCode, equipment.EquipmentName AS MachineName,
               pp.MouldID, mould.MouldNo, mould.MouldName,
               pp.DispatchQty, pp.CounterQty, pp.CuringQty,
               lot_data.ProductionStartTime AS LotStartTime,
               lot_data.ProductionEndTime AS LotEndTime,
               capability.IsActive AS CapabilityIsActive,
               capability.StandardSpeed, pm.ProductName,
               COALESCE(SUM(CASE WHEN event.TimeType='SETUP' THEN event.DurationMin ELSE 0 END), 0) AS SetupMinutes,
               COALESCE(SUM(CASE WHEN event.TimeType='CHANGEOVER' THEN event.DurationMin ELSE 0 END), 0) AS ChangeoverMinutes,
               COALESCE(SUM(CASE WHEN event.TimeType='IDLE' THEN event.DurationMin ELSE 0 END), 0) AS IdleMinutes,
               COALESCE(SUM(CASE WHEN event.TimeType='CLEAN' THEN event.DurationMin ELSE 0 END), 0) AS CleaningMinutes,
               COALESCE(SUM(CASE WHEN event.TimeType='BREAKDOWN' THEN event.DurationMin ELSE 0 END), 0) AS BreakdownMinutes
        FROM dbo.ProductionLot AS lot
        JOIN dbo.PressProduction AS pp ON pp.ProductionID=lot.ProductionID
        LEFT JOIN dbo.ProductionData AS lot_data ON lot_data.ProductionID=lot.ProductionID
        JOIN dbo.EquipmentMaster AS equipment ON equipment.EquipmentCode=pp.MachineCode
        LEFT JOIN dbo.MouldMaster AS mould ON mould.MouldID=pp.MouldID
        LEFT JOIN dbo.ProductCodeMaster AS pm
          ON pm.ProductFamilyID=lot.ProductFamilyID AND pm.ProductCode=lot.ProductCode
        LEFT JOIN dbo.PressProductCapability AS capability
          ON capability.PressEquipmentCode=pp.MachineCode
         AND capability.ProductFamilyID=lot.ProductFamilyID
         AND capability.ProductCode=lot.ProductCode
        {shift_join}
        LEFT JOIN dbo.EquipmentTimeEvent AS event
          ON event.ProductionID=pp.ProductionID AND event.EquipmentCode=pp.MachineCode
         AND event.SourceType='MANUAL'
         AND event.TimeType IN ('SETUP','CHANGEOVER','IDLE','CLEAN','BREAKDOWN')
         {event_scope}
        WHERE lot.ProdDate=? AND lot.IsActive=1
        GROUP BY pp.PressProductionID, pp.ProductionID, lot.ProdDate, lot.Shift,
                 {('pp.ShiftMasterID, shift.ShiftCode,' if shift_schema else '')}
                 lot.LotNo, lot.ProductFamily, lot.ProductCode, pp.MachineCode,
                 equipment.EquipmentName, pp.MouldID, mould.MouldNo, mould.MouldName,
                 pp.DispatchQty, pp.CounterQty, pp.CuringQty,
                 lot_data.ProductionStartTime, lot_data.ProductionEndTime,
                 capability.IsActive, capability.StandardSpeed,
                 pm.ProductName, equipment.DisplayOrder
        ORDER BY equipment.DisplayOrder, pp.MachineCode, pp.PressProductionID''', production_date)
    return rows(cursor)


def read_print_oee_context(cursor, production_date):
    day_start = read_day_start_time(cursor, production_date)
    plan_week = read_plan_week(cursor, production_date)
    shift_rules = read_shift_rules(cursor, production_date)
    report_rows = []
    for source in _query_rows(cursor, production_date):
        if source.get('ShiftMasterID') is not None:
            source['Shift'] = str(source['AssignmentShiftCode'])
        elif source.get('AssignmentShiftUnknown'):
            source['Shift'] = 'UNKNOWN'
        else:
            source['Shift'] = resolve_shift(
                production_date, _clock_value(source.get('LotStartTime')),
                source.get('Shift'), shift_rules)
        report_rows.append(calculate_oee_row(source, production_date, day_start, shift_rules))
    summaries = {str(shift): summarize([row for row in report_rows if str(row.get('Shift')) == str(shift)])
                 for shift in ('1', '2')}
    summaries['ALL DAY'] = summarize(report_rows)
    excluded = [row for row in report_rows if not row['Eligible']]
    return dict(rows=report_rows, summaries=summaries, excluded=excluded,
                day_start_time=day_start, shifts=('1', '2'),
                press_count=len({row['MachineCode'] for row in report_rows}),
                plan_week=plan_week)