from datetime import date, datetime, time, timedelta
from app.production_clock import read_day_start_time, production_clock_datetime


def _resolve_boundary(value, production_date, day_start_time):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, time):
        value = value.strftime('%H:%M')
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return production_clock_datetime(production_date, text, day_start_time)


def resolve_effective_interval(production_date, day_start_time,
                               assignment_start, assignment_end,
                               lot_start, lot_end):
    start_value = assignment_start if assignment_start is not None else lot_start
    end_value = assignment_end if assignment_end is not None else lot_end
    start = _resolve_boundary(start_value, production_date, day_start_time)
    end = _resolve_boundary(end_value, production_date, day_start_time)
    if start is None:
        raise ValueError('Production interval has no resolvable start time.')
    if end is not None and not isinstance(end_value, datetime) and end < start:
        end += timedelta(days=1)
    if end is not None and end <= start:
        raise ValueError('Production interval end must be later than its start.')
    return start, end


def _format_interval(start, end):
    end_label = end.strftime('%Y-%m-%d %H:%M') if end else 'ongoing'
    return f'{start:%Y-%m-%d %H:%M} - {end_label}'


def find_assignment_conflict(cursor, resource_type, resource_id, requested_interval,
                             exclude_press_production_id=None,
                             requested_production_date=None):
    if isinstance(requested_production_date, datetime):
        requested_production_date = requested_production_date.date()
    if not isinstance(requested_production_date, date):
        raise ValueError('Production Lot has an invalid Production Date.')
    if resource_type == 'press':
        predicate = 'assigned.MachineCode=?'
        parameters = [resource_id, exclude_press_production_id]
    elif resource_type == 'mould':
        predicate = 'assigned.MouldID=?'
        parameters = [resource_id, exclude_press_production_id]
    else:
        raise ValueError('Unknown production resource type.')

    cursor.execute(f'''SELECT assigned.PressProductionID, lot.LotNo, lot.ProdDate,
            assigned.ProductionStartTime, assigned.ProductionEndTime,
            production.ProductionStartTime, production.ProductionEndTime,
            day_rule.DayStartTime
        FROM dbo.PressProduction AS assigned WITH (UPDLOCK,HOLDLOCK)
        JOIN dbo.ProductionLot AS lot WITH (UPDLOCK,HOLDLOCK)
          ON lot.ProductionID=assigned.ProductionID
        LEFT JOIN dbo.ProductionData AS production WITH (HOLDLOCK)
          ON production.ProductionID=lot.ProductionID
        OUTER APPLY (
            SELECT TOP (1) day_rule.DayStartTime
            FROM dbo.ProductionDayRuleHistory AS day_rule
            WHERE day_rule.EffectiveFromDate<=lot.ProdDate
            ORDER BY day_rule.EffectiveFromDate DESC, day_rule.RuleID DESC
        ) AS day_rule
        WHERE lot.IsActive=1 AND assigned.ReleasedAt IS NULL
          AND {predicate}
          AND assigned.PressProductionID<>COALESCE(?,0)
        ORDER BY assigned.PressProductionID''',
        *parameters)
    requested_start, requested_end = requested_interval
    for (assignment_id, lot_no, production_date, assignment_start, assignment_end,
         lot_start, lot_end, day_start_time) in cursor.fetchall():
        try:
            if isinstance(production_date, datetime):
                production_date = production_date.date()
            if not isinstance(production_date, date) or not isinstance(day_start_time, time):
                raise ValueError('Production date or Production Day rule is unresolved.')
            existing_start, existing_end = resolve_effective_interval(
                production_date, day_start_time, assignment_start, assignment_end,
                lot_start, lot_end)
        except (TypeError, ValueError):
            if production_date != requested_production_date:
                continue
            return (f'Already assigned to Lot {lot_no} (assignment '
                    f'{assignment_id}) with an invalid or unresolved production interval.')
        overlaps = ((requested_end is None or existing_start < requested_end)
                    and (existing_end is None or requested_start < existing_end))
        if overlaps:
            return (f'This resource is already assigned for the selected interval to '
                    f'Lot {lot_no} during '
                    f'{_format_interval(existing_start, existing_end)}.')
    return None


def read_lot_boundaries(cursor, production_id):
    cursor.execute('''SELECT ProductionStartTime, ProductionEndTime
        FROM dbo.ProductionData WHERE ProductionID=?''', production_id)
    production = cursor.fetchone()
    return production if production else (None, None)


def validate_lot_resource_availability(cursor, production_id, production_date,
                                      lot_start, lot_end):
    cursor.execute('''SELECT PressProductionID, MachineCode, MouldID,
                             ProductionStartTime, ProductionEndTime
        FROM dbo.PressProduction
        WHERE ProductionID=? AND ReleasedAt IS NULL''', production_id)
    assignments = list(cursor.fetchall() or [])
    if not assignments:
        return
    if isinstance(production_date, datetime):
        production_date = production_date.date()
    if not isinstance(production_date, date):
        raise ValueError('Production Lot has an invalid Production Date.')
    day_start_time = read_day_start_time(cursor, production_date)
    for (assignment_id, machine_code, mould_id, assignment_start,
         assignment_end) in assignments:
        interval = resolve_effective_interval(
            production_date, day_start_time, assignment_start, assignment_end,
            lot_start, lot_end)
        for resource_type, resource_id in (('press', machine_code), ('mould', mould_id)):
            if resource_id is None:
                continue
            reason = find_assignment_conflict(
                cursor, resource_type, resource_id, interval, assignment_id,
                production_date)
            if reason:
                raise ValueError(reason)
