"""Read-only LOGGER time summary queries."""

import re

from app.production_data import read_shift_rules, resolve_shift


SUMMARY_TYPES = {
    "SETUP": "SetupMin",
    "CHGOVER": "ChgOverMin",
    "IDLE": "IdleMin",
    "CLEAN": "CleanMin",
    "SMDT": "SmdtMin",
    "BD": "BreakdownMin",
}

GUIDE_TIME_FIELDS = {
    "SETUP": "SetupMinutes",
    "CHGOVER": "ChgOverMinutes",
    "IDLE": "IdleMinutes",
    "CLEAN": "CleaningMinutes",
    "SMDT": "SmdtMinutes",
    "BD": "BreakdownMinutes",
}

SHIFT_SUMMARY_FIELDS = {
    1: {
        "SETUP": "Shift1SetupMin",
        "CHGOVER": "Shift1ChgOverMin",
        "IDLE": "Shift1IdleMin",
        "CLEAN": "Shift1CleanMin",
        "SMDT": "Shift1SmdtMin",
        "BD": "Shift1BreakdownMin",
    },
    2: {
        "SETUP": "Shift2SetupMin",
        "CHGOVER": "Shift2ChgOverMin",
        "IDLE": "Shift2IdleMin",
        "CLEAN": "Shift2CleanMin",
        "SMDT": "Shift2SmdtMin",
        "BD": "Shift2BreakdownMin",
    },
}


def _rows(cursor, keys):
    return [dict(zip(keys, row)) for row in cursor.fetchall()]


def read_logger_press_guide(cursor, production_date, equipment_code):
    """Read the daily LOGGER guide for one explicitly mapped F press."""
    match = re.fullmatch(r"F([1-9][0-9]*)", str(equipment_code or ""))
    empty = dict(SetupMinutes=None, ChgOverMinutes=None, IdleMinutes=None,
                 CleaningMinutes=None, SmdtMinutes=None, BreakdownMinutes=None,
                 HasSetup=False, HasChgOver=False, HasCleaning=False,
                 HasIdle=False, HasBreakdown=False, HasSmdt=False,
                 shifts={str(shift): {
                     name: {"minutes": 0, "present": False}
                     for name in SUMMARY_TYPES
                 } for shift in (1, 2)})
    if not match:
        return empty

    instance_no = int(match.group(1))
    cursor.execute("""
        SELECT McId, No
        FROM dbo.Fitting_MainMachine
        WHERE Machine=? AND IsActive=1
    """, "F")
    machines = cursor.fetchall()
    if len(machines) != 1 or instance_no > int(machines[0][1] or 0):
        return empty

    stop_ids = _summary_stop_ids(cursor)
    category_ids = tuple(stop_ids[name] for name in SUMMARY_TYPES)
    shift_rules = read_shift_rules(cursor, production_date)
    cursor.execute("""
        SELECT event.StopId, event.DurationMin, event.StopDateTime, event.ShiftID
        FROM dbo.LoggerEvent AS event
        WHERE event.ProductionDate=? AND event.McId=? AND event.McInstanceNo=?
          AND event.StopId IN (?,?,?,?,?,?)
    """, production_date, machines[0][0], instance_no, *category_ids)
    events = cursor.fetchall()
    shifts = {
        1: {name: 0 for name in SUMMARY_TYPES},
        2: {name: 0 for name in SUMMARY_TYPES},
    }
    presence = {
        1: {name: False for name in SUMMARY_TYPES},
        2: {name: False for name in SUMMARY_TYPES},
    }
    stop_type_by_id = {stop_id: name for name, stop_id in stop_ids.items()}
    valid_shift_ids = {int(rule["ShiftID"]) for rule in shift_rules}
    for stop_id, duration, stop_datetime, persisted_shift_id in events:
        shift_id = persisted_shift_id
        if shift_id is not None:
            try:
                shift_id = int(shift_id)
            except (TypeError, ValueError):
                shift_id = None
        if shift_id not in valid_shift_ids and stop_datetime is not None:
            resolved_shift = resolve_shift(
                production_date, stop_datetime.time(), None, shift_rules)
            shift_id = int(resolved_shift) if resolved_shift is not None else None
        stop_type = stop_type_by_id[stop_id]
        if shift_id in shifts:
            shifts[shift_id][stop_type] += int(duration or 0)
            presence[shift_id][stop_type] = True

    if not any(any(values.values()) for values in presence.values()):
        return empty
    result = dict(
        SetupMinutes=sum(shifts[shift]["SETUP"] for shift in shifts),
        ChgOverMinutes=sum(shifts[shift]["CHGOVER"] for shift in shifts),
        IdleMinutes=sum(shifts[shift]["IDLE"] for shift in shifts),
        CleaningMinutes=sum(shifts[shift]["CLEAN"] for shift in shifts),
        BreakdownMinutes=sum(shifts[shift]["BD"] for shift in shifts),
        SmdtMinutes=sum(shifts[shift]["SMDT"] for shift in shifts),
        HasSetup=any(presence[shift]["SETUP"] for shift in presence),
        HasChgOver=any(presence[shift]["CHGOVER"] for shift in presence),
        HasIdle=any(presence[shift]["IDLE"] for shift in presence),
        HasCleaning=any(presence[shift]["CLEAN"] for shift in presence),
        HasBreakdown=any(presence[shift]["BD"] for shift in presence),
        HasSmdt=any(presence[shift]["SMDT"] for shift in presence),
        shifts={str(shift): {
            "SETUP": {"minutes": shifts[shift]["SETUP"], "present": presence[shift]["SETUP"]},
            "CHGOVER": {"minutes": shifts[shift]["CHGOVER"], "present": presence[shift]["CHGOVER"]},
            "IDLE": {"minutes": shifts[shift]["IDLE"], "present": presence[shift]["IDLE"]},
            "CLEAN": {"minutes": shifts[shift]["CLEAN"], "present": presence[shift]["CLEAN"]},
            "SMDT": {"minutes": shifts[shift]["SMDT"], "present": presence[shift]["SMDT"]},
            "BD": {"minutes": shifts[shift]["BD"], "present": presence[shift]["BD"]},
        } for shift in shifts},
    )
    return result


def _summary_stop_ids(cursor):
    cursor.execute("""
        SELECT StopId, StopType
        FROM dbo.Fitting_StopType
        WHERE IsActive=1 AND StopType IN (?,?,?,?,?,?)
    """, *SUMMARY_TYPES)
    rows = _rows(cursor, ("StopId", "StopType"))
    by_name = {row["StopType"]: row["StopId"] for row in rows}
    missing = [name for name in SUMMARY_TYPES if name not in by_name]
    if missing:
        raise ValueError(f"Missing active LOGGER Stop Type: {', '.join(missing)}")
    if len(by_name) != len(rows):
        raise ValueError("LOGGER summary Stop Types must have unique names.")
    return {name: by_name[name] for name in SUMMARY_TYPES}


def read_logger_time_summary(cursor, production_date):
    stop_ids = _summary_stop_ids(cursor)
    ordered_names = tuple(SUMMARY_TYPES)
    category_ids = tuple(stop_ids[name] for name in ordered_names)
    cursor.execute("""
        SELECT event.McId, event.McInstanceNo, machine.Machine,
               SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END) AS SetupMin,
               SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END) AS ChgOverMin,
               SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END) AS IdleMin,
               SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END) AS CleanMin,
               SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END) AS SmdtMin,
               SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END) AS BreakdownMin
        FROM dbo.LoggerEvent AS event
        JOIN dbo.Fitting_MainMachine AS machine ON machine.McId=event.McId
        WHERE event.ProductionDate=? AND event.StopId IN (?,?,?,?,?,?)
        GROUP BY event.McId, event.McInstanceNo, machine.Machine
        ORDER BY machine.Machine, event.McInstanceNo
    """, *category_ids, production_date, *category_ids)
    summary = _rows(cursor, ("McId", "McInstanceNo", "Machine", "SetupMin",
                             "ChgOverMin", "IdleMin", "CleanMin", "SmdtMin",
                             "BreakdownMin"))
    for row in summary:
        for field in ("SetupMin", "ChgOverMin", "IdleMin", "CleanMin", "SmdtMin", "BreakdownMin"):
            row[field] = int(row[field] or 0)
        row["TotalLoggedMin"] = sum(row[field] for field in (
            "SetupMin", "ChgOverMin", "IdleMin", "CleanMin", "SmdtMin", "BreakdownMin"))
        for fields in SHIFT_SUMMARY_FIELDS.values():
            for field in fields.values():
                row[field] = 0
        row["MachineLabel"] = f'{row["Machine"]}{row["McInstanceNo"]}'

    shift_rules = read_shift_rules(cursor, production_date)
    cursor.execute("""
        SELECT event.LoggerEventID, event.McId, event.McInstanceNo,
               event.StopDateTime, event.StartDateTime, event.DurationMin,
               event.StopId, event.StopTypeSnapshot, event.RelatedMachineSnapshot,
               event.SubMachineSnapshot, event.CauseSnapshot, event.ShiftID
        FROM dbo.LoggerEvent AS event
        WHERE event.ProductionDate=? AND event.StopId IN (?,?,?,?,?,?)
        ORDER BY event.McId, event.McInstanceNo, event.StopDateTime, event.LoggerEventID
    """, production_date, *category_ids)
    events = _rows(cursor, ("LoggerEventID", "McId", "McInstanceNo", "StopDateTime",
                            "StartDateTime", "DurationMin", "StopId", "StopTypeSnapshot",
                            "RelatedMachineSnapshot", "SubMachineSnapshot", "CauseSnapshot",
                            "ShiftID"))
    stop_type_by_id = {stop_id: name for name, stop_id in stop_ids.items()}
    summary_by_machine = {
        (row["McId"], row["McInstanceNo"]): row for row in summary
    }
    valid_shift_ids = {int(rule["ShiftID"]) for rule in shift_rules}
    for event in events:
        machine_key = (event["McId"], event["McInstanceNo"])
        row = summary_by_machine[machine_key]
        stop_type = stop_type_by_id[event["StopId"]]
        duration = int(event["DurationMin"] or 0)
        shift_id = event.get("ShiftID")
        if shift_id is not None:
            try:
                shift_id = int(shift_id)
            except (TypeError, ValueError):
                shift_id = None
        if shift_id not in valid_shift_ids and event["StopDateTime"] is not None:
            resolved_shift = resolve_shift(
                production_date, event["StopDateTime"].time(), None, shift_rules)
            shift_id = int(resolved_shift) if resolved_shift is not None else None
        if shift_id in SHIFT_SUMMARY_FIELDS:
            row[SHIFT_SUMMARY_FIELDS[shift_id][stop_type]] += duration

    cursor.execute("""
        SELECT COUNT(*)
        FROM dbo.LoggerEvent AS first_event
        JOIN dbo.LoggerEvent AS second_event
          ON first_event.LoggerEventID < second_event.LoggerEventID
         AND first_event.ProductionDate=second_event.ProductionDate
         AND first_event.McId=second_event.McId
         AND first_event.McInstanceNo=second_event.McInstanceNo
         AND first_event.StopDateTime < second_event.StartDateTime
         AND first_event.StartDateTime > second_event.StopDateTime
        WHERE first_event.ProductionDate=?
    """, production_date)
    overlap_count = int(cursor.fetchone()[0] or 0)
    return {
        "summary": summary,
        "events": events,
        "overlap_count": overlap_count,
        "overlap_warning": overlap_count > 0,
        "stop_ids": stop_ids,
    }