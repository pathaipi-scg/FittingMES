"""LOGGER operator page context and request mapping."""
import json
from datetime import date

from app.logger import (LoggerMasters, LoggerSaveInput, expand_main_machine,
                        expand_sub_related_options, main_machine_categories,
                        normalize_sub_related_selection, suggest_cause,
                        sub_related_options_for_instance)


def _json(value):
    return json.dumps(value, default=str)


def logger_page_context(masters: LoggerMasters, production_date, logger_events=None,
                        saved=False, error=None, form=None):
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
    return dict(
        page_title="LOGGER", active_tab="logger", production_date=production_date,
        saved=saved, error=error, form=form, logger_events=list(logger_events or []),
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
        logger_events_json=_json(list(logger_events or [])),
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