"""Read-only LOGGER Master loading and hierarchy normalization helpers."""
from dataclasses import dataclass
from typing import Any

DIRECT_SUB = "DIRECT_SUB"
RELATED_MAIN = "RELATED_MAIN"
RELATED_SUB = "RELATED_SUB"


@dataclass(frozen=True)
class LoggerMasters:
    main_machines: list[dict[str, Any]]
    sub_machines: list[dict[str, Any]]
    stop_types: list[dict[str, Any]]
    sub_stop_types: list[dict[str, Any]]
    causes: list[dict[str, Any]]


class LoggerResolutionError(ValueError):
    """Raised when a LOGGER selection cannot be normalized safely."""


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
        SELECT SubMcId, McId, Equipment AS SubMachine, No, IsRelated
        FROM dbo.Fitting_SubMachine
        WHERE IsActive=1
        ORDER BY SubMcId
    """)
    return _rows(cursor, ("SubMcId", "McId", "SubMachine", "No", "IsRelated"))


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


def expand_main_machine(machine):
    return [
        {"mc_id": machine["McId"], "mc_instance_no": instance_no,
         "display_label": f'{machine["Machine"]}{instance_no}'}
        for instance_no in range(1, int(machine["No"]) + 1)
    ]


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
