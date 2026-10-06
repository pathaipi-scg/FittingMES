"""Context preparation for the quantity-based REJECT operator page."""
from urllib.parse import urlencode

from app.reject import WORKFLOW_TABLES


def reject_page_context(data, production_date, workflow=None, shift_id=None,
                        line_equipment_id=None, production_id=None, entries=None,
                        saved=False, error=None, form=None):
    form = dict(form or {})
    shifts = list(data.get("shifts") or [])
    lines = list(data.get("lines") or [])
    presses = list(data.get("presses") or [])
    all_lots = list(data.get("lots") or [])
    all_reasons = list(data.get("reasons") or [])

    chosen_workflow = str(
        form.get("workflow") or workflow or "production"
    ).strip().lower()
    if chosen_workflow not in WORKFLOW_TABLES:
        chosen_workflow = "production"

    requested_shift = form.get("shift_id") or shift_id
    valid_shift_ids = {str(item["ShiftID"]) for item in shifts}
    selected_shift_id = str(requested_shift or "")
    if selected_shift_id not in valid_shift_ids:
        selected_shift_id = str(shifts[0]["ShiftID"]) if shifts else ""
    selected_shift = next(
        (item for item in shifts if str(item["ShiftID"]) == selected_shift_id),
        None,
    )

    requested_line = form.get("line_equipment_id") or line_equipment_id
    valid_line_ids = {str(item["EquipmentID"]) for item in lines}
    selected_line_id = str(requested_line or "")
    if selected_line_id not in valid_line_ids:
        selected_line_id = str(lines[0]["EquipmentID"]) if lines else ""
    selected_line = next(
        (item for item in lines if str(item["EquipmentID"]) == selected_line_id),
        None,
    )

    lots = [
        item for item in all_lots
        if selected_shift is not None
        and str(item["ShiftID"]) == str(selected_shift["ShiftID"])
    ]
    requested_production = form.get("production_id") or production_id
    lot_ids = {str(item["ProductionID"]) for item in lots}
    selected_production_id = str(requested_production or "")
    if selected_production_id not in lot_ids:
        selected_production_id = (
            str(lots[0]["ProductionID"]) if lots else ""
        )
    selected_lot = next(
        (
            item for item in lots
            if str(item["ProductionID"]) == selected_production_id
        ),
        None,
    )
    family_id = (
        selected_lot["ProductFamilyID"] if selected_lot is not None else None
    )
    reasons = [
        item for item in all_reasons
        if family_id is not None
        and str(item["ProductFamilyID"]) == str(family_id)
    ]

    all_source_options = []
    for line in lines:
        line_id = str(line["EquipmentID"])
        all_source_options.append(dict(
            EquipmentID=line["EquipmentID"],
            EquipmentCode=line["EquipmentCode"],
            EquipmentName=line["EquipmentName"],
            EquipmentType="LINE",
            LineEquipmentID=line["EquipmentID"],
        ))
        all_source_options.extend(
            dict(item, EquipmentType="PRESS")
            for item in presses
            if str(item["LineEquipmentID"]) == line_id
        )
    source_options = [
        item for item in all_source_options
        if str(item["LineEquipmentID"]) == selected_line_id
    ]

    requested_source = form.get("source_equipment_id", "")
    requested_reason = form.get("reject_reason_id", "")
    requested_scope = form.get("reject_source_scope_id", "")
    selected_reason = next(
        (
            item for item in reasons
            if str(item["RejectReasonID"]) == str(requested_reason)
        ),
        None,
    )
    if not requested_scope and selected_reason is not None:
        requested_scope = selected_reason["RejectSourceScopeID"]

    cal_url = ""
    if selected_shift_id and selected_production_id:
        cal_url = "/reject/cal?" + urlencode({
            "production_date": production_date,
            "workflow": chosen_workflow,
            "shift_id": selected_shift_id,
            "production_id": selected_production_id,
        })

    client_data = dict(
        lots=[{
            "ProductionID": item["ProductionID"],
            "ShiftCode": item["ShiftCode"],
            "ProductFamilyID": item["ProductFamilyID"],
            "LotNo": item["LotNo"],
            "ProductFamily": item["ProductFamily"],
            "ProductName": item["ProductName"],
        } for item in all_lots],
        reasons=[{
            "ProductFamilyID": item["ProductFamilyID"],
            "RejectReasonID": item["RejectReasonID"],
            "ReasonCode": item["ReasonCode"],
            "ReasonNameTH": item["ReasonNameTH"],
            "RejectSourceScopeID": item["RejectSourceScopeID"],
            "SourceScopeCode": item["SourceScopeCode"],
        } for item in all_reasons],
        sources=[{
            "EquipmentID": item["EquipmentID"],
            "EquipmentCode": item["EquipmentCode"],
            "EquipmentName": item["EquipmentName"],
            "EquipmentType": item["EquipmentType"],
            "LineEquipmentID": item["LineEquipmentID"],
        } for item in all_source_options],
    )
    return dict(
        page_title="REJECT",
        active_tab="reject",
        production_date=production_date,
        workflow=chosen_workflow,
        shifts=shifts,
        lines=lines,
        lots=lots,
        reasons=reasons,
        source_options=source_options,
        entries=list(entries or []),
        selected_shift_id=selected_shift_id,
        selected_line_id=selected_line_id,
        selected_production_id=selected_production_id,
        selected_family_id=family_id,
        selected_source_id=str(requested_source or ""),
        selected_reason_id=str(requested_reason or ""),
        selected_scope_id=str(requested_scope or ""),
        qty=str(form.get("qty") or ""),
        entry_id=str(form.get("entry_id") or ""),
        form=form,
        saved=saved,
        error=error,
        cal_url=cal_url,
        reject_client_data=client_data,
    )
