import json
from datetime import date, datetime, timedelta, timezone

from app.lots import rows
from app.shift_schedule import parse_clock, validate_periods


def _require_schema(cursor):
    cursor.execute("""SELECT CASE WHEN OBJECT_ID(N'dbo.ShiftMasterVersion', N'U') IS NOT NULL
        AND OBJECT_ID(N'dbo.ShiftPeriodMaster', N'U') IS NOT NULL
        AND OBJECT_ID(N'dbo.ShiftPeriodVersion', N'U') IS NOT NULL
        AND OBJECT_ID(N'dbo.ProductionDateCutoffVersion', N'U') IS NOT NULL
        THEN 1 ELSE 0 END""")
    if not cursor.fetchone()[0]:
        raise ValueError('Shift settings require migration 029.')


def _effective_date(value):
    text = str(value or '').strip()
    try:
        effective = date.fromisoformat(text)
    except ValueError:
        raise ValueError('Effective From must be a valid date.') from None
    today_bangkok = datetime.now(timezone(timedelta(hours=7))).date()
    if effective <= today_bangkok:
        raise ValueError('Configuration changes must take effect on a future Production Date.')
    return effective


def _lock_configuration(cursor):
    cursor.execute("""DECLARE @result int;
        EXEC @result=sys.sp_getapplock
            @Resource='FittingMES.ShiftConfiguration',
            @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=10000;
        SELECT @result""")
    if cursor.fetchone()[0] < 0:
        raise ValueError('Shift configuration is being changed. Please retry.')


def _next_version(cursor, table, identity_column, identity):
    cursor.execute(
        f'SELECT COALESCE(MAX(VersionNumber),0)+1 FROM dbo.{table} WITH (UPDLOCK,HOLDLOCK) WHERE {identity_column}=?',
        identity)
    return cursor.fetchone()[0]


def _require_latest_effective(cursor, table, identity_column, identity, effective):
    cursor.execute(
        f'SELECT MAX(EffectiveFromDate) FROM dbo.{table} WITH (UPDLOCK,HOLDLOCK) WHERE {identity_column}=?',
        identity)
    latest = cursor.fetchone()[0]
    if latest is not None and effective <= latest:
        raise ValueError('A configuration version already exists on or after that effective date.')


def _serialize(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _close_previous(cursor, table, identity_column, identity, effective):
    cursor.execute(
        f'''UPDATE dbo.{table}
            SET EffectiveToDate=DATEADD(day,-1,?)
            WHERE {identity_column}=? AND EffectiveFromDate=(
                SELECT MAX(EffectiveFromDate) FROM dbo.{table} WITH (UPDLOCK,HOLDLOCK)
                WHERE {identity_column}=? AND EffectiveFromDate<?)
              AND EffectiveToDate IS NULL''',
        effective, identity, identity, effective)


def _write_shift_version(cursor, shift_id, code, name, active, effective, reason, old_value):
    _close_previous(cursor, 'ShiftMasterVersion', 'ShiftMasterID', shift_id, effective)
    version = _next_version(cursor, 'ShiftMasterVersion', 'ShiftMasterID', shift_id)
    new_value = dict(ShiftCode=code, ShiftName=name, IsActive=active)
    cursor.execute('''INSERT dbo.ShiftMasterVersion
        (ShiftMasterID,VersionNumber,ShiftCode,ShiftName,IsActive,OldValue,NewValue,
         EffectiveFromDate,ChangeReason)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        shift_id, version, code, name, active, _serialize(old_value),
        _serialize(new_value), effective, reason or None)


def _write_period_version(cursor, period_id, label, order, start, end, active,
                          effective, reason, old_value):
    _close_previous(cursor, 'ShiftPeriodVersion', 'ShiftPeriodID', period_id, effective)
    version = _next_version(cursor, 'ShiftPeriodVersion', 'ShiftPeriodID', period_id)
    new_value = dict(PeriodLabel=label, DisplayOrder=order, StartTime=start,
                     EndTime=end, IsActive=active)
    cursor.execute('''INSERT dbo.ShiftPeriodVersion
        (ShiftPeriodID,VersionNumber,PeriodLabel,DisplayOrder,StartTime,EndTime,
         IsActive,OldValue,NewValue,EffectiveFromDate,ChangeReason)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        period_id, version, label, order, start, end, active,
        _serialize(old_value), _serialize(new_value), effective, reason or None)


def _validate_period_schedule(cursor, effective, candidate=None):
    cursor.execute('''SELECT master.id AS ShiftPeriodID, version.StartTime,
            version.EndTime, version.IsActive
        FROM dbo.ShiftPeriodMaster AS master
        CROSS APPLY (
            SELECT TOP (1) v.StartTime, v.EndTime, v.IsActive
            FROM dbo.ShiftPeriodVersion AS v
            WHERE v.ShiftPeriodID=master.id AND v.EffectiveFromDate<=?
            ORDER BY v.EffectiveFromDate DESC, v.VersionNumber DESC
        ) AS version''', effective)
    periods = rows(cursor)
    if candidate is not None:
        replaced = False
        for period in periods:
            if period['ShiftPeriodID'] == candidate['ShiftPeriodID']:
                period.update(candidate)
                replaced = True
                break
        if not replaced:
            periods.append(candidate)
    validate_periods(periods)


def read_shift_settings(cursor):
    _require_schema(cursor)
    cursor.execute('''SELECT v.id AS VersionID,v.ShiftMasterID,v.VersionNumber,
            v.ShiftCode,v.ShiftName,v.IsActive,v.OldValue,v.NewValue,v.ChangedAt,
            v.ChangedBy,v.EffectiveFromDate,v.EffectiveToDate,v.ChangeReason
        FROM dbo.ShiftMasterVersion AS v
        ORDER BY v.ShiftMasterID,v.EffectiveFromDate DESC,v.VersionNumber DESC''')
    shift_history = rows(cursor)
    cursor.execute('''SELECT p.id AS ShiftPeriodID,p.ShiftMasterID,v.id AS VersionID,
            v.VersionNumber,v.PeriodLabel,v.DisplayOrder,v.StartTime,v.EndTime,
            v.IsActive,v.OldValue,v.NewValue,v.ChangedAt,v.ChangedBy,
            v.EffectiveFromDate,v.EffectiveToDate,v.ChangeReason
        FROM dbo.ShiftPeriodMaster AS p
        JOIN dbo.ShiftPeriodVersion AS v ON v.ShiftPeriodID=p.id
        ORDER BY p.ShiftMasterID,v.DisplayOrder,v.EffectiveFromDate DESC,v.VersionNumber DESC''')
    period_history = rows(cursor)
    cursor.execute('''SELECT id AS VersionID,VersionNumber,CutoffTime,OldValue,
            NewValue,ChangedAt,ChangedBy,EffectiveFromDate,EffectiveToDate,ChangeReason
        FROM dbo.ProductionDateCutoffVersion
        ORDER BY EffectiveFromDate DESC,VersionNumber DESC''')
    cutoff_history = rows(cursor)
    return dict(shift_history=shift_history, period_history=period_history,
                cutoff_history=cutoff_history)


def read_effective_cutoff(cursor, production_date, fallback=None):
    cursor.execute('''SELECT TOP (1) id AS ProductionDateCutoffVersionID,
            VersionNumber,CutoffTime
        FROM dbo.ProductionDateCutoffVersion
        WHERE EffectiveFromDate<=?
        ORDER BY EffectiveFromDate DESC,VersionNumber DESC''', production_date)
    found = cursor.fetchone()
    if found:
        return dict(ProductionDateCutoffVersionID=found[0],
                    ProductionDateCutoffVersion=found[1], CutoffTime=found[2])
    return dict(ProductionDateCutoffVersionID=None,
                ProductionDateCutoffVersion=None, CutoffTime=fallback)


def resolve_new_production_date(cursor, timestamp, fallback_cutoff):
    from app.shift_schedule import production_date_for_timestamp
    if not isinstance(timestamp, datetime):
        timestamp = datetime.combine(timestamp, datetime.min.time())
    calendar_date = timestamp.date()
    cursor.execute("""SELECT OBJECT_ID(N'dbo.ProductionDateCutoffVersion', N'U')""")
    if not cursor.fetchone()[0]:
        return dict(ProductionDate=production_date_for_timestamp(
            timestamp, fallback_cutoff), **{
                'ProductionDateCutoffVersionID': None,
                'ProductionDateCutoffSnapshot': fallback_cutoff,
            })
    config = read_effective_cutoff(cursor, calendar_date, fallback_cutoff)
    return dict(ProductionDate=production_date_for_timestamp(
        timestamp, config['CutoffTime']),
        ProductionDateCutoffVersionID=config['ProductionDateCutoffVersionID'],
        ProductionDateCutoffSnapshot=config['CutoffTime'])


def resolve_shift_snapshot(cursor, shift_code, production_date):
    cursor.execute('''SELECT TOP (1) ShiftMasterID,ShiftCode
        FROM dbo.ShiftMasterVersion
        WHERE ShiftCode=? AND EffectiveFromDate<=? AND IsActive=1
        ORDER BY EffectiveFromDate DESC,VersionNumber DESC''',
        str(shift_code), production_date)
    found = cursor.fetchone()
    if found:
        return found[0], found[1]
    cursor.execute('''SELECT id,ShiftCode FROM dbo.ShiftMaster
        WHERE ShiftCode=? AND IsActive=1''', str(shift_code))
    found = cursor.fetchone()
    return (found[0], found[1]) if found else (None, None)


def save_shift(conn, shift_id, code, active, effective_from, reason=''):
    code = str(code or '').strip()
    if not code or len(code) > 10 or not code.isascii():
        raise ValueError('Shift number/code is required and must contain at most 10 ASCII characters.')
    effective = _effective_date(effective_from)
    try:
        cursor = conn.cursor()
        _require_schema(cursor)
        _lock_configuration(cursor)
        cursor.execute('''SELECT master.id
            FROM dbo.ShiftMaster AS master
            CROSS APPLY (
                SELECT TOP (1) version.ShiftCode,version.IsActive
                FROM dbo.ShiftMasterVersion AS version
                WHERE version.ShiftMasterID=master.id
                  AND version.EffectiveFromDate<=?
                ORDER BY version.EffectiveFromDate DESC,version.VersionNumber DESC
            ) AS current_version
            WHERE current_version.ShiftCode=? AND current_version.IsActive=1
              AND master.id<>COALESCE(?,0)''', effective, code, shift_id)
        if cursor.fetchone():
            raise ValueError('That Shift number is already active on the effective date.')
        if shift_id:
            _require_latest_effective(
                cursor, 'ShiftMasterVersion', 'ShiftMasterID', shift_id, effective)
            cursor.execute('''SELECT TOP (1) ShiftCode,ShiftName,IsActive
                FROM dbo.ShiftMasterVersion WHERE ShiftMasterID=? AND EffectiveFromDate<=?
                ORDER BY EffectiveFromDate DESC,VersionNumber DESC''', shift_id, effective)
            found = cursor.fetchone()
            if not found:
                raise ValueError('Shift not found for the effective date.')
            old_value = dict(ShiftCode=found[0], ShiftName=found[1], IsActive=bool(found[2]))
            _write_shift_version(cursor, int(shift_id), code, code, bool(active),
                                 effective, reason, old_value)
        else:
            cursor.execute('''INSERT dbo.ShiftMaster (ShiftCode,ShiftName,IsActive)
                OUTPUT INSERTED.id VALUES (?,?,?)''', code, code, bool(active))
            new_id = cursor.fetchone()[0]
            _write_shift_version(cursor, new_id, code, code, bool(active),
                                 effective, reason, {})
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def save_period(conn, shift_id, period_id, label, order, start, end,
                active, effective_from, reason=''):
    try:
        start = parse_clock(start, 'Period start')
        end = parse_clock(end, 'Period end')
        order = int(order)
    except (TypeError, ValueError):
        raise ValueError('Period order must be a positive whole number and both times must use HH:mm.') from None
    if order < 1:
        raise ValueError('Period order must be a positive whole number.')
    label = str(label or '').strip()
    if not label or len(label) > 100:
        raise ValueError('Period label is required and must be at most 100 characters.')
    effective = _effective_date(effective_from)
    try:
        cursor = conn.cursor()
        _require_schema(cursor)
        _lock_configuration(cursor)
        cursor.execute('SELECT id FROM dbo.ShiftMaster WHERE id=?', shift_id)
        if not cursor.fetchone():
            raise ValueError('Select an existing Shift.')
        cursor.execute('''SELECT TOP (1) IsActive
            FROM dbo.ShiftMasterVersion
            WHERE ShiftMasterID=? AND EffectiveFromDate<=?
            ORDER BY EffectiveFromDate DESC,VersionNumber DESC''', shift_id, effective)
        shift_version = cursor.fetchone()
        if not shift_version or not shift_version[0]:
            raise ValueError('A Shift Period can only be scheduled for an active Shift.')
        if period_id:
            _require_latest_effective(
                cursor, 'ShiftPeriodVersion', 'ShiftPeriodID', period_id, effective)
            cursor.execute('''SELECT TOP (1) v.PeriodLabel,v.DisplayOrder,v.StartTime,
                    v.EndTime,v.IsActive
                FROM dbo.ShiftPeriodMaster AS p
                JOIN dbo.ShiftPeriodVersion AS v ON v.ShiftPeriodID=p.id
                WHERE p.id=? AND p.ShiftMasterID=? AND v.EffectiveFromDate<=?
                ORDER BY v.EffectiveFromDate DESC,v.VersionNumber DESC''',
                period_id, shift_id, effective)
            found = cursor.fetchone()
            if not found:
                raise ValueError('Shift Period not found for the effective date.')
            old_value = dict(PeriodLabel=found[0], DisplayOrder=found[1],
                             StartTime=found[2], EndTime=found[3],
                             IsActive=bool(found[4]))
            candidate_id = int(period_id)
        else:
            cursor.execute('''INSERT dbo.ShiftPeriodMaster (ShiftMasterID)
                OUTPUT INSERTED.id VALUES (?)''', shift_id)
            candidate_id = cursor.fetchone()[0]
            old_value = {}
        candidate = dict(ShiftPeriodID=candidate_id, StartTime=start,
                         EndTime=end, IsActive=bool(active))
        _validate_period_schedule(cursor, effective, candidate)
        _write_period_version(cursor, candidate_id, label, order, start, end,
                              bool(active), effective, reason, old_value)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def save_cutoff(conn, cutoff, effective_from, reason=''):
    cutoff = parse_clock(cutoff, 'Production Date cutoff')
    effective = _effective_date(effective_from)
    try:
        cursor = conn.cursor()
        _require_schema(cursor)
        _lock_configuration(cursor)
        cursor.execute('''SELECT TOP (1) id,CutoffTime FROM dbo.ProductionDateCutoffVersion
            WHERE EffectiveFromDate<=? ORDER BY EffectiveFromDate DESC,VersionNumber DESC''',
            effective)
        previous = cursor.fetchone()
        cursor.execute('''SELECT MAX(EffectiveFromDate)
            FROM dbo.ProductionDateCutoffVersion WITH (UPDLOCK,HOLDLOCK)''')
        latest_effective = cursor.fetchone()[0]
        if latest_effective is not None and effective <= latest_effective:
            raise ValueError('A cutoff version already exists on or after that effective date.')
        old_value = {'CutoffTime': previous[1]} if previous else {}
        cursor.execute('''UPDATE dbo.ProductionDateCutoffVersion
            SET EffectiveToDate=DATEADD(day,-1,?)
            WHERE EffectiveFromDate=(SELECT MAX(EffectiveFromDate)
                FROM dbo.ProductionDateCutoffVersion WITH (UPDLOCK,HOLDLOCK)
                WHERE EffectiveFromDate<?) AND EffectiveToDate IS NULL''',
            effective, effective)
        cursor.execute('''SELECT COALESCE(MAX(VersionNumber),0)+1
            FROM dbo.ProductionDateCutoffVersion WITH (UPDLOCK,HOLDLOCK)''')
        version = cursor.fetchone()[0]
        new_value = {'CutoffTime': cutoff}
        cursor.execute('''INSERT dbo.ProductionDateCutoffVersion
            (VersionNumber,CutoffTime,OldValue,NewValue,EffectiveFromDate,ChangeReason)
            VALUES (?,?,?,?,?,?)''', version, cutoff, _serialize(old_value),
            _serialize(new_value), effective, reason or None)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
