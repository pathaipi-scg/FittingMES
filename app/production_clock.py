"""Shared production-day clock resolution."""
import re
from datetime import date, datetime, time, timedelta


def read_day_start_time(cursor, production_date):
    cursor.execute("""SELECT TOP (1) DayStartTime FROM dbo.ProductionDayRuleHistory
        WHERE EffectiveFromDate<=? ORDER BY EffectiveFromDate DESC,RuleID DESC""", production_date)
    found = cursor.fetchone()
    if not found:
        raise ValueError('No Production Day rule exists for this Production Date.')
    if not isinstance(found[0], time):
        raise ValueError('The effective Production Day rule has an invalid DayStartTime.')
    return found[0]


def production_clock_datetime(production_date, clock_value, day_start_time):
    value = str(clock_value or '').strip()
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
        raise ValueError('Start and End must use HH:mm (24-hour time).')
    clock = time.fromisoformat(value)
    calendar_date = production_date + timedelta(days=1) if clock < day_start_time else production_date
    return datetime.combine(calendar_date, clock)


def resolve_run_times(production_date, start_value, end_value, day_start_time, allow_missing=False):
    start_value = str(start_value or '').strip()
    end_value = str(end_value or '').strip()
    if not start_value and not end_value:
        return None, None
    if not start_value or not end_value:
        raise ValueError('Enter both Start and End times for this Depallet run.')
    start = production_clock_datetime(production_date, start_value, day_start_time)
    end = production_clock_datetime(production_date, end_value, day_start_time)
    if end < start:
        raise ValueError('End time must be at or after Start within the selected Production Date.')
    return start, end


def clock_display(value):
    return value.strftime('%H:%M') if value is not None else ''
