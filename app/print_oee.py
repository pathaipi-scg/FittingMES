"""Read-only Press OEE report assembled from existing FittingMES sources."""
from datetime import date, datetime, time
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


def calculate_oee_row(row, production_date, day_start_time):
    result = dict(row)
    status = []
    try:
        start, end = resolve_run_times(
            production_date, _clock_value(row.get('ProductionStartTime')),
            _clock_value(row.get('ProductionEndTime')), day_start_time, allow_missing=True)
    except ValueError:
        start = end = None
        status.append('Invalid production time')
    result['StartDateTime'] = start
    result['EndDateTime'] = end
    result['Start'] = clock_display(start)
    result['End'] = clock_display(end)
    planned = (Decimal(str((end - start).total_seconds())) / Decimal('60')
               if start is not None and end is not None else None)
    result['PlannedTime'] = planned
    if planned is None or planned <= 0:
        status.append('Invalid production time')

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
    if planned is not None and (total_loss > planned or runtime is None or runtime <= 0):
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

    time_valid = planned is not None and planned > 0 and runtime is not None and runtime > 0 and total_loss <= planned
    result['Availability'] = _ratio(runtime, planned) if time_valid else None
    result['Quality'] = _ratio(curing, counter) if counts_valid and counter > 0 else None
    theoretical = speed * runtime if speed_valid and time_valid else None
    result['TheoreticalOutput'] = theoretical
    result['Performance'] = _ratio(counter, theoretical) if counts_valid and theoretical is not None else None
    result['OEE'] = (result['Availability'] * result['Performance'] * result['Quality']
                     if time_valid and counts_valid and theoretical is not None and result['Quality'] is not None else None)
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
    cursor.execute('''
        SELECT pp.PressProductionID, pp.ProductionID, lot.ProdDate, lot.Shift,
               lot.LotNo, lot.ProductFamily, lot.ProductCode,
               pp.MachineCode, equipment.EquipmentName AS MachineName,
               pp.MouldID, mould.MouldNo, mould.MouldName,
               pp.DispatchQty, pp.CounterQty, pp.CuringQty,
               pp.ProductionStartTime, pp.ProductionEndTime,
               capability.IsActive AS CapabilityIsActive,
               capability.StandardSpeed, pm.ProductName,
               COALESCE(SUM(CASE WHEN event.TimeType='SETUP' THEN event.DurationMin ELSE 0 END), 0) AS SetupMinutes,
               COALESCE(SUM(CASE WHEN event.TimeType='CHANGEOVER' THEN event.DurationMin ELSE 0 END), 0) AS ChangeoverMinutes,
               COALESCE(SUM(CASE WHEN event.TimeType='IDLE' THEN event.DurationMin ELSE 0 END), 0) AS IdleMinutes,
               COALESCE(SUM(CASE WHEN event.TimeType='CLEAN' THEN event.DurationMin ELSE 0 END), 0) AS CleaningMinutes,
               COALESCE(SUM(CASE WHEN event.TimeType='BREAKDOWN' THEN event.DurationMin ELSE 0 END), 0) AS BreakdownMinutes
        FROM dbo.ProductionLot AS lot
        JOIN dbo.PressProduction AS pp ON pp.ProductionID=lot.ProductionID
        JOIN dbo.EquipmentMaster AS equipment ON equipment.EquipmentCode=pp.MachineCode
        LEFT JOIN dbo.MouldMaster AS mould ON mould.MouldID=pp.MouldID
        LEFT JOIN dbo.ProductCodeMaster AS pm
          ON pm.ProductFamily=lot.ProductFamily AND pm.ProductCode=lot.ProductCode
        LEFT JOIN dbo.PressProductCapability AS capability
          ON capability.PressEquipmentCode=pp.MachineCode
         AND capability.ProductFamily=lot.ProductFamily
         AND capability.ProductCode=lot.ProductCode
        LEFT JOIN dbo.EquipmentTimeEvent AS event
          ON event.ProductionID=pp.ProductionID AND event.EquipmentCode=pp.MachineCode
         AND event.SourceType='MANUAL'
         AND event.TimeType IN ('SETUP','CHANGEOVER','IDLE','CLEAN','BREAKDOWN')
        WHERE lot.ProdDate=? AND lot.IsActive=1
        GROUP BY pp.PressProductionID, pp.ProductionID, lot.ProdDate, lot.Shift,
                 lot.LotNo, lot.ProductFamily, lot.ProductCode, pp.MachineCode,
                 equipment.EquipmentName, pp.MouldID, mould.MouldNo, mould.MouldName,
                 pp.DispatchQty, pp.CounterQty, pp.CuringQty, pp.ProductionStartTime,
                 pp.ProductionEndTime, capability.IsActive, capability.StandardSpeed,
                 pm.ProductName, equipment.DisplayOrder
        ORDER BY equipment.DisplayOrder, pp.MachineCode, pp.PressProductionID''', production_date)
    return rows(cursor)


def read_print_oee_context(cursor, production_date):
    day_start = read_day_start_time(cursor, production_date)
    plan_week = read_plan_week(cursor, production_date)
    shift_rules = read_shift_rules(cursor, production_date)
    report_rows = []
    for source in _query_rows(cursor, production_date):
        source['Shift'] = resolve_shift(production_date, _clock_value(source.get('ProductionStartTime')),
                                        source.get('Shift'), shift_rules)
        report_rows.append(calculate_oee_row(source, production_date, day_start))
    summaries = {str(shift): summarize([row for row in report_rows if str(row.get('Shift')) == str(shift)])
                 for shift in ('1', '2')}
    summaries['ALL DAY'] = summarize(report_rows)
    excluded = [row for row in report_rows if not row['Eligible']]
    return dict(rows=report_rows, summaries=summaries, excluded=excluded,
                day_start_time=day_start, shifts=('1', '2'),
                press_count=len({row['MachineCode'] for row in report_rows}),
                plan_week=plan_week)