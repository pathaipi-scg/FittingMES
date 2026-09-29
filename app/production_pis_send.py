"""Dry-testable Production API send orchestration.

This module is intentionally not connected to an application route. Callers must
explicitly provide a PISClient and a database connection.
"""
import json
from datetime import datetime
from uuid import uuid4

from fastapi.encoders import jsonable_encoder

from app.pis_client import PISClientError
from app.prod_api import build_pis_prodorders_payload, group_key, lot_readiness
from app.production_pis_log import has_success, insert_attempts, latest_state
from app.pis_send_log import (RESULT_ERROR, RESULT_SKIP, RESULT_SUCCESS,
                               audit_row, insert_audit_rows)


SUCCESS = 'SUCCESS'
FAILED = 'FAILED'
UNKNOWN = 'UNKNOWN'


def classify_response(status_code=None, body=None, error=None):
    if error is not None:
        if str(error) == 'PIS returned an unsuccessful HTTP status.':
            return FAILED
        return UNKNOWN
    if status_code is None or not 200 <= status_code < 300:
        return FAILED if status_code is not None else UNKNOWN
    try:
        data = json.loads(body) if isinstance(body, str) else body
    except (TypeError, ValueError):
        return UNKNOWN
    if not isinstance(data, dict):
        return UNKNOWN
    return SUCCESS if str(data.get('message', '')).lower() == 'success' else FAILED


def _group_records(records):
    groups = {}
    for record in records:
        groups.setdefault(group_key(record), []).append(record)
    return groups


def send_ready_groups(conn, records, client, *, include_unknown=False, production_ids=None,
                       attempted_at=None, audit_batch_id=None, audit_mode='BATCH'):
    """Send eligible groups through a supplied client; never retries automatically."""
    selected = [record for record in records if lot_readiness(record)['ready']]
    if production_ids is not None:
        selected = [record for record in selected if record['ProductionID'] in set(production_ids)]
    cursor = conn.cursor()
    eligible = []
    skipped = []
    for record in selected:
        if has_success(cursor, record['ProductionID']):
            skipped.append((record, 'ALREADY_SENT'))
            continue
        state = latest_state(cursor, record['ProductionID'])
        if state and state['Outcome'] == UNKNOWN and not include_unknown:
            skipped.append((record, 'UNKNOWN_NOT_RETRIED'))
            continue
        eligible.append(record)

    results = []
    attempted_at = attempted_at or datetime.now()
    for key, group_records in _group_records(eligible).items():
        request_group_id = uuid4()
        payload = build_pis_prodorders_payload(group_records)
        request_json = json.dumps(jsonable_encoder(payload), ensure_ascii=False,
                                  allow_nan=False, separators=(',', ':'))
        status_code = None
        response_text = None
        error_message = None
        try:
            response = client.post_prodorders(payload)
            status_code = response.get('status_code')
            response_text = response.get('body')
            outcome = classify_response(status_code, response_text)
        except PISClientError as exc:
            error_message = str(exc)
            outcome = classify_response(error=exc)
        except Exception as exc:
            error_message = 'PIS request failed.'
            outcome = classify_response(error=exc)

        attempts = [{
            'ProductionID': record['ProductionID'],
            'LotNo': record['LotNo'],
            'ProductionDate': record['ProdDate'],
            'ShiftCode': record.get('Shift'),
            'PlantCode': record.get('Plant'),
            'MachineCode': record.get('Machine'),
            'RequestGroupID': request_group_id,
            'RequestJSON': request_json,
            'HTTPStatus': status_code,
            'ResponseText': response_text,
            'Outcome': outcome,
            'ErrorMessage': error_message,
            'AttemptedAt': attempted_at,
        } for record in group_records]
        try:
            insert_attempts(conn, attempts)
            if audit_batch_id is not None:
                audit_result = (RESULT_SUCCESS if outcome == SUCCESS else RESULT_ERROR)
                insert_audit_rows(conn, [audit_row(
                    audit_batch_id, 'PROD', audit_mode, record['LotNo'], audit_result,
                    None if audit_result == RESULT_SUCCESS else (
                        'API_NON_SUCCESS_RESPONSE' if outcome == FAILED else 'TRANSPORT_FAILURE'),
                    send_date=record['ProdDate'], PlantCode=record.get('Plant'),
                    MachineCode=record.get('Machine'), ShiftID=record.get('Shift'),
                    ServerMessage=error_message, RequestJson=request_json,
                    ResponseJson=response_text) for record in group_records])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        results.append(dict(request_group_id=request_group_id, group_key=key,
                            production_ids=[r['ProductionID'] for r in group_records],
                            outcome=outcome, http_status=status_code))
    if audit_batch_id is not None:
        skipped_rows = []
        for record, reason in skipped:
            skipped_rows.append(audit_row(
                audit_batch_id, 'PROD', audit_mode, record['LotNo'], RESULT_SKIP, reason,
                send_date=record['ProdDate'], PlantCode=record.get('Plant'),
                MachineCode=record.get('Machine'), ShiftID=record.get('Shift')))
        if skipped_rows:
            insert_audit_rows(conn, skipped_rows)
            conn.commit()
    return results
