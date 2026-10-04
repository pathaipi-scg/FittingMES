"""Read-only LOGGER Master loading and hierarchy normalization helpers."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from app.production_clock import production_clock_datetime, read_day_start_time
from app.production_data import read_shift_rules, resolve_shift

DIRECT_SUB = "DIRECT_SUB"
RELATED_MAIN = "RELATED_MAIN"
RELATED_SUB = "RELATED_SUB"
SMDT_STOP_ID = 6
BD_STOP_ID = 7


def cause_catalog_stop_id(event_stop_id):
    return SMDT_STOP_ID if event_stop_id == BD_STOP_ID else event_stop_id


@dataclass(frozen=True)
class LoggerMasters:
    main_machines: list[dict[str, Any]]
    sub_machines: list[dict[str, Any]]
    stop_types: list[dict[str, Any]]
    sub_stop_types: list[dict[str, Any]]
    causes: list[dict[str, Any]]


class LoggerResolutionError(ValueError):
    """Raised when a LOGGER selection cannot be normalized safely."""


class LoggerValidationError(ValueError):
    """Raised when final LOGGER SAVE input is invalid."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LoggerSaveInput:
    production_date: Any
    stop: Any
    start: Any
    mc_id: Any
    mc_instance_no: Any
    duration_min: Any = None
    related_mc_id: Any = None
    related_mc_instance_no: Any = None
    sub_mc_id: Any = None
    sub_mc_instance_no: Any = None
    stop_id: Any = None
    sub_stop_id: Any = None
    cause_id: Any = None
    meo: Any = None
    note: Any = None
    created_by: Any = None
    classification_edited: Any = False
    preset_shift_id: Any = None
    event_shift_id: Any = None
    logger_event_id: Any = None


def _validation_error(code, message):
    raise LoggerValidationError(code, message)


def _as_save_input(value):
    if isinstance(value, LoggerSaveInput):
        return value
    if not isinstance(value, dict):
        _validation_error("INVALID_INPUT", "LOGGER SAVE input must be a mapping.")
    names = {
        "production_date": "ProductionDate",
        "stop": "Stop",
        "start": "Start",
        "duration_min": "DurationMin",
        "mc_id": "McId",
        "mc_instance_no": "McInstanceNo",
        "related_mc_id": "RelatedMcId",
        "related_mc_instance_no": "RelatedMcInstanceNo",
        "sub_mc_id": "SubMcId",
        "sub_mc_instance_no": "SubMcInstanceNo",
        "stop_id": "StopId",
        "sub_stop_id": "SubStopId",
        "cause_id": "CauseId",
        "meo": "MEO",
        "note": "Note",
        "created_by": "CreatedBy",
        "classification_edited": "classification_edited",
        "preset_shift_id": "PresetShiftID",
        "event_shift_id": "EventShiftID",
        "logger_event_id": "LoggerEventID",
    }
    values = {}
    for field, external in names.items():
        values[field] = value.get(external, value.get(field))
    return LoggerSaveInput(**values)


def _positive_int(value, code, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _validation_error(code, f"{label} must be a positive integer.")
    return value


def _optional_int(value, code, label):
    if value is None:
        return None
    return _positive_int(value, code, label)


def _parse_production_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        _validation_error("INVALID_PRODUCTION_DATE", "ProductionDate is invalid.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        _validation_error("INVALID_PRODUCTION_DATE", "ProductionDate is invalid.")


def _parse_hhmm(value, code, label):
    if not isinstance(value, str):
        _validation_error(code, f"{label} must use HH:mm format.")
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError:
        _validation_error(code, f"{label} must use HH:mm format.")
    if value != parsed.strftime("%H:%M"):
        _validation_error(code, f"{label} must use HH:mm format.")
    return parsed.time()


def _parse_duration_min(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        _validation_error("INVALID_DURATION", "Min must be greater than 0 and use at most one decimal place.")
    text = str(value).strip()
    if not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d)?", text):
        _validation_error("INVALID_DURATION", "Min must be greater than 0 and use at most one decimal place.")
    try:
        duration = Decimal(text)
    except InvalidOperation:
        _validation_error("INVALID_DURATION", "Min must be greater than 0 and use at most one decimal place.")
    if duration <= 0:
        _validation_error("INVALID_DURATION", "Min must be greater than 0 and use at most one decimal place.")
    return duration


def _master_by_id(rows, key, value):
    return next((row for row in rows if row[key] == value), None)


def _validate_pair(first, second, code, label):
    if (first is None) != (second is None):
        _validation_error(code, f"{label} values must be supplied as a pair.")


def _validate_logger_masters(data, masters, day_start_time=None):
    production_date = _parse_production_date(data.production_date)
    has_stop = data.stop not in (None, "")
    has_start = data.start not in (None, "")
    if has_stop != has_start:
        _validation_error("INCOMPLETE_TIMESTAMPS", "Enter both Stop and Start, or leave both blank and enter Min.")
    manual_duration = _parse_duration_min(data.duration_min)
    timestamp_mode = has_stop and has_start
    if timestamp_mode:
        stop_time = _parse_hhmm(data.stop, "INVALID_STOP_TIME", "Stop")
        start_time = _parse_hhmm(data.start, "INVALID_START_TIME", "Start")
        if start_time == stop_time:
            _validation_error("EQUAL_STOP_START", "Stop and Start times must differ.")
    elif manual_duration is None:
        _validation_error("INVALID_DURATION", "Min is required when Stop and Start are blank.")

    def timestamp_datetimes():
        if day_start_time is None:
            stop_datetime = datetime.combine(production_date, stop_time)
            start_date = production_date if start_time > stop_time else production_date + timedelta(days=1)
            start_datetime = datetime.combine(start_date, start_time)
        else:
            stop_datetime = production_clock_datetime(production_date, data.stop, day_start_time)
            start_datetime = production_clock_datetime(production_date, data.start, day_start_time)
            if start_datetime <= stop_datetime:
                start_datetime += timedelta(days=1)
        return stop_datetime, start_datetime

    if not isinstance(data.classification_edited, bool):
        _validation_error("INVALID_CLASSIFICATION_PROVENANCE", "classification_edited must be boolean.")
    if data.meo not in (None, "M", "E", "O"):
        _validation_error("INVALID_MEO", "MEO must be M, E, O, or null.")
    if data.note is not None and (not isinstance(data.note, str) or len(data.note) > 1000):
        _validation_error("INVALID_NOTE", "Note must be at most 1000 characters.")
    if data.created_by is not None and (not isinstance(data.created_by, str) or len(data.created_by) > 200):
        _validation_error("INVALID_CREATED_BY", "CreatedBy must be at most 200 characters.")

    mc_id = _positive_int(data.mc_id, "INVALID_MACHINE", "McId")
    mc_instance_no = _positive_int(data.mc_instance_no, "INVALID_MACHINE_INSTANCE", "McInstanceNo")
    machine = _master_by_id(masters.main_machines, "McId", mc_id)
    if machine is None:
        _validation_error("INVALID_MACHINE", "McId is not an active Main Machine.")
    if mc_instance_no > int(machine["No"]):
        _validation_error("INVALID_MACHINE_INSTANCE", "McInstanceNo is outside the active Main Machine range.")

    stop_id = _positive_int(data.stop_id, "INVALID_STOP", "StopId")
    stop_type = _master_by_id(masters.stop_types, "StopId", stop_id)
    if stop_type is None:
        _validation_error("INVALID_STOP", "StopId is not an active Stop Type.")
    machine_level = stop_type["StopType"] in {"SETUP", "CHGOVER", "CLEAN", "IDLE"}

    _validate_pair(data.related_mc_id, data.related_mc_instance_no,
                   "INVALID_RELATED_MACHINE", "Related Main Machine")
    related_mc_id = _optional_int(data.related_mc_id, "INVALID_RELATED_MACHINE", "RelatedMcId")
    related_instance_no = _optional_int(data.related_mc_instance_no, "INVALID_RELATED_INSTANCE", "RelatedMcInstanceNo")
    related_machine = None
    if related_mc_id is not None:
        related_machine = _master_by_id(masters.main_machines, "McId", related_mc_id)
        if related_machine is None:
            _validation_error("INVALID_RELATED_MACHINE", "RelatedMcId is not an active Main Machine.")
        if related_instance_no > int(related_machine["No"]):
            _validation_error("INVALID_RELATED_INSTANCE", "RelatedMcInstanceNo is outside the active Main Machine range.")
        if not any(row["McId"] == related_mc_id and bool(row["IsRelated"])
                   for row in masters.sub_machines):
            _validation_error("INVALID_RELATED_MACHINE", "Related Main Machine has no active proxy.")

    _validate_pair(data.sub_mc_id, data.sub_mc_instance_no,
                   "INVALID_SUBMACHINE", "physical SubMachine")
    sub_mc_id = _optional_int(data.sub_mc_id, "INVALID_SUBMACHINE", "SubMcId")
    sub_instance_no = _optional_int(data.sub_mc_instance_no, "INVALID_SUBMACHINE_INSTANCE", "SubMcInstanceNo")
    sub_machine = None
    if sub_mc_id is not None:
        sub_machine = _master_by_id(masters.sub_machines, "SubMcId", sub_mc_id)
        if sub_machine is None:
            _validation_error("INVALID_SUBMACHINE", "SubMcId is not an active SubMachine.")
        if bool(sub_machine["IsRelated"]):
            _validation_error("PROXY_SUBMACHINE", "An IsRelated proxy cannot be stored as SubMcId.")
        if sub_instance_no > int(sub_machine["No"]):
            _validation_error("INVALID_SUBMACHINE_INSTANCE", "SubMcInstanceNo is outside the physical SubMachine range.")

    if related_mc_id is None and sub_mc_id is None and not machine_level:
        _validation_error("INVALID_HIERARCHY", "A final physical or Related M/C selection is required.")
    if related_mc_id is None and sub_mc_id is None:
        kind = None
    elif related_mc_id is None and sub_mc_id is not None:
        kind = DIRECT_SUB
    elif related_mc_id is not None and sub_mc_id is None:
        kind = RELATED_MAIN
    else:
        kind = RELATED_SUB
        if sub_machine["McId"] != related_mc_id:
            _validation_error("INVALID_HIERARCHY", "The physical SubMachine is not owned by the Related Main Machine.")

    sub_stop_id = _optional_int(data.sub_stop_id, "INVALID_SUBSTOP", "SubStopId")
    sub_stop_type = None
    if sub_stop_id is not None:
        sub_stop_type = _master_by_id(masters.sub_stop_types, "SubStopId", sub_stop_id)
        if sub_stop_type is None or sub_stop_type["StopId"] != stop_id:
            _validation_error("INVALID_STOP_SUBSTOP", "SubStopId does not belong to StopId.")

    cause = None
    if data.cause_id is not None:
        cause_id = _positive_int(data.cause_id, "INVALID_CAUSE", "CauseId")
        cause = _master_by_id(masters.causes, "CauseId", cause_id)
        if cause is None:
            _validation_error("INVALID_CAUSE", "CauseId is not an active Cause.")
        if related_mc_id is not None and sub_mc_id is None:
            if cause.get("McId") != related_mc_id:
                _validation_error("INVALID_CAUSE", "Cause does not belong to the selected Related Main Machine.")
            cause_sub_mc_id = cause.get("SubMcId")
            if cause_sub_mc_id is not None:
                proxy = _master_by_id(masters.sub_machines, "SubMcId", cause_sub_mc_id)
                if (proxy is None or not bool(proxy["IsRelated"])
                        or proxy["McId"] != related_mc_id):
                    _validation_error("INVALID_CAUSE", "Cause is not mapped to a valid Related Main Machine proxy.")
    else:
        cause_id = None

    if data.classification_edited:
        classification_source = "MANUAL"
    elif cause is None:
        classification_source = "MANUAL"
    elif (cause_catalog_stop_id(stop_id) != cause.get("StopId")
          or (stop_id != BD_STOP_ID and sub_stop_id != cause.get("SubStopId"))):
        _validation_error("INCONSISTENT_CLASSIFICATION", "Final classification does not match the selected Cause.")
    else:
        classification_source = "CAUSE_SHORTCUT"

    if timestamp_mode and stop_id == 6 and sub_stop_id == 20:
        stop_datetime, start_datetime = timestamp_datetimes()
        duration_min = int((start_datetime - stop_datetime).total_seconds() // 60)
        if duration_min >= 10:
            stop_id = 7
            sub_stop_id = 21
            stop_type = _master_by_id(masters.stop_types, "StopId", stop_id)
            sub_stop_type = _master_by_id(masters.sub_stop_types, "SubStopId", sub_stop_id)
            if stop_type is None or sub_stop_type is None or sub_stop_type["StopId"] != stop_id:
                _validation_error("INVALID_STOP_SUBSTOP", "Configured BD classification is unavailable.")
            classification_source = "DURATION_RULE"
    elif timestamp_mode:
        stop_datetime, start_datetime = timestamp_datetimes()
        duration_min = int((start_datetime - stop_datetime).total_seconds() // 60)
    else:
        stop_datetime = None
        start_datetime = None
        duration_min = manual_duration

    if timestamp_mode and (duration_min <= 0 or start_datetime <= stop_datetime):
        _validation_error("INVALID_DURATION", "LOGGER duration must be positive.")

    if kind == DIRECT_SUB:
        related_machine = None
    return {
        "production_date": production_date,
        "stop_datetime": stop_datetime,
        "start_datetime": start_datetime,
        "duration_min": duration_min,
        "mc_id": mc_id,
        "mc_instance_no": mc_instance_no,
        "related_mc_id": related_mc_id,
        "related_mc_instance_no": related_instance_no,
        "sub_mc_id": sub_mc_id,
        "sub_mc_instance_no": sub_instance_no,
        "stop_id": stop_id,
        "sub_stop_id": sub_stop_id,
        "cause_id": cause_id,
        "meo": data.meo,
        "note": data.note,
        "created_by": data.created_by,
        "kind": kind,
        "machine": machine,
        "related_machine": related_machine,
        "sub_machine": sub_machine,
        "stop_type": stop_type,
        "sub_stop_type": sub_stop_type,
        "cause": cause,
        "classification_source": classification_source,
    }


def _logger_snapshot(row, instance_no):
    if row is None:
        return None
    name = row.get("Machine", row.get("SubMachine"))
    return f"{name}{instance_no}"


def _build_logger_snapshots(values):
    return {
        "MachineNameSnapshot": _logger_snapshot(values["machine"], values["mc_instance_no"]),
        "RelatedMachineSnapshot": _logger_snapshot(values["related_machine"], values["related_mc_instance_no"]),
        "SubMachineSnapshot": _logger_snapshot(values["sub_machine"], values["sub_mc_instance_no"]),
        "StopTypeSnapshot": values["stop_type"]["StopType"],
        "SubStopTypeSnapshot": values["sub_stop_type"]["SubStopType"] if values["sub_stop_type"] else None,
        "CauseSnapshot": values["cause"]["Cause"] if values["cause"] else None,
    }


def _format_logger_time(value):
    return value.strftime("%H:%M")


def _overlap_message(existing, values, snapshots):
    existing_machine = existing[1] or snapshots["MachineNameSnapshot"] or "-"
    existing_type = existing[2] or "-"
    existing_cause = existing[3] or "-"
    new_machine = snapshots["MachineNameSnapshot"] or "-"
    new_type = snapshots["StopTypeSnapshot"] or "-"
    return ("Time overlaps an existing LOGGER event.\n\n"
            f"Existing: {existing_machine} | {existing_type} | "
            f"{_format_logger_time(existing[4])} - {_format_logger_time(existing[5])} | "
            f"{existing_cause}\n\n"
            f"New: {new_machine} | {new_type} | "
            f"{_format_logger_time(values['stop_datetime'])} - "
            f"{_format_logger_time(values['start_datetime'])}\n\n"
            "Please correct the Stop / Start time before saving.")


def _reject_overlapping_logger_event(cursor, values, snapshots):
    if values["stop_datetime"] is None or values["start_datetime"] is None:
        return
    cursor.execute("""
        SELECT TOP (1) LoggerEventID, MachineNameSnapshot, StopTypeSnapshot,
               CauseSnapshot, StopDateTime, StartDateTime, DurationMin
        FROM dbo.LoggerEvent WITH (UPDLOCK,HOLDLOCK)
        WHERE McId=? AND McInstanceNo=?
          AND StopDateTime < ? AND StartDateTime > ?
        ORDER BY StopDateTime, LoggerEventID
    """, values["mc_id"], values["mc_instance_no"], values["start_datetime"],
        values["stop_datetime"])
    existing = cursor.fetchone()
    if existing:
        _validation_error("OVERLAPPING_EVENT", _overlap_message(existing, values, snapshots))


def _resolve_logger_shift(cursor, values, data, day_start_time):
    if values["stop_datetime"] is not None:
        rules = read_shift_rules(cursor, values["production_date"])
        shift = resolve_shift(
            values["production_date"],
            values["stop_datetime"].time(),
            None,
            rules,
        )
        if shift is None:
            _validation_error(
                "SHIFT_RULE_NOT_FOUND",
                "No historical Production Shift rule applies to the LOGGER Stop time.",
            )
        return int(shift)

    try:
        preset_shift = int(data.preset_shift_id)
    except (TypeError, ValueError):
        _validation_error("INVALID_PRESET_SHIFT", "Select a valid Preset Shift.")
    rules = read_shift_rules(cursor, values["production_date"])
    if not any(int(rule["ShiftID"]) == preset_shift for rule in rules):
        _validation_error("INVALID_PRESET_SHIFT", "Select a valid Preset Shift.")
    return preset_shift


def _resolve_logger_event_shift(cursor, production_date, event_shift_id, existing_shift):
    if event_shift_id in (None, ""):
        event_shift_id = existing_shift
        if event_shift_id is None:
            return None

    raw_shift_id = str(event_shift_id).strip()
    if not re.fullmatch(r"[0-9]+", raw_shift_id):
        _validation_error("INVALID_EVENT_SHIFT", "Select a valid Event Shift.")
    selected_shift = int(raw_shift_id)
    rules = read_shift_rules(cursor, production_date)
    if not any(int(rule["ShiftID"]) == selected_shift for rule in rules):
        _validation_error("INVALID_EVENT_SHIFT", "Select a valid Event Shift.")
    return selected_shift


def _read_logger_day_start_time(cursor, production_date):
    try:
        return read_day_start_time(cursor, production_date)
    except ValueError as exc:
        _validation_error("PRODUCTION_DAY_RULE_NOT_FOUND", str(exc))


def _read_existing_logger_event(cursor, event_id):
    cursor.execute(
        "SELECT StopDateTime, ShiftID FROM dbo.LoggerEvent WITH (UPDLOCK,HOLDLOCK) "
        "WHERE LoggerEventID=?",
        event_id,
    )
    row = cursor.fetchone()
    return row if row is not None and len(row) >= 2 else (None, None)


def save_logger_event(conn, data, masters=None):
    """Validate and insert one final operator-confirmed LOGGER event."""
    try:
        cursor = conn.cursor()
        if masters is None:
            masters = read_logger_masters(cursor)
        data = _as_save_input(data)
        day_start_time = _read_logger_day_start_time(cursor, data.production_date)
        values = _validate_logger_masters(data, masters, day_start_time)
        shift_id = _resolve_logger_shift(cursor, values, data, day_start_time)
        snapshots = _build_logger_snapshots(values)
        _reject_overlapping_logger_event(cursor, values, snapshots)
        cursor.execute("""
            INSERT INTO dbo.LoggerEvent
                (ProductionDate, StopDateTime, StartDateTime, DurationMin,
                 McId, McInstanceNo, RelatedMcId, RelatedMcInstanceNo,
                 SubMcId, SubMcInstanceNo, StopId, SubStopId, CauseId, MEO,
                 MachineNameSnapshot, RelatedMachineSnapshot,
                 SubMachineSnapshot, StopTypeSnapshot, SubStopTypeSnapshot,
                 CauseSnapshot, Note, SourceType, ClassificationSource,
                 ShiftID, CreatedBy)
            OUTPUT INSERTED.LoggerEventID
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, values["production_date"], values["stop_datetime"], values["start_datetime"],
            values["duration_min"], values["mc_id"], values["mc_instance_no"],
            values["related_mc_id"], values["related_mc_instance_no"],
            values["sub_mc_id"], values["sub_mc_instance_no"], values["stop_id"],
            values["sub_stop_id"],
            values["cause_id"], values["meo"], snapshots["MachineNameSnapshot"],
            snapshots["RelatedMachineSnapshot"], snapshots["SubMachineSnapshot"],
            snapshots["StopTypeSnapshot"], snapshots["SubStopTypeSnapshot"],
            snapshots["CauseSnapshot"], values["note"], "MANUAL",
            values["classification_source"], shift_id, values["created_by"])
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("LoggerEventID was not returned by the INSERT.")
        event_id = row[0]
        conn.commit()
        return event_id
    except LoggerValidationError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise LoggerValidationError("DATABASE_INSERT", "LOGGER transaction INSERT failed.") from exc


def update_logger_event(conn, event_id, data, masters=None):
    """Validate and update one final operator-confirmed LOGGER event."""
    try:
        cursor = conn.cursor()
        if masters is None:
            masters = read_logger_masters(cursor)
        data = _as_save_input(data)
        _, existing_shift = _read_existing_logger_event(cursor, event_id)
        day_start_time = _read_logger_day_start_time(cursor, data.production_date)
        values = _validate_logger_masters(data, masters, day_start_time)
        if values["stop_datetime"] is None:
            shift_id = _resolve_logger_event_shift(
                cursor, values["production_date"], data.event_shift_id, existing_shift)
        else:
            if data.event_shift_id not in (None, ""):
                _resolve_logger_event_shift(
                    cursor, values["production_date"], data.event_shift_id, None)
            shift_id = _resolve_logger_shift(cursor, values, data, day_start_time)
        snapshots = _build_logger_snapshots(values)
        cursor.execute("""
            UPDATE dbo.LoggerEvent
            SET ProductionDate=?, StopDateTime=?, StartDateTime=?, DurationMin=?,
                McId=?, McInstanceNo=?, RelatedMcId=?, RelatedMcInstanceNo=?, ShiftID=?,
                SubMcId=?, SubMcInstanceNo=?, StopId=?, SubStopId=?, CauseId=?, MEO=?,
                MachineNameSnapshot=?, RelatedMachineSnapshot=?, SubMachineSnapshot=?,
                StopTypeSnapshot=?, SubStopTypeSnapshot=?, CauseSnapshot=?, Note=?,
                ClassificationSource=?
            WHERE LoggerEventID=?
        """, values["production_date"], values["stop_datetime"], values["start_datetime"],
            values["duration_min"], values["mc_id"], values["mc_instance_no"],
            values["related_mc_id"], values["related_mc_instance_no"], shift_id, values["sub_mc_id"],
            values["sub_mc_instance_no"], values["stop_id"], values["sub_stop_id"],
            values["cause_id"], values["meo"], snapshots["MachineNameSnapshot"],
            snapshots["RelatedMachineSnapshot"], snapshots["SubMachineSnapshot"],
            snapshots["StopTypeSnapshot"], snapshots["SubStopTypeSnapshot"],
            snapshots["CauseSnapshot"], values["note"], values["classification_source"],
            event_id)
        if cursor.rowcount != 1:
            _validation_error("LOGGER_EVENT_NOT_FOUND", "LOGGER entry no longer exists.")
        conn.commit()
        return event_id
    except LoggerValidationError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise LoggerValidationError("DATABASE_UPDATE", "LOGGER transaction UPDATE failed.") from exc


def _rows(cursor, keys):
    return [dict(zip(keys, row)) for row in cursor.fetchall()]


def read_main_machines(cursor):
    cursor.execute("""
        SELECT McId, Machine, No, Relate
        FROM dbo.Fitting_MainMachine
        WHERE IsActive=1
        ORDER BY McId
    """)
    return _rows(cursor, ("McId", "Machine", "No", "Relate"))


def read_sub_machines(cursor):
    cursor.execute("""
        SELECT SubMcId, McId, Equipment AS SubMachine, No, IsActive, IsRelated
        FROM dbo.Fitting_SubMachine
        WHERE IsActive=1
        ORDER BY SubMcId
    """)
    return _rows(cursor, ("SubMcId", "McId", "SubMachine", "No", "IsActive", "IsRelated"))


def read_stop_types(cursor):
    cursor.execute("""
        SELECT StopId, StopType
        FROM dbo.Fitting_StopType
        WHERE IsActive=1
        ORDER BY StopId
    """)
    return _rows(cursor, ("StopId", "StopType"))


def read_sub_stop_types(cursor):
    cursor.execute("""
        SELECT SubStopId, StopId, SubStopType
        FROM dbo.Fitting_SubStopType
        WHERE IsActive=1
        ORDER BY SubStopId
    """)
    return _rows(cursor, ("SubStopId", "StopId", "SubStopType"))


def read_causes(cursor):
    cursor.execute("""
        SELECT CauseId, Cause, McId, SubMcId, StopId, SubStopId, MEO
        FROM dbo.Fitting_Cause
        WHERE IsActive=1
        ORDER BY CauseId
    """)
    return _rows(cursor, ("CauseId", "Cause", "McId", "SubMcId", "StopId", "SubStopId", "MEO"))


def read_logger_masters(cursor):
    return LoggerMasters(
        main_machines=read_main_machines(cursor),
        sub_machines=read_sub_machines(cursor),
        stop_types=read_stop_types(cursor),
        sub_stop_types=read_sub_stop_types(cursor),
        causes=read_causes(cursor),
    )


def read_logger_events(cursor, production_date):
    cursor.execute("""
        SELECT LoggerEventID, ProductionDate, StopDateTime, StartDateTime,
               DurationMin, MachineNameSnapshot, RelatedMachineSnapshot,
               SubMachineSnapshot, CauseSnapshot, StopTypeSnapshot,
               SubStopTypeSnapshot, MEO, Note, McId, McInstanceNo,
               RelatedMcId, RelatedMcInstanceNo, ShiftID, SubMcId, SubMcInstanceNo,
               StopId, SubStopId, CauseId
        FROM dbo.LoggerEvent
        WHERE ProductionDate=?
        ORDER BY StopDateTime DESC, LoggerEventID DESC
    """, production_date)
    return _rows(cursor, (
        "LoggerEventID", "ProductionDate", "StopDateTime", "StartDateTime",
        "DurationMin", "MachineNameSnapshot", "RelatedMachineSnapshot",
        "SubMachineSnapshot", "CauseSnapshot", "StopTypeSnapshot",
        "SubStopTypeSnapshot", "MEO", "Note",
        "McId", "McInstanceNo", "RelatedMcId", "RelatedMcInstanceNo",
        "ShiftID", "SubMcId", "SubMcInstanceNo", "StopId", "SubStopId", "CauseId",
    ))


def expand_main_machine(machine):
    return [
        {"mc_id": machine["McId"], "mc_instance_no": instance_no,
         "display_label": f'{machine["Machine"]}{instance_no}'}
        for instance_no in range(1, int(machine["No"]) + 1)
    ]


def main_machine_categories(main_machines):
    """Return distinct broad machine categories from active master rows."""
    categories = []
    seen = set()
    for machine in main_machines:
        name = machine["Machine"]
        if name in seen:
            continue
        seen.add(name)
        categories.append({"mc_id": machine["McId"], "machine": name})
    return sorted(categories, key=lambda item: item["machine"] != "F")


def sub_related_options_for_instance(main_machines, sub_machines, mc_id, instance_no):
    """Expand physical equipment and configured related machines for one instance."""
    machine = _master_by_id(main_machines, "McId", mc_id)
    if machine is None or not 1 <= int(instance_no) <= int(machine["No"]):
        return []
    options = []
    for sub_machine in sub_machines:
        if bool(sub_machine["IsRelated"]) or sub_machine["McId"] != mc_id:
            continue
        for sub_instance_no in range(1, int(sub_machine["No"]) + 1):
            label = f'{sub_machine["SubMachine"]}{sub_instance_no}'
            options.append({
                "kind": DIRECT_SUB,
                "owner_mc_id": mc_id,
                "owner_mc_instance_no": int(instance_no),
                "related_mc_id": None,
                "related_mc_instance_no": None,
                "sub_mc_id": sub_machine["SubMcId"],
                "sub_mc_instance_no": sub_instance_no,
                "display_label": label,
                "related_machine_snapshot": None,
                "sub_machine_snapshot": label,
            })
    for option in expand_sub_related_options(main_machines, sub_machines):
        if option["kind"] not in (RELATED_MAIN, RELATED_SUB):
            continue
        related_option = option.copy()
        related_option["owner_mc_id"] = mc_id
        related_option["owner_mc_instance_no"] = int(instance_no)
        options.append(related_option)
    return options


def expand_sub_related_options(main_machines, sub_machines):
    main_by_id = {machine["McId"]: machine for machine in main_machines}
    options = []
    related_machines = []
    for sub_machine in sub_machines:
        count = int(sub_machine["No"])
        if bool(sub_machine["IsRelated"]):
            related_machine = main_by_id.get(sub_machine["McId"])
            if related_machine is None:
                continue
            related_machines.append(related_machine)
            for instance_no in range(1, int(related_machine["No"]) + 1):
                label = f'{related_machine["Machine"]}{instance_no}'
                options.append({
                    "kind": RELATED_MAIN,
                    "related_mc_id": related_machine["McId"],
                    "related_mc_instance_no": instance_no,
                    "sub_mc_id": None,
                    "sub_mc_instance_no": None,
                    "display_label": label,
                    "related_machine_snapshot": label,
                    "sub_machine_snapshot": None,
                })
            continue
        for instance_no in range(1, count + 1):
            label = f'{sub_machine["SubMachine"]}{instance_no}'
            options.append({
                "kind": DIRECT_SUB,
                "related_mc_id": None,
                "related_mc_instance_no": None,
                "sub_mc_id": sub_machine["SubMcId"],
                "sub_mc_instance_no": instance_no,
                "display_label": label,
                "related_machine_snapshot": None,
                "sub_machine_snapshot": label,
            })
    physical_sub_machines = [sub for sub in sub_machines if not bool(sub["IsRelated"])]
    for related_machine in related_machines:
        for sub_machine in physical_sub_machines:
            if sub_machine["McId"] != related_machine["McId"]:
                continue
            for related_instance_no in range(1, int(related_machine["No"]) + 1):
                for sub_instance_no in range(1, int(sub_machine["No"]) + 1):
                    related_label = f'{related_machine["Machine"]}{related_instance_no}'
                    sub_label = f'{sub_machine["SubMachine"]}{sub_instance_no}'
                    options.append({
                        "kind": RELATED_SUB,
                        "related_mc_id": related_machine["McId"],
                        "related_mc_instance_no": related_instance_no,
                        "sub_mc_id": sub_machine["SubMcId"],
                        "sub_mc_instance_no": sub_instance_no,
                        "display_label": f"{related_label} / {sub_label}",
                        "related_machine_snapshot": related_label,
                        "sub_machine_snapshot": sub_label,
                    })
    return options


def normalize_sub_related_selection(selection, main_machines, sub_machines):
    if not selection:
        return {
            "kind": None,
            "related_mc_id": None,
            "related_mc_instance_no": None,
            "sub_mc_id": None,
            "sub_mc_instance_no": None,
            "display_label": "-",
            "related_machine_snapshot": None,
            "sub_machine_snapshot": None,
        }
    options = expand_sub_related_options(main_machines, sub_machines)
    for option in options:
        if all(selection.get(key) == option[key] for key in (
            "kind", "related_mc_id", "related_mc_instance_no",
            "sub_mc_id", "sub_mc_instance_no")):
            return option.copy()
    raise LoggerResolutionError("The selected Sub / Related M/C is unavailable.")


def suggest_cause(cause, selected_machine_id=None, sub_related_options=None):
    suggestion = {
        "cause_id": cause["CauseId"],
        "stop_id": cause.get("StopId"),
        "sub_stop_id": cause.get("SubStopId"),
        "meo": cause.get("MEO"),
        "machine_id": selected_machine_id if selected_machine_id is not None else cause.get("McId"),
        "sub_related_option": None,
    }
    if sub_related_options is not None and cause.get("SubMcId") is not None:
        suggestion["sub_related_option"] = next(
            (option for option in sub_related_options
             if option.get("sub_mc_id") == cause["SubMcId"]
             or option.get("related_mc_id") == cause["McId"]),
            None,
        )
    return suggestion
