"""Read-only Reject API readiness and preview support."""
import json
from datetime import datetime

from app.lots import rows, day
from app.prod_api import resolve_plan
from app.production_data import calculate

CB_REJECT_REASON_FIELDS = {
    'R01': 'Rej_R01', 'R02': 'Rej_R02', 'R03': 'Rej_R03',
    'R04': 'Rej_R04', 'R05': 'Rej_R05', 'R06': 'Rej_R06',
    'R08': 'Rej_R08', 'R12': 'Rej_R12', 'R13': 'Rej_R13',
}
CB_SUPPORTED_REASONS = frozenset((*CB_REJECT_REASON_FIELDS, 'R99'))


def build_output_details_query(record):
    production_date = record.get('ProdDate')
    date_text = day(production_date).isoformat() if production_date else ''
    return dict(PlantCode=str(record.get('Plant') or '').strip(),
                MachineCode=str(record.get('Machine') or '').strip(),
                DateFrom=date_text, DateTo=date_text,
                LotNumbers=str(record.get('LotNo') or '').strip())


def parse_output_details_response(response):
    if not isinstance(response, dict) or not isinstance(response.get('body'), str):
        raise ValueError('OutputDetails response is malformed.')
    try:
        payload = json.loads(response['body'])
    except (TypeError, json.JSONDecodeError):
        raise ValueError('OutputDetails response is not valid JSON.') from None
    if not isinstance(payload, list):
        raise ValueError('OutputDetails response is not an array.')
    return payload


def summarize_output_details(output_details):
    if not isinstance(output_details, list):
        raise ValueError('OutputDetails response is not an array.')
    summary = dict(originalQty=None, stockyard=0, rejects={}, totalReject=0,
                   totalTransferred=0, curingRemaining=0,
                   calculatedRemaining=None, curingOutputDetailId=None)
    for item in output_details:
        if not isinstance(item, dict):
            raise ValueError('OutputDetails contains a malformed item.')
        status = str(item.get('status') or '').strip()
        total = max(int(item.get('total') or 0), 0)
        if status.lower() == 'curing':
            summary['curingRemaining'] += total
            if summary['curingOutputDetailId'] is None:
                summary['curingOutputDetailId'] = item.get('productionOrderOutputDetailID')
        elif status == 'Stockyard (แกะดี)':
            summary['stockyard'] += total
        elif status.lower() == 'reject':
            reason = str(item.get('reason') or '').strip()
            summary['rejects'][reason] = summary['rejects'].get(reason, 0) + total
            summary['totalReject'] += total
    summary['totalTransferred'] = summary['stockyard'] + summary['totalReject']
    return summary


def _preview_update_date(record):
    timestamps = [row.get('RejectDateTime') for row in record.get('RejectRows', [])
                   if int(row.get('Qty') or 0) > 0 and row.get('RejectDateTime')]
    if not timestamps or not record.get('ProdDate'):
        return None
    timestamp = max(timestamps)
    if isinstance(timestamp, datetime):
        return f'{day(record["ProdDate"]).isoformat()}T{timestamp:%H:%M}'
    return None


def build_change_status_preview(record, output_summary):
    readiness = reject_readiness(record)
    if not readiness['ready']:
        raise ValueError('NOT READY: ' + '; '.join(readiness['missing']))
    output_detail_id = output_summary.get('curingOutputDetailId')
    update_date = _preview_update_date(record)
    change_to = []
    for reason_code, quantity in record['PositiveRejects'].items():
        if quantity > 0:
            change_to.append(dict(machine=record['Machine'], quantity=quantity,
                                  reasonCode=reason_code, remark='', Shift=str(record['Shift']),
                                  status='Reject', updateDate=update_date))
    return dict(plant=record['Plant'], fromOutputDetailId=output_detail_id,
                changeTo=change_to,
                outputSummary=output_summary,
                unresolved=(["fromOutputDetailId (no curing OutputDetail found)"]
                             if not output_detail_id else []))


def read_reject_records(cursor, production_date):
    cursor.execute("""SELECT p.ProductionID,p.ProdDate,p.Shift,p.MaterialCode,
        p.MaterialName,p.LotNo,p.ProductFamily,p.ProductCode,p.PlanName,p.PlanQty,
        d.CounterQty,d.CuringQty
        FROM dbo.ProductionLot p
        LEFT JOIN dbo.ProductionData d ON d.ProductionID=p.ProductionID
        WHERE p.IsActive=1 AND p.ProdDate=? ORDER BY p.ProductionID""", production_date)
    records = rows(cursor)
    if not records:
        return []
    cursor.execute("""SELECT Company,Plant,Machine,PlanWeek,VersionNo,PlanName,
        Shift,StartTime,MaterialCode,PlanCount,OperationCode
        FROM dbo.P_ActivePlan
        WHERE Company=? AND Plant=? AND Machine=? AND StartTime=?""",
        'CRTC', '30A1', 'SB2-3', production_date)
    plans = rows(cursor)
    ids = [record['ProductionID'] for record in records]
    placeholders = ','.join('?' for _ in ids)
    cursor.execute(f"""SELECT ProductionID,ReasonCode,Qty,RejectDateTime
        FROM dbo.WetReject WHERE ProductionID IN ({placeholders})
        ORDER BY ProductionID,WetRejectID""", *ids)
    rejects = {}
    for reject in rows(cursor):
        rejects.setdefault(reject['ProductionID'], []).append(reject)
    result = []
    for record in records:
        record.update(resolve_plan(record, plans))
        record.update(calculate(record['CounterQty'], record['CuringQty']))
        record['RejectRows'] = rejects.get(record['ProductionID'], [])
        result.append(record)
    return result


def reject_readiness(record):
    missing = []
    for label, key in (
        ('ProductionID', 'ProductionID'), ('Production Date', 'ProdDate'),
        ('Shift', 'Shift'), ('Lot No.', 'LotNo'), ('Material Code', 'MaterialCode'),
        ('Plant', 'Plant'), ('Machine', 'Machine'), ('CounterQty', 'CounterQty'),
        ('CuringQty', 'CuringQty')):
        if record.get(key) is None or record.get(key) == '':
            missing.append(label)
    positive_rejects = {}
    for row in record.get('RejectRows', []):
        quantity = int(row.get('Qty') or 0)
        if quantity > 0:
            positive_rejects[row['ReasonCode']] = positive_rejects.get(row['ReasonCode'], 0) + quantity
    unsupported = sorted(code for code in positive_rejects if code not in CB_SUPPORTED_REASONS)
    if unsupported:
        missing.append('Unsupported Reject Code ' + ', '.join(unsupported))
    recorded_total = sum(positive_rejects.values())
    record['RecordedRejectTotal'] = recorded_total
    if recorded_total <= 0:
        missing.append('Recorded Wet Reject must be greater than 0')
    expected_total = None
    if record.get('CounterQty') is not None and record.get('CuringQty') is not None:
        expected_total = record['CounterQty'] - record['CuringQty']
        if expected_total != recorded_total:
            missing.append(f'Reject total mismatch: expected {expected_total}, recorded {recorded_total}')
    record['ExpectedRejectTotal'] = expected_total
    record['PositiveRejects'] = positive_rejects
    record['RejectReadiness'] = dict(ready=not missing, missing=missing)
    return record['RejectReadiness']


def build_reject_preview(record):
    readiness = reject_readiness(record)
    if not readiness['ready']:
        raise ValueError('NOT READY: ' + '; '.join(readiness['missing']))
    change_to = []
    for reason_code, quantity in record['PositiveRejects'].items():
        change_to.append(dict(machine=record['Machine'], quantity=quantity,
                              reasonCode=reason_code, remark='', Shift=str(record['Shift']),
                              status='Reject', updateDate=None))
    return dict(
        plant=record['Plant'], fromOutputDetailId=None, changeTo=change_to,
        unresolved=['fromOutputDetailId (requires GET /api/v2/OutputDetails)',
                    'changeTo[].updateDate (CB maps DateDepallet + PIS reject dt)'],
    )


def preview_json(record):
    return json.dumps(build_reject_preview(record), ensure_ascii=False, indent=2)
