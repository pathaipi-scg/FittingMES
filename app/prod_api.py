"""Read-only FittingMES records for future production integration review."""
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


def resolve_plan(record, plans):
    # Shift is operator-editable, so it is not an immutable plan key.
    candidates = [p for p in plans if day(p['StartTime']) == day(record['ProdDate'])
                  and p['PlanName'] == record['PlanName']
                  and p['MaterialCode'] == record['MaterialCode']
                  and p['PlanCount'] == record['PlanQty']]
    result = {}
    for field in PLAN_FIELDS:
        values = {p[field] for p in candidates}
        result[field] = next(iter(values)) if len(values) == 1 else None
    result['PlanResolution'] = (
        'No matching ActivePlan snapshot; plan mappings are unresolved.' if not candidates else
        'Matched saved date, plan name, material and quantity in the installation ActivePlan scope. '
        'Plant/machine/version were not persisted on the lot; only values shared by all matching rows are used. '
        'This does not prove the original plan version.')
    return result


def build_pis_production_item(record):
    return dict(operationCode=record.get('OperationCode'),
                dateTimeStart=record.get('ProductionStartTime'), dateTimeEnd=record.get('ProductionEndTime'),
                planWeek=record.get('PlanWeek'), planName=record.get('PlanName'),
                versionNo=record.get('VersionNo'), followPlan=None, remark=record.get('Remark'),
                itemDetails=[], itemOutputs=[dict(
                    materialCode=record.get('MaterialCode'), lotNo=record.get('LotNo'),
                    gross0=record.get('CuringQty'), tool='', remark=record.get('Remark'),
                    outputDetails=[dict(statusCode='Curing', lockProdOrderNo='', reasonCode='',
                        reasonCode2='', effectiveDate=record.get('ProdDate'), lockId='',
                        count=record.get('CuringQty'), remark='')])], itemInputs=[], itemProperties=[])


def build_pis_prodorders_payload(records):
    if not records:
        raise ValueError('Select at least one Production record.')
    def group(row):
        return (row.get('ProdDate'), row.get('Shift'), row.get('Plant'), row.get('Machine'))
    key = group(records[0])
    if any(group(row) != key for row in records):
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
        ('dateTimeStart','ProductionData.ProductionStartTime (time only)','ProductionStartTime'),
        ('dateTimeEnd','ProductionData.ProductionEndTime (time only)','ProductionEndTime'),
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
    mapping = [dict(field=field, source=source, value=record.get(key),
                    missing=record.get(key) is None or record.get(key) == '')
               for field,source,key in fields]
    mapping.append(dict(field='outputDetails.statusCode', source='Requested preview constant', value='Curing', missing=False))
    return mapping
