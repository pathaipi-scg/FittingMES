import re
from datetime import date, datetime, time, timedelta, timezone


_CLOCK_RE = re.compile(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z')


def parse_clock(value, label='Time'):
    if isinstance(value, time):
        if value.tzinfo is not None:
            raise ValueError(f'{label} must not include a timezone.')
        return value.replace(second=0, microsecond=0)
    text = str(value or '').strip()
    if not _CLOCK_RE.fullmatch(text):
        raise ValueError(f'{label} must use HH:mm (24-hour time).')
    return time.fromisoformat(text)


def production_date_for_timestamp(timestamp, cutoff):
    if not isinstance(timestamp, datetime):
        raise ValueError('Timestamp must be a datetime.')
    cutoff_time = parse_clock(cutoff, 'Production Date cutoff')
    local_timestamp = timestamp
    if timestamp.utcoffset() is not None:
        local_timestamp = timestamp.astimezone(timezone(timedelta(hours=7)))
    production_date = local_timestamp.date()
    if local_timestamp.time().replace(tzinfo=None) < cutoff_time:
        production_date -= timedelta(days=1)
    return production_date


def period_interval(production_date, start_value, end_value, cutoff='07:00'):
    start_clock = parse_clock(start_value, 'Period start')
    end_clock = parse_clock(end_value, 'Period end')
    cutoff_clock = parse_clock(cutoff, 'Production Date cutoff')
    start_date = production_date + timedelta(days=1) if start_clock < cutoff_clock else production_date
    start = datetime.combine(start_date, start_clock)
    end_date = production_date + timedelta(days=1) if end_clock <= start_clock else production_date
    if end_date < start_date:
        end_date = start_date
    return start, datetime.combine(end_date, end_clock)


def period_contains_interval(production_date, period_start, period_end,
                             actual_start, actual_end, cutoff='07:00'):
    scheduled_start, scheduled_end = period_interval(
        production_date, period_start, period_end, cutoff)
    return (actual_start >= scheduled_start and actual_end is not None
            and actual_end > actual_start and actual_end <= scheduled_end)


def resolve_period_interval(production_date, period_start, period_end,
                            actual_start=None, actual_end=None, cutoff='07:00'):
    scheduled_start, scheduled_end = period_interval(
        production_date, period_start, period_end, cutoff)
    if not actual_start and not actual_end:
        return scheduled_start, scheduled_end
    if not actual_start or not actual_end:
        raise ValueError('Enter both actual Start and End times.')
    start_clock = parse_clock(actual_start, 'Assignment start')
    end_clock = parse_clock(actual_end, 'Assignment end')
    start_candidates = [
        datetime.combine(scheduled_start.date() + timedelta(days=offset), start_clock)
        for offset in (0, 1)
    ]
    starts = [value for value in start_candidates
              if scheduled_start <= value < scheduled_end]
    if not starts:
        raise ValueError('Assignment start is outside the selected Shift Period.')
    start = min(starts)
    end_candidates = [
        datetime.combine(start.date() + timedelta(days=offset), end_clock)
        for offset in (0, 1)
    ]
    ends = [value for value in end_candidates if start < value <= scheduled_end]
    if not ends:
        raise ValueError('Assignment end crosses the selected Shift Period boundary.')
    return start, min(ends)


def validate_periods(periods):
    intervals = []
    for period in periods:
        if not period.get('IsActive'):
            continue
        start = parse_clock(period.get('StartTime'), 'Period start')
        end = parse_clock(period.get('EndTime'), 'Period end')
        if start == end:
            raise ValueError('A Shift Period cannot have identical start and end times.')
        start_minute = start.hour * 60 + start.minute
        end_minute = end.hour * 60 + end.minute
        if end_minute <= start_minute:
            end_minute += 24 * 60
        intervals.append((period.get('ShiftPeriodID'), start_minute, end_minute))
        if end_minute > 24 * 60:
            intervals.append((period.get('ShiftPeriodID'), 0, end_minute - 24 * 60))
    for index, (period_id, start, end) in enumerate(intervals):
        for other_id, other_start, other_end in intervals[index + 1:]:
            if period_id != other_id and start < other_end and other_start < end:
                raise ValueError('Enabled Shift Periods cannot overlap.')
