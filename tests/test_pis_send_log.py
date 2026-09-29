import unittest
from datetime import date
from uuid import uuid4

from app.pis_send_log import audit_row, insert_audit_rows


class AuditConnection:
    def __init__(self):
        self.calls = []

    def cursor(self):
        return self

    def execute(self, sql, *args):
        self.calls.append((sql, args))


class UnifiedAuditTests(unittest.TestCase):
    def test_insert_maps_unified_and_detail_columns_without_network(self):
        connection = AuditConnection()
        batch_id = uuid4()
        row = audit_row(batch_id, 'PROD', 'SINGLE', 'LOT-1', 'SUCCESS', None,
                        send_date=date(2026, 9, 29), PlantCode='30A1',
                        MachineCode='SB2-3', ShiftID='1', ServerMessage='success',
                        RequestJson='{}', ResponseJson='{"message":"success"}')
        insert_audit_rows(connection, [row])
        sql, values = connection.calls[0]
        self.assertIn('INSERT INTO dbo.PIS_Send_Log', sql)
        self.assertEqual(values[:7], (batch_id, 'PROD', 'SINGLE', date(2026, 9, 29),
                                      'LOT-1', 'SUCCESS', None))
        self.assertEqual(values[-2:], ('{}', '{"message":"success"}'))

    def test_result_contract_rejects_unknown_values(self):
        with self.assertRaises(ValueError):
            audit_row(uuid4(), 'PROD', 'BATCH', 'LOT-1', 'FAILED', 'old result')


if __name__ == '__main__':
    unittest.main()
