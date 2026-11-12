from datetime import datetime, time, timedelta

from app.lots import rows


def read_press_assignments(cursor, production_date):
    cursor.execute('''SELECT pp.PressProductionID, pp.ProductionID, lot.LotNo,
            lot.ProdDate, lot.IsActive AS LotIsActive, pp.MachineCode,
            equipment.EquipmentName AS PressName, pp.MouldID,
            mould.MouldNo, mould.MouldName, shift.ShiftCode,
            pp.ProductionStartTime, pp.ProductionEndTime, pp.ReleasedAt
        FROM dbo.PressProduction AS pp
        JOIN dbo.ProductionLot AS lot
          ON lot.ProductionID=pp.ProductionID
        LEFT JOIN dbo.ShiftMaster AS shift
          ON shift.id=pp.ShiftMasterID
        LEFT JOIN dbo.EquipmentMaster AS equipment
          ON equipment.EquipmentCode=pp.MachineCode
        LEFT JOIN dbo.MouldMaster AS mould
          ON mould.MouldID=pp.MouldID
        WHERE lot.ProdDate=?
        ORDER BY pp.MachineCode, shift.ShiftCode, pp.ProductionStartTime,
                 lot.LotNo, pp.PressProductionID''',
        production_date)
    return rows(cursor)


def _format_timestamp(value, production_date):
    if not isinstance(value, datetime):
        return '—'
    if value.date() == production_date:
        return value.strftime('%H:%M')
    if value.date() == production_date + timedelta(days=1):
        return f'{value:%H:%M} (+1 day)'
    return value.strftime('%Y-%m-%d %H:%M')


def _timeline_position(start, end, production_date):
    if not isinstance(start, datetime) or not isinstance(end, datetime) or end <= start:
        return None, None
    axis_start = datetime.combine(production_date, time.min)
    axis_end = axis_start + timedelta(days=2)
    clipped_start = max(start, axis_start)
    clipped_end = min(end, axis_end)
    if clipped_end <= clipped_start:
        return None, None
    axis_minutes = 2 * 24 * 60
    left = (clipped_start - axis_start).total_seconds() / 60 / axis_minutes * 100
    width = (clipped_end - clipped_start).total_seconds() / 60 / axis_minutes * 100
    return round(left, 4), round(width, 4)


def _actual_interval(row):
    start = row.get('ProductionStartTime')
    end = row.get('ProductionEndTime')
    if (isinstance(start, datetime) and isinstance(end, datetime)
            and end > start):
        return start, end
    return None


def _overlap_warnings(assignments):
    overlap_count = 0
    for row in assignments:
        row['OverlapWarnings'] = []
        row['IncompleteInterval'] = (
            row.get('ProductionStartTime') is None
            or row.get('ProductionEndTime') is None
        )
        row['InvalidInterval'] = False
        if (row.get('ProductionStartTime') is not None
                and row.get('ProductionEndTime') is not None
                and _actual_interval(row) is None):
            row['InvalidInterval'] = True
        if row['IncompleteInterval']:
            missing = []
            if row.get('ProductionStartTime') is None:
                missing.append('start')
            if row.get('ProductionEndTime') is None:
                missing.append('end')
            row['IntervalWarning'] = 'Missing ' + ' and '.join(missing) + ' time; overlap cannot be verified.'
        elif row['InvalidInterval']:
            row['IntervalWarning'] = 'End is not later than Start; overlap cannot be verified.'
        else:
            row['IntervalWarning'] = None

    active = [row for row in assignments
              if row.get('ReleasedAt') is None and _actual_interval(row)]
    for index, first in enumerate(active):
        first_interval = _actual_interval(first)
        for second in active[index + 1:]:
            second_interval = _actual_interval(second)
            overlaps_press = (
                first.get('MachineCode') is not None
                and first.get('MachineCode') == second.get('MachineCode')
            )
            overlaps_mould = (
                first.get('MouldID') is not None
                and first.get('MouldID') == second.get('MouldID')
            )
            if (not overlaps_press and not overlaps_mould) or not (
                first_interval[0] < second_interval[1]
                and second_interval[0] < first_interval[1]
            ):
                continue
            overlap_count += 1
            overlap_start = max(first_interval[0], second_interval[0])
            overlap_end = min(first_interval[1], second_interval[1])
            span = f'{overlap_start:%Y-%m-%d %H:%M}–{overlap_end:%Y-%m-%d %H:%M}'
            resources = []
            if overlaps_press:
                resources.append(f'Press {first["MachineCode"]}')
            if overlaps_mould:
                resources.append(f'Mould {first["MouldID"]}')
            description = (
                f'{", ".join(resources)} overlaps assignment '
                f'#{second["PressProductionID"]} ({span}).'
            )
            first['OverlapWarnings'].append(description)
            reverse_resources = []
            if overlaps_press:
                reverse_resources.append(f'Press {second["MachineCode"]}')
            if overlaps_mould:
                reverse_resources.append(f'Mould {second["MouldID"]}')
            second['OverlapWarnings'].append(
                f'{", ".join(reverse_resources)} overlaps assignment '
                f'#{first["PressProductionID"]} ({span}).'
            )
    return overlap_count


def read_press_assignment_context(cursor, production_date, press_filter=None,
                                  shift_filter=None, mould_filter=None):
    assignments = read_press_assignments(cursor, production_date)
    overlap_count = _overlap_warnings(assignments)
    presses = sorted({str(row['MachineCode']) for row in assignments
                      if row.get('MachineCode') is not None})
    shifts = sorted({str(row['ShiftCode']) for row in assignments
                     if row.get('ShiftCode') is not None})
    moulds_by_id = {
        str(row['MouldID']): (
            f"{row.get('MouldNo') or ('Mould ' + str(row['MouldID']))}"
        )
        for row in assignments if row.get('MouldID') is not None
    }

    filtered = []
    for row in assignments:
        if press_filter and str(row.get('MachineCode') or '') != str(press_filter):
            continue
        if shift_filter and str(row.get('ShiftCode') or '') != str(shift_filter):
            continue
        if mould_filter and str(row.get('MouldID') or '') != str(mould_filter):
            continue
        row = dict(row)
        row['ShiftPeriodDisplay'] = '—'
        row['ReleasedStatus'] = 'Released' if row.get('ReleasedAt') is not None else 'Active'
        row['LotStatus'] = 'Active Lot' if row.get('LotIsActive') else 'Inactive Lot'
        row['StartDisplay'] = _format_timestamp(
            row.get('ProductionStartTime'), production_date)
        row['EndDisplay'] = _format_timestamp(
            row.get('ProductionEndTime'), production_date)
        row['TimelineLeft'], row['TimelineWidth'] = _timeline_position(
            row.get('ProductionStartTime'), row.get('ProductionEndTime'),
            production_date)
        filtered.append(row)

    ticks = []
    for hour in range(0, 49, 6):
        ticks.append(dict(
            Label=f'{hour % 24:02d}:00' + (
                f' +{hour // 24} day' if hour >= 24 else ''),
            Position=hour / 48 * 100,
        ))
    return dict(
        assignments=filtered,
        press_options=presses,
        shift_options=shifts,
        mould_options=[dict(MouldID=key, Label=value)
                       for key, value in sorted(moulds_by_id.items())],
        selected_press=str(press_filter or ''),
        selected_shift=str(shift_filter or ''),
        selected_mould=str(mould_filter or ''),
        overlap_count=overlap_count,
        timeline_ticks=ticks,
    )
