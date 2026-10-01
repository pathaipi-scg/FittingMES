"""Read-only LOGGER Master Maintenance review data."""


def _rows(cursor, keys):
    return [dict(zip(keys, row)) for row in cursor.fetchall()]


def _by_id(rows, key):
    return {row[key]: row for row in rows}


def _active_label(row):
    return "ACTIVE" if row["IsActive"] else "INACTIVE"


def _instances(row, name_key):
    count = row["No"]
    if not isinstance(count, int) or count < 1:
        return [], [f"{name_key} instance count must be a positive integer."]
    return [f'{row[name_key]}{number}' for number in range(1, count + 1)], []


def build_master_review(main_machines, sub_machines, stop_types, sub_stop_types, causes):
    main_by_id = _by_id(main_machines, "McId")
    sub_by_id = _by_id(sub_machines, "SubMcId")
    stop_by_id = _by_id(stop_types, "StopId")
    sub_stop_by_id = _by_id(sub_stop_types, "SubStopId")
    warnings = []

    for row in main_machines:
        instances, row_warnings = _instances(row, "Machine")
        row["status"] = _active_label(row)
        row["instances"] = instances
        row["warnings"] = row_warnings
        warnings.extend(f'Main Machine {row["McId"]}: {item}' for item in row_warnings)

    for row in sub_machines:
        row["status"] = _active_label(row)
        row["parent_machine"] = main_by_id.get(row["McId"], {}).get("Machine", "MISSING")
        instances, row_warnings = _instances(row, "Equipment")
        row["instances"] = instances
        row["warnings"] = row_warnings[:]
        if row["McId"] not in main_by_id:
            row["warnings"].append("McId references a missing Main Machine.")
        warnings.extend(f'SubMachine {row["SubMcId"]}: {item}' for item in row["warnings"])

    for row in stop_types:
        row["status"] = _active_label(row)

    for row in sub_stop_types:
        row["status"] = _active_label(row)
        row["parent_stop_type"] = stop_by_id.get(row["StopId"], {}).get("StopType", "MISSING")
        row["warnings"] = [] if row["StopId"] in stop_by_id else ["StopId references a missing Stop Type."]
        warnings.extend(f'SubStopType {row["SubStopId"]}: {item}' for item in row["warnings"])

    for row in causes:
        row["status"] = _active_label(row)
        machine = main_by_id.get(row["McId"])
        sub_machine = sub_by_id.get(row["SubMcId"]) if row["SubMcId"] is not None else None
        stop_type = stop_by_id.get(row["StopId"])
        sub_stop_type = sub_stop_by_id.get(row["SubStopId"]) if row["SubStopId"] is not None else None
        row["machine_name"] = machine["Machine"] if machine else "MISSING"
        row["sub_machine_name"] = sub_machine["Equipment"] if sub_machine else ("-" if row["SubMcId"] is None else "MISSING")
        row["stop_type_name"] = stop_type["StopType"] if stop_type else "MISSING"
        row["sub_stop_type_name"] = sub_stop_type["SubStopType"] if sub_stop_type else ("-" if row["SubStopId"] is None else "MISSING")
        row["mapping_kind"] = "MACHINE" if row["SubMcId"] is None else (
            "RELATED_PROXY" if sub_machine and sub_machine["IsRelated"] else "DIRECT_SUB / PHYSICAL")
        row["warnings"] = []
        if machine is None:
            row["warnings"].append("McId references a missing Main Machine.")
        elif not machine["IsActive"]:
            row["warnings"].append("McId references an inactive Main Machine.")
        if row["SubMcId"] is not None and sub_machine is None:
            row["warnings"].append("SubMcId references a missing SubMachine.")
        elif sub_machine and not sub_machine["IsActive"]:
            row["warnings"].append("SubMcId references an inactive SubMachine.")
        if sub_machine and sub_machine["IsRelated"] and sub_machine["McId"] != row["McId"]:
            row["warnings"].append("Related proxy points to a different Main Machine than Cause.McId.")
        if sub_machine and not sub_machine["IsRelated"] and sub_machine["McId"] != row["McId"]:
            row["warnings"].append("Physical SubMachine ownership differs from Cause.McId.")
        if stop_type is None:
            row["warnings"].append("StopId references a missing Stop Type.")
        if row["SubStopId"] is not None and sub_stop_type is None:
            row["warnings"].append("SubStopId references a missing Sub Stop Type.")
        elif sub_stop_type and sub_stop_type["StopId"] != row["StopId"]:
            row["warnings"].append("SubStopId belongs to a different Stop Type.")
        if row["MEO"] not in (None, "M", "E", "O"):
            row["warnings"].append("MEO is not one of M, E, O, or NULL.")
        warnings.extend(f'Cause {row["CauseId"]}: {item}' for item in row["warnings"])

    families = [
        ("Main Machine", main_machines), ("Sub Machine", sub_machines),
        ("Stop Type", stop_types), ("Sub Stop Type", sub_stop_types),
        ("Cause", causes),
    ]
    counts = [{"name": name, "total": len(rows),
               "active": sum(bool(row["IsActive"]) for row in rows),
               "inactive": sum(not bool(row["IsActive"]) for row in rows)}
              for name, rows in families]
    return {
        "main_machines": main_machines, "sub_machines": sub_machines,
        "stop_types": stop_types, "sub_stop_types": sub_stop_types,
        "causes": causes, "counts": counts, "warnings": warnings,
    }


def read_logger_master_review(cursor):
    cursor.execute("""
        SELECT McId, Machine, No, Relate, IsActive
        FROM dbo.Fitting_MainMachine ORDER BY McId
    """)
    main_machines = _rows(cursor, ("McId", "Machine", "No", "Relate", "IsActive"))
    cursor.execute("""
        SELECT SubMcId, Equipment, McId, No, IsActive, IsRelated
        FROM dbo.Fitting_SubMachine ORDER BY SubMcId
    """)
    sub_machines = _rows(cursor, ("SubMcId", "Equipment", "McId", "No", "IsActive", "IsRelated"))
    cursor.execute("SELECT StopId, StopType, IsActive FROM dbo.Fitting_StopType ORDER BY StopId")
    stop_types = _rows(cursor, ("StopId", "StopType", "IsActive"))
    cursor.execute("""
        SELECT SubStopId, SubStopType, StopId, IsActive
        FROM dbo.Fitting_SubStopType ORDER BY SubStopId
    """)
    sub_stop_types = _rows(cursor, ("SubStopId", "SubStopType", "StopId", "IsActive"))
    cursor.execute("""
        SELECT CauseId, Cause, McId, SubMcId, StopId, SubStopId, IsActive, MEO
        FROM dbo.Fitting_Cause ORDER BY CauseId
    """)
    causes = _rows(cursor, ("CauseId", "Cause", "McId", "SubMcId", "StopId", "SubStopId", "IsActive", "MEO"))
    return build_master_review(main_machines, sub_machines, stop_types, sub_stop_types, causes)
