"""LOGGER operator page context and request mapping."""
import json
from datetime import date

from app.logger import (LoggerMasters, LoggerSaveInput, expand_main_machine,
                        expand_sub_related_options, main_machine_categories,
                        normalize_sub_related_selection, suggest_cause,
                        sub_related_options_for_instance)
from app.production_data import resolve_shift


def _json(value):
    return json.dumps(value, default=str)


def logger_page_context(masters: LoggerMasters, production_date, logger_events=None,
                        saved=False, error=None, form=None, shift_rules=None,
                        preset_shift_id=None):
    main_categories = main_machine_categories(masters.main_machines)
    main_instances = [instance for machine in masters.main_machines
                      for instance in expand_main_machine(machine)]
    sub_related_options = expand_sub_related_options(
        masters.main_machines, masters.sub_machines)
    instance_options = {}
    for machine in masters.main_machines:
        for instance in expand_main_machine(machine):
            key = f'{instance["mc_id"]}:{instance["mc_instance_no"]}'
            instance_options[key] = sub_related_options_for_instance(
                masters.main_machines, masters.sub_machines,
                instance["mc_id"], instance["mc_instance_no"])
    form = dict(form or {})
    shift_rules = sorted(
        list(shift_rules or []),
        key=lambda item: (item["StartTime"], item["ShiftID"]),
    )
    valid_shift_ids = {str(item["ShiftID"]) for item in shift_rules}
    selected_shift = str(
        preset_shift_id or form.get("preset_shift_id") or
        (shift_rules[0]["ShiftID"] if shift_rules else "")
    )
    if selected_shift not in valid_shift_ids:
        selected_shift = str(shift_rules[0]["ShiftID"]) if shift_rules else ""
    event_rows = []
    for event in logger_events or []:
        event_row = dict(event)
        stop_datetime = event_row.get("StopDateTime")
        event_row["ResolvedShiftID"] = (
            resolve_shift(production_date, stop_datetime.time(), None, shift_rules)
            if stop_datetime is not None else event_row.get("ShiftID")
        )
        event_rows.append(event_row)
    return dict(
        page_title="LOGGER", active_tab="logger", production_date=production_date,
        saved=saved, error=error, form=form, logger_events=event_rows,
        shift_rules=shift_rules, preset_shift_id=selected_shift,
        main_categories=main_categories, main_instances=main_instances,
        sub_related_options=sub_related_options,
        stop_types=masters.stop_types, sub_stop_types=masters.sub_stop_types,
        causes=masters.causes,
        main_categories_json=_json(main_categories),
        main_machines_json=_json(masters.main_machines),
        main_instances_json=_json(main_instances),
        instance_options_json=_json(instance_options),
        sub_related_options_json=_json(sub_related_options),
        sub_machines_json=_json(masters.sub_machines),
        stop_types_json=_json(masters.stop_types),
        sub_stop_types_json=_json(masters.sub_stop_types),
        causes_json=_json(masters.causes),
        logger_events_json=_json(event_rows),
    )


def logger_form_input(form):
    try:
        production_date = date.fromisoformat(str(form.get("production_date", "")))
    except ValueError:
        raise ValueError("Enter a valid Production Date.") from None
    try:
        machine_id = int(form.get("mc_id", ""))
        machine_instance_no = int(form.get("mc_instance_no", ""))
    except (TypeError, ValueError):
        raise ValueError("Select a valid Main Machine instance.") from None
    try:
        selection = json.loads(form.get("sub_related_selection", ""))
    except (TypeError, json.JSONDecodeError):
        raise ValueError("Select a valid Sub / Related M/C.") from None
    if not isinstance(selection, dict):
        raise ValueError("Select a valid Sub / Related M/C.")

    def optional_int(name):
        value = form.get(name)
        return None if value in (None, "") else int(value)

    return LoggerSaveInput(
        production_date=production_date,
        preset_shift_id=optional_int("preset_shift_id"),
        event_shift_id=form.get("event_shift_id"),
        logger_event_id=optional_int("logger_event_id"),
        stop=form.get("stop", ""), start=form.get("start", ""),
        duration_min=form.get("duration_min", ""),
        mc_id=machine_id, mc_instance_no=machine_instance_no,
        related_mc_id=optional_int("related_mc_id"),
        related_mc_instance_no=optional_int("related_mc_instance_no"),
        sub_mc_id=optional_int("sub_mc_id"),
        sub_mc_instance_no=optional_int("sub_mc_instance_no"),
        stop_id=optional_int("stop_id"), sub_stop_id=optional_int("sub_stop_id"),
        cause_id=optional_int("cause_id"), meo=form.get("meo") or None,
        note=form.get("note") or None, created_by=None,
        classification_edited=str(form.get("classification_edited", "false")).lower() == "true",
    ), selection


def normalize_form_selection(selection, masters):
    return normalize_sub_related_selection(selection, masters.main_machines,
                                           masters.sub_machines)


def cause_suggestion(cause, selected_machine_id, options):
    return suggest_cause(cause, selected_machine_id=selected_machine_id,
                         sub_related_options=options)