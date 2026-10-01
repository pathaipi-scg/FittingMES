"""Read-only LOGGER time summary queries."""

import re


SUMMARY_TYPES = {
    "SETUP": "SetupMin",
    "CHGOVER": "ChgOverMin",
    "SMDT": "SmdtMin",
    "BD": "BreakdownMin",
    "CLEAN": "CleanMin",
}

GUIDE_TIME_FIELDS = {
    "SETUP": "SetupMinutes",
    "CHGOVER": "ChgOverMinutes",
    "CLEAN": "CleaningMinutes",
    "BD": "BreakdownMinutes",
}


def _rows(cursor, keys):
    return [dict(zip(keys, row)) for row in cursor.fetchall()]


def read_logger_press_guide(cursor, production_date, equipment_code):
    """Read the daily LOGGER guide for one explicitly mapped F press."""
    match = re.fullmatch(r"F([1-9][0-9]*)", str(equipment_code or ""))
    empty = dict(SetupMinutes=None, ChgOverMinutes=None, CleaningMinutes=None,
                 BreakdownMinutes=None, SmdtMinutes=None,
                 HasSetup=False, HasChgOver=False, HasCleaning=False,
                 HasBreakdown=False, HasSmdt=False)
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
    cursor.execute("""
        SELECT
            SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END),
            SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END),
            SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END),
            SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END),
            SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END),
            SUM(CASE WHEN event.StopId=? THEN 1 ELSE 0 END),
            SUM(CASE WHEN event.StopId=? THEN 1 ELSE 0 END),
            SUM(CASE WHEN event.StopId=? THEN 1 ELSE 0 END),
            SUM(CASE WHEN event.StopId=? THEN 1 ELSE 0 END),
            SUM(CASE WHEN event.StopId=? THEN 1 ELSE 0 END)
        FROM dbo.LoggerEvent AS event
        WHERE event.ProductionDate=? AND event.McId=? AND event.McInstanceNo=?
          AND event.StopId IN (?,?,?,?,?)
    """, *(category_ids + category_ids + (production_date, machines[0][0], instance_no) + category_ids))
    result = cursor.fetchone()
    if not result or all(value is None or value == 0 for value in result):
        return empty
    values = [int(value or 0) for value in result[:5]]
    presence = [bool(value) for value in result[5:]]
    return dict(SetupMinutes=values[0], ChgOverMinutes=values[1],
                CleaningMinutes=values[4], BreakdownMinutes=values[3],
                SmdtMinutes=values[2], HasSetup=presence[0],
                HasChgOver=presence[1], HasCleaning=presence[4],
                HasBreakdown=presence[3], HasSmdt=presence[2])


def _summary_stop_ids(cursor):
    cursor.execute("""
        SELECT StopId, StopType
        FROM dbo.Fitting_StopType
        WHERE IsActive=1 AND StopType IN (?,?,?,?,?)
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
               SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END) AS SmdtMin,
               SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END) AS BreakdownMin,
               SUM(CASE WHEN event.StopId=? THEN event.DurationMin ELSE 0 END) AS CleanMin
        FROM dbo.LoggerEvent AS event
        JOIN dbo.Fitting_MainMachine AS machine ON machine.McId=event.McId
        WHERE event.ProductionDate=? AND event.StopId IN (?,?,?,?,?)
        GROUP BY event.McId, event.McInstanceNo, machine.Machine
        ORDER BY machine.Machine, event.McInstanceNo
    """, *category_ids, production_date, *category_ids)
    summary = _rows(cursor, ("McId", "McInstanceNo", "Machine", "SetupMin",
                             "ChgOverMin", "SmdtMin", "BreakdownMin", "CleanMin"))
    for row in summary:
        for field in ("SetupMin", "ChgOverMin", "SmdtMin", "BreakdownMin", "CleanMin"):
            row[field] = int(row[field] or 0)
        row["TotalLoggedMin"] = sum(row[field] for field in (
            "SetupMin", "ChgOverMin", "SmdtMin", "BreakdownMin", "CleanMin"))
        row["MachineLabel"] = f'{row["Machine"]}{row["McInstanceNo"]}'

    cursor.execute("""
        SELECT event.LoggerEventID, event.McId, event.McInstanceNo,
               event.StopDateTime, event.StartDateTime, event.DurationMin,
               event.StopId, event.StopTypeSnapshot, event.RelatedMachineSnapshot,
               event.SubMachineSnapshot, event.CauseSnapshot
        FROM dbo.LoggerEvent AS event
        WHERE event.ProductionDate=? AND event.StopId IN (?,?,?,?,?)
        ORDER BY event.McId, event.McInstanceNo, event.StopDateTime, event.LoggerEventID
    """, production_date, *category_ids)
    events = _rows(cursor, ("LoggerEventID", "McId", "McInstanceNo", "StopDateTime",
                            "StartDateTime", "DurationMin", "StopId", "StopTypeSnapshot",
                            "RelatedMachineSnapshot", "SubMachineSnapshot", "CauseSnapshot"))

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