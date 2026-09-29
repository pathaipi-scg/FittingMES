"""REJECT preflight and controlled SINGLE ChangeStatus orchestration."""

import json
import threading
from datetime import datetime
from uuid import uuid4

from app.pis_client import PISClient, PISClientError
from app.pis_send_log import RESULT_ERROR, RESULT_SKIP, audit_row, insert_audit_rows
from app.reject_api import evaluate_reject_send, reject_batch_summary
from app.reject_pis_log import has_success, insert_attempts


_SEND_LOCKS = {}
_SEND_LOCKS_GUARD = threading.Lock()


def _lot_lock(production_id):
    with _SEND_LOCKS_GUARD:
        return _SEND_LOCKS.setdefault(production_id, threading.Lock())


def _business_success(response):
    if not isinstance(response, dict) or not isinstance(response.get('body'), str):
        raise ValueError('PIS response is malformed.')
    try:
        body = json.loads(response['body'])
    except (TypeError, json.JSONDecodeError):
        raise ValueError('PIS response is not valid JSON.') from None
    return (isinstance(body, dict) and isinstance(body.get('message'), str)
            and body['message'].strip().lower() == 'success')


def _snapshot(preview):
    return dict(OutputDetailId=preview.get('PISOutputDetailId'), LocalCuring=preview.get('LocalCuring'),
                LocalGood=preview.get('LocalGood'), LocalReject=preview.get('LocalRejectTotal'),
                OriginalQty=preview.get('OriginalQty'), PISGood=preview.get('PISGood'),
                PISReject=preview.get('PISReject'), PISTransferred=preview.get('PISTransferred'),
                PISAvailable=preview.get('PISAvailable'), SendGood=preview.get('SendGood'),
                SendReject=preview.get('SendReject'), SendTotal=preview.get('SendTotal'))


def send_reject_single(conn, record, output_details_loader, cumulative_loader, *, config=None,
                       client=None, duplicate_checker=None):
    """Reload, preflight, serialize, POST, and persist one REJECT lot."""
    batch_run_id = uuid4()
    if config is None:
        from app.pis_config import PISConfig
        config = PISConfig.from_environment()
    if not config.reject_send_enabled:
        return dict(lot_no=record.get('LotNo'), status='ERROR', result=RESULT_ERROR,
                    reason='REJECT SEND DISABLED', preview=None, batch_run_id=batch_run_id)
    lock = _lot_lock(record.get('ProductionID'))
    with lock:
        try:
            readiness = record.get('RejectReadiness') or {}
            if not readiness.get('ready'):
                return dict(lot_no=record.get('LotNo'), status='NOT_READY', result=RESULT_SKIP,
                            reason='NOT_READY: ' + '; '.join(readiness.get('missing', [])),
                            preview=None, batch_run_id=batch_run_id)
            summary = output_details_loader(record)
            cumulative = cumulative_loader(record)
            if duplicate_checker is None:
                duplicate_checker = lambda item, _summary, _row: has_success(conn.cursor(), item['ProductionID'])
            preview = evaluate_reject_send(record, summary, cumulative,
                                           duplicate=duplicate_checker(record, summary, cumulative))
            if preview['Status'] != 'READY':
                return dict(lot_no=record.get('LotNo'), status=preview['Status'], result=RESULT_SKIP,
                            reason=preview['Status'], preview=preview, batch_run_id=batch_run_id)
            payload = preview['changeStatusPayload']
            request_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
            response = (client or PISClient(config)).post_change_status(payload)
            success = _business_success(response)
            status_code = response.get('status_code') if isinstance(response, dict) else None
            response_text = response.get('body') if isinstance(response, dict) else None
            outcome = 'SUCCESS' if success else 'FAILED'
            reason = 'SUCCESS' if success else 'API ERROR'
            result = RESULT_ERROR if not success else 'SUCCESS'
        except (PISClientError, TimeoutError, ConnectionError) as exc:
            outcome, reason, result, status_code, response_text = 'FAILED', type(exc).__name__, RESULT_ERROR, None, None
            response = None
        except Exception as exc:
            outcome, reason, result, status_code, response_text = 'FAILED', f'{type(exc).__name__}: {exc}', RESULT_ERROR, None, None
            response = None
        preview = locals().get('preview')
        payload = locals().get('payload')
        snapshot = _snapshot(preview or {})
        attempt = dict(ProductionID=record.get('ProductionID'), LotNo=record.get('LotNo'),
                       ProductionDate=record.get('ProdDate'), RequestGroupID=batch_run_id,
                       FromOutputDetailID=snapshot['OutputDetailId'], RequestJSON=locals().get('request_json'),
                       HTTPStatus=locals().get('status_code'), ResponseText=locals().get('response_text'),
                       Outcome=locals().get('outcome', 'FAILED'), ErrorMessage=None if result == 'SUCCESS' else reason,
                       AttemptedAt=datetime.utcnow())
        audit = audit_row(batch_run_id, 'REJECT', 'SINGLE', record.get('LotNo'), result,
                          reason, send_date=record.get('ProdDate'), PlantCode=record.get('Plant'),
                          MachineCode=record.get('Machine'), ShiftID=record.get('Shift'),
                          ServerMessage=reason, RequestJson=locals().get('request_json'),
                          ResponseJson=locals().get('response_text'), **snapshot)
        try:
            insert_attempts(conn, [attempt])
            insert_audit_rows(conn, [audit])
            conn.commit()
        except Exception as exc:
            if result == 'SUCCESS':
                return dict(lot_no=record.get('LotNo'), status='ERROR', result=RESULT_ERROR,
                            reason=f'AUDIT PERSISTENCE FAILED: {exc}', preview=preview,
                            batch_run_id=batch_run_id, pis_may_have_succeeded=True)
            return dict(lot_no=record.get('LotNo'), status='ERROR', result=RESULT_ERROR,
                        reason=f'AUDIT PERSISTENCE FAILED: {exc}', preview=preview,
                        batch_run_id=batch_run_id)
        return dict(lot_no=record.get('LotNo'), status=('SUCCESS' if result == 'SUCCESS' else 'ERROR'),
                    result=result, reason=reason, preview=preview, batch_run_id=batch_run_id,
                    response=response)


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
