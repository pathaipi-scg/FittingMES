"""Append-only audit writes for the unified PIS send log."""

from datetime import date
from uuid import UUID


RESULT_SUCCESS = 'SUCCESS'
RESULT_SKIP = 'SKIP'
RESULT_ERROR = 'ERROR'


def insert_audit_rows(conn, rows):
    """Insert audit rows without deciding whether a PIS request is eligible."""
    rows = list(rows)
    if not rows:
        return
    cursor = conn.cursor()
    for row in rows:
        cursor.execute("""
            INSERT INTO dbo.PIS_Send_Log
                (BatchRunId, SendType, SendMode, SendDate, LotNo, Result, Reason,
                 PlantCode, MachineCode, ShiftID, ServerMessage, RequestJson, ResponseJson)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, row['BatchRunId'], row['SendType'], row['SendMode'], row.get('SendDate'),
        row['LotNo'], row['Result'], row.get('Reason'), row.get('PlantCode'),
        row.get('MachineCode'), row.get('ShiftID'), row.get('ServerMessage'),
        row.get('RequestJson'), row.get('ResponseJson'))


def audit_row(batch_run_id, send_type, send_mode, lot_no, result, reason, *,
              send_date=None, **details):
    if not isinstance(batch_run_id, UUID):
        raise ValueError('batch_run_id must be a UUID')
    if result not in {RESULT_SUCCESS, RESULT_SKIP, RESULT_ERROR}:
        raise ValueError('Unsupported unified PIS audit result')
    return dict(BatchRunId=batch_run_id, SendType=send_type, SendMode=send_mode,
                SendDate=send_date, LotNo=str(lot_no or '').strip(), Result=result,
                Reason=reason, **details)
