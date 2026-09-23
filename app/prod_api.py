"""Read-only FittingMES records for future production integration review."""
from datetime import datetime, timedelta
from app.lots import rows, day
from app.production_data import calculate


def read_prod_records(cursor, production_date):
    cursor.execute("""SELECT p.ProductionID,p.ProdDate,p.Shift,p.MaterialCode,
        p.MaterialName,p.LotNo,p.ProductFamily,p.ProductCode,p.PlanName,p.PlanQty,
        d.ProductionStartTime,d.ProductionEndTime,d.CounterQty,d.CuringQty,d.Remark
        FROM dbo.ProductionLot p
        LEFT JOIN dbo.ProductionData d ON d.ProductionID=p.ProductionID
        WHERE p.IsActive=1 AND p.ProdDate=?
        ORDER BY p.ProductionID""", production_date)
    records = rows(cursor)
    cursor.execute("""SELECT Company,Plant,Machine,PlanWeek,VersionNo,PlanName,
        Shift,StartTime,MaterialCode,PlanCount,OperationCode
        FROM dbo.P_ActivePlan
        WHERE Company=? AND Plant=? AND Machine=? AND StartTime=?""",
        'CRTC', '30A1', 'SB2-3', production_date)
    plans = rows(cursor)
    for record in records:
        record.update(resolve_plan(record, plans))
        record.update(calculate(record['CounterQty'], record['CuringQty']))
    return records


PLAN_FIELDS = ('Plant', 'Machine', 'PlanWeek', 'VersionNo', 'OperationCode')


def clean_string(value):
    if value is None:
        return None
    return str(value).strip() or None


def local_timestamps(record):
    production_date = record.get('ProdDate')
    start, end = record.get('ProductionStartTime'), record.get('ProductionEndTime')
    if production_date is None:
        return None, None
    start_at = datetime.combine(day(production_date), start) if start is not None else None
    end_at = datetime.combine(day(production_date), end) if end is not None else None
    if start_at is not None and end_at is not None and end_at < start_at:
        end_at += timedelta(days=1)
    return tuple(value.isoformat(timespec='minutes') if value is not None else None
                 for value in (start_at, end_at))


def group_key(record):
    return (day(record.get('ProdDate')), clean_string(record.get('Shift')),
            clean_string(record.get('Plant')), clean_string(record.get('Machine')))


def resolve_plan(record, plans):
    # Shift is operator-editable, so it is not an immutable plan key.
    candidates = [p for p in plans if day(p['StartTime']) == day(record['ProdDate'])
                  and clean_string(p['PlanName']) == clean_string(record['PlanName'])
                  and clean_string(p['MaterialCode']) == clean_string(record['MaterialCode'])
                  and p['PlanCount'] == record['PlanQty']]
    result = {}
    for field in PLAN_FIELDS:
        values = {clean_string(p[field]) for p in candidates}
        result[field] = next(iter(values)) if len(values) == 1 else None
    result['PlanResolution'] = (
        'No matching ActivePlan snapshot; plan mappings are unresolved.' if not candidates else
        'Matched saved date, plan name, material and quantity in the installation ActivePlan scope. '
        'Plant/machine/version were not persisted on the lot; only values shared by all matching rows are used. '
        'This does not prove the original plan version.')
    return result


def build_pis_production_item(record):
    start, end = local_timestamps(record)
    return dict(operationCode=clean_string(record.get('OperationCode')),
                dateTimeStart=start, dateTimeEnd=end,
                planWeek=clean_string(record.get('PlanWeek')), planName=clean_string(record.get('PlanName')),
                versionNo=clean_string(record.get('VersionNo')), followPlan=None, remark=clean_string(record.get('Remark')),
                itemDetails=[], itemOutputs=[dict(
                    materialCode=clean_string(record.get('MaterialCode')), lotNo=clean_string(record.get('LotNo')),
                    gross0=record.get('CuringQty'), tool='', remark=clean_string(record.get('Remark')),
                    outputDetails=[dict(statusCode='Curing', lockProdOrderNo='', reasonCode='',
                        reasonCode2='', effectiveDate=record.get('ProdDate'), lockId='',
                        count=record.get('CuringQty'), remark='')])], itemInputs=[], itemProperties=[])


def build_pis_prodorders_payload(records):
    if not records:
        raise ValueError('No Production records exist for this date.')
    key = group_key(records[0])
    if any(group_key(row) != key for row in records):
        raise ValueError('Production date, shift, plant and machine must match within a preview group.')
    return dict(productionDate=key[0], shiftCode=key[1], plantCode=key[2], machineCode=key[3],
                operatorName='', resources=[], productionItems=[build_pis_production_item(row) for row in records])


def field_mapping(record):
    fields = [
        ('productionDate','ProductionLot.ProdDate','ProdDate'),
        ('shiftCode','ProductionLot.Shift (saved Production shift)','Shift'),
        ('plantCode','P_ActivePlan.Plant','Plant'),
        ('machineCode','P_ActivePlan.Machine','Machine'),
        ('operationCode','P_ActivePlan.OperationCode','OperationCode'),
        ('dateTimeStart','ProductionLot.ProdDate + ProductionData.ProductionStartTime (factory local)','ProductionStartTime'),
        ('dateTimeEnd','ProductionLot.ProdDate + ProductionData.ProductionEndTime (next day if earlier than Start)','ProductionEndTime'),
        ('planWeek','P_ActivePlan.PlanWeek','PlanWeek'),
        ('planName','ProductionLot.PlanName','PlanName'),
        ('versionNo','P_ActivePlan.VersionNo (resolved source, not stored version)','VersionNo'),
        ('followPlan','UNMAPPED: no confirmed source',None),
        ('remark / itemOutputs.remark','ProductionData.Remark','Remark'),
        ('materialCode','ProductionLot.MaterialCode','MaterialCode'),
        ('lotNo','ProductionLot.LotNo','LotNo'),
        ('gross0','ProductionData.CuringQty','CuringQty'),
        ('outputDetails.count','ProductionData.CuringQty','CuringQty'),
        ('outputDetails.effectiveDate','ProductionLot.ProdDate','ProdDate')]
    start, end = local_timestamps(record)
    values = dict(record, ProductionStartTime=start, ProductionEndTime=end)
    mapping = []
    for field, source, key in fields:
        value = values.get(key)
        if isinstance(value, str):
            value = clean_string(value)
        missing = value is None or value == ''
        severity = ('unresolved' if field == 'followPlan' else
                    'optional' if field == 'remark / itemOutputs.remark' else
                    'required') if missing else 'mapped'
        mapping.append(dict(field=field, source=source, value=value, missing=missing, severity=severity))
    mapping.append(dict(field='outputDetails.statusCode', source='Requested preview constant', value='Curing', missing=False, severity='mapped'))
    return mapping


def build_pis_date_preview(records, production_date):
    """Include every date record once, preserving the confirmed header grouping.

    Each group is one ProdOrders request body in the date-level ALL PROD operation.
    Return separate bodies, never a PIS batch wrapper.
    """
    groups = {}
    for record in records:
        if day(record['ProdDate']) != production_date:
            raise ValueError('All preview records must belong to the selected Production Date.')
        key = group_key(record)
        groups.setdefault(key, []).append(record)
    return [build_pis_prodorders_payload(sorted(groups[key], key=lambda row: (
        row.get('ProductionStartTime').isoformat() if row.get('ProductionStartTime') is not None else '',
        clean_string(row.get('LotNo')) or '', row['ProductionID'])))
        for key in sorted(groups, key=lambda key: '|'.join('' if value is None else str(value) for value in key))]


def preview_readiness(payload):
    missing = []
    for field in ('productionDate', 'shiftCode', 'plantCode', 'machineCode'):
        if payload.get(field) is None or payload.get(field) == '':
            missing.append(field)
    for index, item in enumerate(payload['productionItems'], 1):
        prefix = 'Item ' + str(index) + ': '
        for field in ('operationCode', 'planWeek', 'planName', 'versionNo', 'dateTimeStart', 'dateTimeEnd'):
            if item.get(field) is None or item.get(field) == '':
                missing.append(prefix + field)
        output = item['itemOutputs'][0]
        for field in ('materialCode', 'lotNo', 'gross0'):
            if output.get(field) is None or output.get(field) == '':
                missing.append(prefix + field + (' (CuringQty)' if field == 'gross0' else ''))
    return dict(missing=missing, ready=not missing,
                unresolved=['followPlan source not implemented'],
                notes=['itemDetails/tasks, itemInputs, itemProperties and resources have no confirmed source; arrays remain empty.'])
