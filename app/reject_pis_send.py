"""REJECT pre-POST orchestration; ChangeStatus is intentionally disabled."""

from uuid import uuid4

from app.pis_send_log import RESULT_ERROR, RESULT_SKIP, audit_row, insert_audit_rows
from app.reject_api import evaluate_reject_send, reject_batch_summary
from app.reject_pis_log import has_success


def _error_result(record, reason):
    return dict(lot_no=record.get('LotNo'), status='ERROR', result=RESULT_ERROR,
                reason=str(reason), preview=None)


def evaluate_reject_lots(conn, records, output_details_loader, cumulative_loader, *,
                         send_mode='BATCH', batch_run_id=None, duplicate_checker=None):
    """Evaluate lots independently and stop before any ChangeStatus request."""
    batch_run_id = batch_run_id or uuid4()
    results = []
    audit_rows = []
    if duplicate_checker is None:
        def duplicate_checker(record, summary, cumulative):
            try:
                return has_success(conn.cursor(), record['ProductionID'])
            except (AttributeError, KeyError):
                return False
    for record in records:
        lot_no = str(record.get('LotNo') or '').strip()
        try:
            readiness = record.get('RejectReadiness') or {}
            if not readiness.get('ready'):
                reason = 'NOT_READY: ' + '; '.join(readiness.get('missing', []))
                result = dict(lot_no=lot_no, status=reason, result=RESULT_SKIP, reason=reason, preview=None)
            else:
                output_details = output_details_loader(record)
                if not isinstance(output_details, dict) or 'curingRemaining' not in output_details:
                    raise ValueError('OutputDetails response is malformed.')
                summary = output_details
                cumulative = cumulative_loader(record)
                duplicate = duplicate_checker(record, summary, cumulative) if duplicate_checker else False
                preview = evaluate_reject_send(record, summary, cumulative, duplicate=duplicate)
                result = dict(lot_no=lot_no, status=preview['Status'],
                              result=(RESULT_SKIP if preview['Status'] != 'READY' else 'READY'),
                              reason=preview['Status'], preview=preview)
        except Exception as exc:
            result = _error_result(record, f'{type(exc).__name__}: {exc}')
        results.append(result)
        if result['result'] in (RESULT_SKIP, RESULT_ERROR):
            audit_rows.append(audit_row(
                batch_run_id, 'REJECT', send_mode, lot_no, result['result'], result['reason'],
                send_date=record.get('ProdDate'), PlantCode=record.get('Plant'),
                MachineCode=record.get('Machine'), ShiftID=record.get('Shift'),
                OutputDetailId=(result.get('preview') or {}).get('PISOutputDetailId'),
                LocalCuring=(result.get('preview') or {}).get('LocalCuring'),
                LocalGood=(result.get('preview') or {}).get('LocalGood'),
                LocalReject=(result.get('preview') or {}).get('LocalRejectTotal'),
                OriginalQty=(result.get('preview') or {}).get('OriginalQty'),
                PISGood=(result.get('preview') or {}).get('PISGood'),
                PISReject=(result.get('preview') or {}).get('PISReject'),
                PISTransferred=(result.get('preview') or {}).get('PISTransferred'),
                PISAvailable=(result.get('preview') or {}).get('PISAvailable'),
                SendGood=(result.get('preview') or {}).get('SendGood'),
                SendReject=(result.get('preview') or {}).get('SendReject'),
                SendTotal=(result.get('preview') or {}).get('SendTotal'),
                ServerMessage=result['reason']))
    if audit_rows:
        insert_audit_rows(conn, audit_rows)
        conn.commit()
    summary = reject_batch_summary(results)
    summary['batch_run_id'] = batch_run_id
    return summary


def evaluate_reject_single(conn, record, output_details_loader, cumulative_loader, *,
                           duplicate_checker=None):
    return evaluate_reject_lots(conn, [record], output_details_loader, cumulative_loader,
                                send_mode='SINGLE', batch_run_id=uuid4(),
                                duplicate_checker=duplicate_checker)['results'][0]
