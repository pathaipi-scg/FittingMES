"""Read-only Press OEE report assembled from existing FittingMES sources."""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.lots import rows
from app.production_clock import clock_display
from app.production_data import read_shift_rules, resolve_shift
from app.print_prod import read_plan_week


LOSS_FIELDS = (
    ('SETUP', 'SetupMinutes'),
    ('CHANGEOVER', 'ChangeoverMinutes'),
    ('IDLE', 'IdleMinutes'),
    ('CLEAN', 'CleaningMinutes'),
    ('BREAKDOWN', 'BreakdownMinutes'),
)

LOGGER_CATEGORIES = (
    ('ก.1', 'ก', 'เตรียมการผลิต'),
    ('ก.2', 'ก', 'หยุดเปลี่ยนสี'),
    ('ก.3', 'ก', 'หยุดเปลี่ยนโมล'),
    ('ก.4', 'ก', 'หยุดเปลี่ยนผ้าตะแกรง'),
    ('ก.5', 'ก', 'ทำความสะอาดหลังผลิต'),
    ('ข.1', 'ข', 'ปรับตั้งเครื่องจักร'),
    ('ข.2', 'ข', 'เครื่องจักรหยุด < 10 นาที'),
    ('ค.1', 'ค', 'เครื่องจักรเสียตั้งแต่ 10 นาที ขึ้นไป'),
    ('ค.2', 'ค', 'ผู้รับเหมาทำไม่ทัน'),
    ('ค.3', 'ค', 'รถ Fork lift เสีย / วิ่งไม่ทัน'),
    ('ค.4', 'ค', 'วัตถุดิบหมด'),
    ('ค.5', 'ค', 'รอแบบ'),
    ('ค.6', 'ค', 'อื่น ๆ'),
    ('ง.1', 'ง', 'ไม่มีแผนผลิต'),
    ('ง.2', 'ง', 'ทดลองผลิต'),
    ('ง.3', 'ง', 'ที่กองเต็ม'),
    ('ง.4', 'ง', 'ไม่มีแบบ'),
    ('ง.5', 'ง', 'ไฟฟ้าดับ / น้ำประปาไม่ไหล'),
    ('ง.6', 'ง', 'ครอบไม่แห้งรอแกะ'),
    ('ง.7', 'ง', 'อื่น ๆ'),
)
LOGGER_CATEGORY_CODES = frozenset(category[0] for category in LOGGER_CATEGORIES)
ZERO_MINUTES = Decimal('0')
BREAKDOWN_STOP_ID = 7


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


def calculate_oee_row(row):
    result = dict(row)
    status = []
    if row.get('TimeIdentityAmbiguous'):
        status.append('Ambiguous Press/Shift downtime')
    if row.get('AssignmentShiftUnknown'):
        status.append('Assignment Shift unknown')
    start = row.get('ProductionStartTime')
    end = row.get('ProductionEndTime')
    actual_minutes = None
    if start is None or end is None:
        status.append('Missing Press Start/End time')
    elif not isinstance(start, datetime) or not isinstance(end, datetime):
        status.append('Invalid Press Start/End time')
    else:
        try:
            if end <= start:
                status.append('Invalid Press Start/End time')
            else:
                actual_minutes = Decimal(str((end - start).total_seconds())) / Decimal('60')
        except TypeError:
            status.append('Invalid Press Start/End time')
    result['StartDateTime'] = start if isinstance(start, datetime) else None
    result['EndDateTime'] = end if isinstance(end, datetime) else None
    result['Start'] = clock_display(result['StartDateTime'])
    result['End'] = clock_display(result['EndDateTime'])
    result['ActualProductionMinutes'] = actual_minutes

    losses = {}
    for code, field in LOSS_FIELDS:
        value = _decimal(row.get(field))
        losses[field] = value if value is not None else Decimal('0')
        if value is None or value < 0:
            status.append('Invalid loss time')
    result.update(losses)
    total_loss = sum(losses.values(), Decimal('0'))
    runtime = actual_minutes - total_loss if actual_minutes is not None else None
    result['TotalLoss'] = total_loss
    result['RunTime'] = runtime
    if actual_minutes is not None and total_loss > actual_minutes:
        status.append('Downtime exceeds actual production time')
    elif actual_minutes is not None and runtime is not None and runtime <= 0:
        status.append('Invalid Press production time')

    counter = _decimal(row.get('CounterQty'))
    curing = _decimal(row.get('CuringQty'))
    result['Counter'] = counter
    result['Curing'] = curing
    counts_valid = counter is not None and counter >= 0 and curing is not None and curing >= 0 and curing <= counter
    result['Reject'] = counter - curing if counts_valid else None
    if not counts_valid:
        status.append('Invalid count')

    speed = _decimal(row.get('StandardSpeed'))
    result['StandardSpeed'] = speed
    speed_valid = bool(row.get('CapabilityIsActive')) and speed is not None and speed > 0
    if not speed_valid:
        status.append('Speed not configured' if row.get('CapabilityIsActive') else 'Missing capability')

    time_valid = (actual_minutes is not None and actual_minutes > 0 and runtime is not None
                  and runtime > 0 and total_loss <= actual_minutes)
    result['Availability'] = _ratio(runtime, actual_minutes) if time_valid else None
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
    actual_minutes = sum((row['ActualProductionMinutes'] for row in eligible), Decimal('0'))
    runtime = sum((row['RunTime'] for row in eligible), Decimal('0'))
    counter = sum((row['Counter'] for row in eligible), Decimal('0'))
    curing = sum((row['Curing'] for row in eligible), Decimal('0'))
    theoretical = sum((row['StandardSpeed'] * row['RunTime'] for row in eligible), Decimal('0'))
    availability = _ratio(runtime, actual_minutes)
    performance = _ratio(counter, theoretical)
    quality = _ratio(curing, counter)
    return dict(ActualProductionMinutes=actual_minutes, RunTime=runtime, TotalCount=counter,
                GoodCount=curing, Availability=availability,
                Performance=performance, Quality=quality,
                OEE=(availability * performance * quality
                     if availability is not None and performance is not None and quality is not None else None),
                EligibleCount=len(eligible), ExcludedCount=len(rows_for_summary) - len(eligible))


def _valid_production_count(value):
    count = _decimal(value)
    if (count is None or count < 0
            or count != count.to_integral_value()):
        return None
    return count


def _production_episode_times(episodes, field):
    if not episodes:
        return ''
    values = []
    for index, episode in enumerate(episodes, start=1):
        moment = episode.get(field)
        clock = clock_display(moment) if isinstance(moment, datetime) else 'N/A'
        label = f'{index}: {clock}' if len(episodes) > 1 else clock
        values.append(label or 'N/A')
    return '; '.join(values)


def _episode_quantity_totals(episodes):
    counters = []
    curing_values = []
    for episode in episodes:
        counter = _valid_production_count(episode.get('CounterQty'))
        curing = _valid_production_count(episode.get('CuringQty'))
        if counter is None or curing is None or curing > counter:
            return None, None, None
        counters.append(counter)
        curing_values.append(curing)
    counter_total = sum(counters, ZERO_MINUTES)
    curing_total = sum(curing_values, ZERO_MINUTES)
    return counter_total, curing_total, counter_total - curing_total


def _episode_standard_speed(episode):
    speed = _decimal(episode.get('StandardSpeed'))
    if episode.get('CapabilityIsActive') and speed is not None and speed > 0:
        return speed
    return None


def _unique_episode_values(episodes, getter, formatter=None):
    values = []
    for episode in episodes:
        value = getter(episode)
        if value not in values:
            values.append(value)
    if formatter is None:
        return ' / '.join(str(value) if value is not None else 'N/A'
                          for value in values)
    return ' / '.join(formatter(value) if value is not None else 'N/A'
                      for value in values)


def _overlapping_episode_ids(episodes):
    indexed_intervals = []
    for index, episode in enumerate(episodes):
        start = episode.get('StartDateTime')
        end = episode.get('EndDateTime')
        if (isinstance(start, datetime) and isinstance(end, datetime)
                and end > start):
            indexed_intervals.append((index, start, end))
    overlapping = set()
    for left_index, (left_id, left_start, left_end) in enumerate(indexed_intervals):
        for right_id, right_start, right_end in indexed_intervals[left_index + 1:]:
            if left_start < right_end and right_start < left_end:
                overlapping.update((left_id, right_id))
    return overlapping


def build_press_production_summary(report_rows):
    presses = {}
    for episode in report_rows:
        machine_code = episode.get('MachineCode')
        if not machine_code:
            continue
        press = presses.setdefault(machine_code, dict(
            Press=machine_code, Episodes=[], UnknownShiftEpisodes=[],
            Shifts={'1': [], '2': []}))
        press['Episodes'].append(episode)
        shift = str(episode.get('Shift') or '')
        if (episode.get('ShiftMasterID') is None or shift not in press['Shifts']):
            press['UnknownShiftEpisodes'].append(episode)
        else:
            press['Shifts'][shift].append(episode)

    summaries = []
    for press in presses.values():
        episodes = press['Episodes']
        overlapping = _overlapping_episode_ids(episodes)
        episode_indexes = {
            id(episode): index for index, episode in enumerate(episodes)
        }
        mould_names = _unique_episode_values(
            episodes, lambda episode: episode.get('MouldName') or None)
        speeds = _unique_episode_values(
            episodes, _episode_standard_speed,
            lambda speed: format(speed.normalize(), 'f'))
        shift_summaries = {}
        known_minutes = []
        incomplete_minutes = False
        for shift, shift_episodes in press['Shifts'].items():
            if not shift_episodes:
                shift_summaries[shift] = dict(HasEpisodes=False)
                continue
            actual_values = [episode.get('ActualProductionMinutes')
                             for episode in shift_episodes]
            if (any(value is None or value <= 0 for value in actual_values)
                    or any(episode_indexes[id(episode)] in overlapping
                           for episode in shift_episodes)):
                production_minutes = None
                incomplete_minutes = True
            else:
                production_minutes = sum(actual_values, ZERO_MINUTES)
                known_minutes.append(production_minutes)
            counter, curing, reject = _episode_quantity_totals(shift_episodes)
            shift_summaries[shift] = dict(
                HasEpisodes=True,
                EpisodeCount=len(shift_episodes),
                Start=_production_episode_times(shift_episodes, 'StartDateTime'),
                End=_production_episode_times(shift_episodes, 'EndDateTime'),
                ProductionMinutes=production_minutes,
                Counter=counter,
                Curing=curing,
                WetReject=reject,
            )

        total_minutes = None
        if not press['UnknownShiftEpisodes'] and not incomplete_minutes:
            total_minutes = sum(known_minutes, ZERO_MINUTES)
        summaries.append(dict(
            Press=press['Press'],
            Mould=mould_names or 'N/A',
            StandardSpeed=speeds or 'N/A',
            Shift1=shift_summaries['1'],
            Shift2=shift_summaries['2'],
            TotalProductionMinutes=total_minutes,
            HasUnknownShift=bool(press['UnknownShiftEpisodes']),
        ))
    return summaries


def build_press_production_totals(summary_rows):
    totals = {}
    for shift, key in (('1', 'Shift1'), ('2', 'Shift2')):
        assigned = [press[key] for press in summary_rows
                    if press[key]['HasEpisodes']]
        if not assigned:
            totals[shift] = dict(
                HasEpisodes=False, ProductionMinutes=None,
                Counter=None, Curing=None, WetReject=None)
            continue
        quantities = {}
        for field in ('Counter', 'Curing'):
            values = [item[field] for item in assigned]
            quantities[field] = (
                None if any(value is None for value in values)
                else sum(values, ZERO_MINUTES)
            )
        total_counter = quantities['Counter']
        total_curing = quantities['Curing']
        production_minutes = [item['ProductionMinutes'] for item in assigned]
        totals[shift] = dict(
            HasEpisodes=True,
            ProductionMinutes=(
                None if any(value is None for value in production_minutes)
                else sum(production_minutes, ZERO_MINUTES)
            ),
            Counter=total_counter,
            Curing=total_curing,
            WetReject=(
                total_counter - total_curing
                if total_counter is not None and total_curing is not None
                else None
            ),
        )
    press_minutes = [press['TotalProductionMinutes'] for press in summary_rows]
    total_minutes = (
        None if not press_minutes or any(value is None for value in press_minutes)
        else sum(press_minutes, ZERO_MINUTES)
    )
    return dict(
        Shift1=totals['1'], Shift2=totals['2'],
        TotalProductionMinutes=total_minutes)


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
        'CAST(1 AS bit) AS AssignmentShiftUnknown,'
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
                 pp.ProductionStartTime, pp.ProductionEndTime,
                 capability.IsActive, capability.StandardSpeed,
                 pm.ProductName, equipment.DisplayOrder
        ORDER BY equipment.DisplayOrder, pp.MachineCode, pp.PressProductionID''', production_date)
    return rows(cursor)


def _normalized_shift_code(value):
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return None


def _oee_code(value):
    code = str(value or '').strip()
    return code or None


def _read_logger_mappings(cursor):
    cursor.execute("""SELECT main.StopId, main.StopType, main.OEEExcelCode AS MainCode,
            sub.SubStopId, sub.SubStopType, sub.OEEExcelCode AS SubCode,
            COALESCE(NULLIF(sub.OEEExcelCode,N''),NULLIF(main.OEEExcelCode,N'')) AS EffectiveCode
        FROM dbo.Fitting_StopType AS main
        LEFT JOIN dbo.Fitting_SubStopType AS sub ON sub.StopId=main.StopId
        ORDER BY main.StopId, sub.SubStopId""")
    master_rows = rows(cursor)
    cursor.execute("""SELECT sub.SubStopId, sub.StopId, sub.SubStopType, sub.OEEExcelCode
        FROM dbo.Fitting_SubStopType AS sub
        LEFT JOIN dbo.Fitting_StopType AS main ON main.StopId=sub.StopId
        WHERE main.StopId IS NULL
        ORDER BY sub.StopId, sub.SubStopId""")
    orphan_subtypes = rows(cursor)

    main_codes = {}
    codes_by_stop = {}
    available_codes = set()
    for item in master_rows:
        stop_id = item['StopId']
        main_codes[stop_id] = _oee_code(item.get('MainCode'))
        effective_code = _oee_code(item.get('EffectiveCode'))
        if effective_code:
            available_codes.add(effective_code)
            codes_by_stop.setdefault(stop_id, set()).add(effective_code)
    return dict(main_codes=main_codes, codes_by_stop=codes_by_stop,
                available_codes=available_codes,
                missing_codes=LOGGER_CATEGORY_CODES - available_codes,
                orphan_subtypes=orphan_subtypes)


def _new_press_shift_group(machine_code, shift_code, mapping):
    missing = set(mapping['missing_codes'])
    return dict(
        MachineCode=machine_code,
        Shift=shift_code,
        CategoryMinutes={
            code: None if code in missing else ZERO_MINUTES
            for code in LOGGER_CATEGORY_CODES
        },
        UnavailableCodes=missing,
        UnavailableReasons={
            code: 'Unavailable: no OEEExcelCode mapping in LOGGER masters'
            for code in missing
        },
        _MappedCodes=set(),
    )


def _press_shift_groups(report_rows, mapping):
    groups = []
    by_key = {}
    for report_row in report_rows:
        if report_row.get('AssignmentShiftUnknown'):
            continue
        machine_code = report_row.get('MachineCode')
        shift_code = _normalized_shift_code(report_row.get('Shift'))
        if not machine_code or shift_code is None:
            continue
        key = (machine_code, shift_code)
        if key not in by_key:
            group = _new_press_shift_group(machine_code, shift_code, mapping)
            by_key[key] = group
            groups.append(group)
    return groups, by_key


def _resolve_logger_shift(event, production_date, shift_rules):
    valid_shift_codes = {
        _normalized_shift_code(rule.get('ShiftID')) for rule in shift_rules
    }
    event_shift = _normalized_shift_code(event.get('ShiftID'))
    if event_shift in valid_shift_codes:
        return event_shift
    stop_datetime = event.get('StopDateTime')
    if isinstance(stop_datetime, datetime):
        resolved = resolve_shift(
            production_date, stop_datetime.time(), None, shift_rules)
        resolved_code = _normalized_shift_code(resolved)
        if resolved_code in valid_shift_codes:
            return resolved_code
    return None


def _unavailable_codes_for_event(event, mapping):
    stop_id = event.get('StopId')
    stop_codes = set(mapping['codes_by_stop'].get(stop_id, ()))
    main_code = mapping['main_codes'].get(stop_id)
    if main_code:
        stop_codes.add(main_code)
    return stop_codes or set(LOGGER_CATEGORY_CODES)


def _mark_group_unavailable(group, codes, reason):
    for code in codes:
        if code in LOGGER_CATEGORY_CODES:
            group['UnavailableCodes'].add(code)
            group['UnavailableReasons'][code] = reason
            group['CategoryMinutes'][code] = None


def _duration_minutes(event):
    duration = _decimal(event.get('DurationMin'))
    return duration if duration is not None and duration >= 0 else None


def _breakdown_details(events):
    details = []
    seen_ids = set()
    for event in events:
        if event.get('StopId') != BREAKDOWN_STOP_ID:
            continue
        event_id = event.get('LoggerEventID')
        if event_id is not None and event_id in seen_ids:
            continue
        if event_id is not None:
            seen_ids.add(event_id)
        details.append(dict(
            LoggerEventID=event_id,
            StartTime=clock_display(event.get('StartDateTime')) or None,
            StopTime=clock_display(event.get('StopDateTime')) or None,
            DurationMinutes=_decimal(event.get('DurationMin')),
            Cause=event.get('CauseLabel'),
            Machine=event.get('LoggerMachine'),
            MachineType=event.get('MainMachine'),
            # LoggerEvent and Fitting_MainMachine have no separate machine-code field.
            MachineCode=None,
            CorrectiveAction=event.get('Note'),
            ResolvedShift=event.get('ResolvedShift'),
        ))
    return details


def _process_logger_events(events, groups, groups_by_key, mapping,
                           production_date, shift_rules):
    unique_events = {}
    duplicate_ids = set()
    for raw_event in events:
        event_id = raw_event.get('LoggerEventID')
        if event_id in unique_events:
            duplicate_ids.add(event_id)
        else:
            unique_events[event_id] = dict(raw_event)

    unmapped_count = 0
    unmapped_minutes = ZERO_MINUTES
    unattributed_count = 0
    unattributed_minutes = ZERO_MINUTES
    for event_id, event in unique_events.items():
        instance = event.get('McInstanceNo')
        machine_prefix = event.get('MainMachine')
        instance_count = event.get('MainMachineCount')
        valid_instance = (
            machine_prefix == 'F' and isinstance(instance, int)
            and instance > 0 and instance_count is not None
            and instance <= int(instance_count)
        )
        event['LoggerMachine'] = (
            f'{machine_prefix}{instance}' if valid_instance else None)
        event['ResolvedShift'] = _resolve_logger_shift(
            event, production_date, shift_rules)
        duration = _duration_minutes(event)
        event['DurationValid'] = duration is not None
        event['EffectiveOEEExcelCode'] = _oee_code(
            event.get('EffectiveOEEExcelCode'))
        group = groups_by_key.get(
            (event['LoggerMachine'], event['ResolvedShift'])
        ) if valid_instance and event['ResolvedShift'] is not None else None

        if group is None:
            unattributed_count += 1
            if duration is not None:
                unattributed_minutes += duration
            event['AssignmentStatus'] = (
                'Not attributed: Press/Shift assignment is missing or unresolved')
            event['MappingStatus'] = 'Not attributed'
            if valid_instance and event['ResolvedShift'] is None:
                for candidate in groups:
                    if candidate['MachineCode'] == event['LoggerMachine']:
                        _mark_group_unavailable(
                            candidate, LOGGER_CATEGORY_CODES,
                            'Unavailable: LOGGER Shift could not be resolved')
            continue

        event['AssignmentStatus'] = (
            f"{group['MachineCode']} / Shift {group['Shift']}")
        if event_id in duplicate_ids:
            mapping_status = 'Unmapped: duplicate LoggerEventID result'
            affected_codes = LOGGER_CATEGORY_CODES
        elif event.get('InvalidSubStopRelationship'):
            mapping_status = 'Unmapped: SubStopId does not belong to StopId'
            affected_codes = _unavailable_codes_for_event(event, mapping)
        elif event['EffectiveOEEExcelCode'] not in LOGGER_CATEGORY_CODES:
            raw_code = event['EffectiveOEEExcelCode']
            mapping_status = (
                'Unmapped: no OEEExcelCode mapping' if raw_code is None
                else f'Unmapped: unsupported OEEExcelCode {raw_code}')
            affected_codes = (
                _unavailable_codes_for_event(event, mapping)
                if raw_code is None else set(LOGGER_CATEGORY_CODES))
        elif duration is None:
            mapping_status = 'Unavailable: invalid DurationMin'
            affected_codes = {event['EffectiveOEEExcelCode']}
        else:
            code = event['EffectiveOEEExcelCode']
            if code not in group['_MappedCodes']:
                group['CategoryMinutes'][code] = ZERO_MINUTES
            group['CategoryMinutes'][code] += duration
            group['_MappedCodes'].add(code)
            event['MappingStatus'] = f'Mapped: {code}'
            event['PressCode'] = group['MachineCode']
            event['ResolvedShift'] = group['Shift']
            continue

        event['MappingStatus'] = mapping_status
        event['PressCode'] = group['MachineCode']
        _mark_group_unavailable(
            group, affected_codes, 'Unavailable: unmapped LOGGER event(s)')
        unmapped_count += 1
        if duration is not None:
            unmapped_minutes += duration

    for group in groups:
        del group['_MappedCodes']
    return dict(
        events=list(unique_events.values()),
        groups=groups,
        unmapped_count=unmapped_count,
        unmapped_minutes=unmapped_minutes,
        unattributed_count=unattributed_count,
        unattributed_minutes=unattributed_minutes,
        duplicate_count=len(duplicate_ids),
    )


def _query_logger_details(cursor, production_date, report_rows):
    mapping = _read_logger_mappings(cursor)
    groups, groups_by_key = _press_shift_groups(report_rows, mapping)
    shift_rules = read_shift_rules(cursor, production_date)
    cursor.execute("""SELECT event.LoggerEventID, event.ProductionDate,
            event.StopDateTime, event.StartDateTime, event.DurationMin,
            event.McId, event.McInstanceNo, machine.Machine AS MainMachine,
            machine.No AS MainMachineCount, event.RelatedMcId,
            event.RelatedMcInstanceNo, event.SubMcId, event.SubMcInstanceNo,
            event.ShiftID, event.StopId, event.SubStopId, event.CauseId,
            event.MEO, event.Note, event.SourceType,
            event.MachineNameSnapshot, event.RelatedMachineSnapshot,
            event.SubMachineSnapshot,
            COALESCE(event.StopTypeSnapshot, stop_type.StopType) AS StopTypeLabel,
            COALESCE(event.SubStopTypeSnapshot, sub_label.SubStopType) AS SubStopTypeLabel,
            COALESCE(event.CauseSnapshot, cause.Cause) AS CauseLabel,
            stop_type.OEEExcelCode AS MainOEEExcelCode,
            sub_map.OEEExcelCode AS SubOEEExcelCode,
            COALESCE(NULLIF(sub_map.OEEExcelCode,N''),
                     NULLIF(stop_type.OEEExcelCode,N'')) AS EffectiveOEEExcelCode,
            CASE WHEN event.SubStopId IS NOT NULL
                      AND sub_map.SubStopId IS NULL
                 THEN CAST(1 AS bit) ELSE CAST(0 AS bit)
            END AS InvalidSubStopRelationship
        FROM dbo.LoggerEvent AS event
        JOIN dbo.Fitting_MainMachine AS machine
          ON machine.McId=event.McId AND machine.Machine='F'
        LEFT JOIN dbo.Fitting_StopType AS stop_type
          ON stop_type.StopId=event.StopId
        LEFT JOIN dbo.Fitting_SubStopType AS sub_label
          ON sub_label.SubStopId=event.SubStopId
        LEFT JOIN dbo.Fitting_SubStopType AS sub_map
          ON sub_map.SubStopId=event.SubStopId
         AND sub_map.StopId=event.StopId
        LEFT JOIN dbo.Fitting_Cause AS cause
          ON cause.CauseId=event.CauseId
        WHERE event.ProductionDate=?
        ORDER BY machine.Machine, event.McInstanceNo, event.ShiftID,
                 event.StopDateTime, event.LoggerEventID""", production_date)
    events = rows(cursor)
    mapping_result = _process_logger_events(
        events, groups, groups_by_key, mapping, production_date, shift_rules)
    mapping_result['mapping_missing_codes'] = sorted(mapping['missing_codes'])
    mapping_result['mapping_orphan_subtypes'] = mapping['orphan_subtypes']
    return mapping_result


def _sum_category_cells(cells):
    assigned = [cell['value'] for cell in cells if cell['assigned']]
    if not assigned:
        return dict(assigned=False, value=None)
    if any(value is None for value in assigned):
        return dict(assigned=True, value=None)
    return dict(assigned=True, value=sum(assigned, ZERO_MINUTES))


def build_logger_category_table(logger_report, production_summary_rows):
    machines = [dict(
        MachineCode=press['Press'],
        Shift1=press['Shift1']['HasEpisodes'],
        Shift2=press['Shift2']['HasEpisodes'],
    ) for press in production_summary_rows]
    groups = {
        (group['MachineCode'], str(group['Shift'])): group
        for group in logger_report['groups']
    }
    all_shifts_assigned = any(
        machine['Shift1'] or machine['Shift2'] for machine in machines)
    sections = []
    for section_code in ('ก', 'ข', 'ค', 'ง'):
        categories = [
            (code, label) for code, section, label in LOGGER_CATEGORIES
            if section == section_code
        ]
        section_rows = []
        for code, label in categories:
            shift_cells = {}
            for shift in ('1', '2'):
                cells = []
                for machine in machines:
                    assigned = machine[f'Shift{shift}']
                    group = groups.get((machine['MachineCode'], shift))
                    value = (
                        group['CategoryMinutes'].get(code)
                        if assigned and group is not None else None
                    )
                    cells.append(dict(assigned=assigned, value=value))
                shift_cells[shift] = cells
            all_shift_value = logger_report['all_shift_category_minutes'].get(code)
            all_shift_cell = dict(
                assigned=all_shifts_assigned,
                value=all_shift_value
                if code not in logger_report['all_shift_unavailable_codes']
                else None,
            )
            section_rows.append(dict(
                Kind='category', Code=code, Label=label,
                Shift1=shift_cells['1'],
                Shift2=shift_cells['2'],
                Shift1Total=_sum_category_cells(shift_cells['1']),
                Shift2Total=_sum_category_cells(shift_cells['2']),
                AllShiftsTotal=all_shift_cell,
            ))

        subtotal_shift_cells = {}
        for shift in ('1', '2'):
            subtotal_shift_cells[shift] = []
            for machine_index, machine in enumerate(machines):
                assignment = machine[f'Shift{shift}']
                values = [
                    row[f'Shift{shift}'][machine_index]['value']
                    for row in section_rows
                ]
                subtotal_shift_cells[shift].append(
                    _sum_category_cells([
                        dict(assigned=assignment, value=value)
                        for value in values
                    ]))
            shift_total = _sum_category_cells([
                row[f'Shift{shift}Total'] for row in section_rows
            ])
            subtotal_shift_cells[f'{shift}Total'] = shift_total
        all_shift_subtotal = _sum_category_cells([
            row['AllShiftsTotal'] for row in section_rows
        ])
        section_rows.append(dict(
            Kind='subtotal', Code='', Label=f'Subtotal ({section_code})',
            Shift1=subtotal_shift_cells['1'],
            Shift2=subtotal_shift_cells['2'],
            Shift1Total=subtotal_shift_cells['1Total'],
            Shift2Total=subtotal_shift_cells['2Total'],
            AllShiftsTotal=all_shift_subtotal,
        ))
        sections.append(dict(Code=section_code, Rows=section_rows))
    return dict(Machines=machines, Sections=sections)


def read_print_oee_context(cursor, production_date):
    plan_week = read_plan_week(cursor, production_date)
    report_rows = []
    for source in _query_rows(cursor, production_date):
        if source.get('ShiftMasterID') is not None:
            source['Shift'] = str(source['AssignmentShiftCode'])
        else:
            source['Shift'] = 'UNKNOWN'
            source['AssignmentShiftUnknown'] = True
        report_rows.append(calculate_oee_row(source))
    logger_report = _query_logger_details(cursor, production_date, report_rows)
    summaries = {str(shift): summarize([row for row in report_rows if str(row.get('Shift')) == str(shift)])
                 for shift in ('1', '2')}
    summaries['ALL DAY'] = summarize(report_rows)
    excluded = [row for row in report_rows if not row['Eligible']]
    logger_report['all_shift_category_minutes'] = {}
    logger_report['all_shift_unavailable_codes'] = set()
    for code in LOGGER_CATEGORY_CODES:
        if (code in logger_report['mapping_missing_codes']
                or logger_report['unattributed_count']
                or any(code in group['UnavailableCodes']
                       for group in logger_report['groups'])):
            logger_report['all_shift_category_minutes'][code] = None
            logger_report['all_shift_unavailable_codes'].add(code)
        else:
            logger_report['all_shift_category_minutes'][code] = sum(
                (group['CategoryMinutes'][code] for group in logger_report['groups']),
                ZERO_MINUTES)
    production_summary_rows = build_press_production_summary(report_rows)
    logger_category_table = build_logger_category_table(
        logger_report, production_summary_rows)
    return dict(
        rows=report_rows, summaries=summaries, excluded=excluded,
        production_summary_rows=production_summary_rows,
        production_summary_totals=build_press_production_totals(
            production_summary_rows),
        logger_category_table=logger_category_table,
        logger_report=logger_report, logger_categories=LOGGER_CATEGORIES,
        breakdown_details=_breakdown_details(logger_report['events']),
        shifts=('1', '2'),
        press_count=len({row['MachineCode'] for row in report_rows}),
        plan_week=plan_week,
    )