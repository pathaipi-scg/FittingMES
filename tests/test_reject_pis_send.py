import unittest
from datetime import datetime
from uuid import UUID

from app.reject_api import REJECT_SKIP_REASONS, evaluate_reject_send
from app.reject_pis_send import evaluate_reject_lots


class AuditConnection:
    def __init__(self):
        self.rows = []
        self.commits = 0

    def cursor(self):
        return self

    def execute(self, sql, *args):
        if 'PIS_Send_Log' in sql:
            self.rows.append(args)

    def commit(self):
        self.commits += 1


class PersistedDuplicateConnection(AuditConnection):
    def fetchone(self):
        return (1,)


class RejectPrePostTests(unittest.TestCase):
    def setUp(self):
        self.record = dict(LotNo='LOT-1', ProdDate='2026-09-29', Plant='30A1', Machine='SB2-3', Shift='1',
                           RejectReadiness={'ready': True, 'missing': []})
        self.summary = dict(originalQty=100, stockyard=0, totalReject=0, totalTransferred=0,
                            curingRemaining=100, curingOutputDetailId='OD-1')
        self.row = dict(CuringCnt=10, ToPackCnt=5, Rej_R01=5, DateDepallet='2026-09-29',
                        dt=datetime(2026, 9, 29, 12, 30), ShiftID='1')

    def test_ready_builds_payload_without_post_success(self):
        result = evaluate_reject_send(self.record, self.summary, self.row)
        self.assertEqual(result['Status'], 'READY')
        self.assertEqual(result['SendTotal'], 10)
        self.assertEqual(result['changeStatusPayload']['fromOutputDetailId'], 'OD-1')

    def test_exact_skip_statuses_reachable_from_node_red_precedence(self):
        cases = [
            ('ALREADY SENT', dict(curingRemaining=0, totalTransferred=100), None, None),
            ('NO PIS CURING BALANCE', dict(curingRemaining=0, totalTransferred=0), None, None),
            ('NO CURING ID', dict(curingOutputDetailId=None), None, None),
            ('NO LOCAL DEPALLET', dict(curingRemaining=100), dict(CuringCnt=0, ToPackCnt=0), None),
            ('GOOD > LOCAL CURING', dict(curingRemaining=100), dict(CuringCnt=10, ToPackCnt=11), None),
            ('LOCAL CURING > ORIGINAL', dict(curingRemaining=100, originalQty=5), None, None),
            ('REJECT REASON > TOTAL REJECT', dict(curingRemaining=100), dict(CuringCnt=10, ToPackCnt=5, Rej_R01=6), None),
            ('PIS REMAIN < LOCAL REJECT', dict(curingRemaining=4), None, None),
            ('MACHINE MISSING', dict(curingRemaining=100), None, dict(Machine='')),
            ('PLANT MISSING', dict(curingRemaining=100), None, dict(Plant='')),
            ('SHIFT MISSING', dict(curingRemaining=100), dict(ShiftID=''), dict(Shift='')),
            ('UPDATE DATE MISSING', dict(curingRemaining=100), dict(dt=None), None),
        ]
        for expected, summary_changes, row_changes, record_changes in cases:
            with self.subTest(expected=expected):
                summary = dict(self.summary, **summary_changes)
                row = dict(self.row, **(row_changes or {}))
                record = dict(self.record, **(record_changes or {}))
                self.assertEqual(evaluate_reject_send(record, summary, row)['Status'], expected)

    def test_duplicate_blocked_is_pre_post_only(self):
        result = evaluate_reject_send(self.record, self.summary, self.row, duplicate=True)
        self.assertEqual(result['Status'], 'DUPLICATE BLOCKED')
        self.assertNotIn('changeStatusPayload', result)

    def test_persisted_reject_success_is_duplicate_blocked(self):
        record = dict(self.record, ProductionID=7)
        result = evaluate_reject_lots(PersistedDuplicateConnection(), [record],
                                      lambda item: self.summary, lambda item: self.row)
        self.assertEqual(result['results'][0]['status'], 'DUPLICATE BLOCKED')
        self.assertEqual(result['skip'], 1)

    def test_outputdetails_api_failure_is_error_and_audited(self):
        connection = AuditConnection()
        result = evaluate_reject_lots(connection, [self.record],
                                       lambda record: (_ for _ in ()).throw(TimeoutError('PIS unavailable')),
                                       lambda record: self.row)
        self.assertEqual(result['error'], 1)
        self.assertEqual(connection.rows[0][5:7], ('ERROR', 'TimeoutError: PIS unavailable'))

    def test_malformed_outputdetails_is_error(self):
        result = evaluate_reject_lots(AuditConnection(), [self.record],
                                       lambda record: [], lambda record: self.row)
        self.assertEqual(result['results'][0]['result'], 'ERROR')

    def test_database_query_failure_continues_batch(self):
        records = [self.record, dict(self.record, LotNo='LOT-2')]
        calls = []
        def cumulative(record):
            calls.append(record['LotNo'])
            if record['LotNo'] == 'LOT-1':
                raise RuntimeError('SQL failure')
            return self.row
        result = evaluate_reject_lots(AuditConnection(), records,
                                      lambda record: self.summary, cumulative)
        self.assertEqual(result['error'], 1)
        self.assertEqual(result['ready'], 1)
        self.assertEqual(calls, ['LOT-1', 'LOT-2'])

    def test_skip_and_error_are_audited_but_ready_is_not_success(self):
        connection = AuditConnection()
        result = evaluate_reject_lots(connection, [self.record,
            dict(self.record, LotNo='LOT-2', RejectReadiness={'ready': False, 'missing':['Machine']})],
            lambda record: self.summary, lambda record: self.row)
        self.assertEqual(result['ready'], 1)
        self.assertEqual([values[5] for values in connection.rows], ['SKIP'])
        self.assertNotIn('SUCCESS', [values[5] for values in connection.rows])

    def test_batch_continues_and_shares_batch_id(self):
        connection = AuditConnection()
        records = [self.record, dict(self.record, LotNo='LOT-2', RejectReadiness={'ready': False, 'missing':['CuringQty']}),
                   dict(self.record, LotNo='LOT-3')]
        calls = []
        def details(record):
            calls.append(record['LotNo'])
            if record['LotNo'] == 'LOT-3':
                raise RuntimeError('OutputDetails unavailable')
            return self.summary
        result = evaluate_reject_lots(connection, records, details, lambda record: self.row)
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['ready'], 1)
        self.assertEqual(result['skip'], 1)
        self.assertEqual(result['error'], 1)
        self.assertEqual(len({values[0] for values in connection.rows}), 1)
        self.assertEqual(calls, ['LOT-1', 'LOT-3'])

    def test_batch_runs_get_distinct_ids_and_no_post_client_exists(self):
        connection = AuditConnection()
        first = evaluate_reject_lots(connection, [self.record], lambda record: self.summary, lambda record: self.row)
        second = evaluate_reject_lots(connection, [self.record], lambda record: self.summary, lambda record: self.row)
        self.assertIsInstance(first['batch_run_id'], UUID)
        self.assertNotEqual(first['batch_run_id'], second['batch_run_id'])
        self.assertNotIn('post_change_status', dir(evaluate_reject_lots))

    def test_reference_reason_set_is_preserved(self):
        self.assertIn('SEND BALANCE ERROR', REJECT_SKIP_REASONS)
        self.assertIn('DUPLICATE BLOCKED', REJECT_SKIP_REASONS)

    def test_r99_balance_cases_match_node_red(self):
        less = evaluate_reject_send(self.record, self.summary,
                                                                        dict(self.row, ToPackCnt=7, Rej_R01=2, Rej_R02=0))
        equal = evaluate_reject_send(self.record, self.summary,
                                                                         dict(self.row, ToPackCnt=7, Rej_R01=3, Rej_R02=0))
        greater = evaluate_reject_send(self.record, self.summary,
                                                                             dict(self.row, ToPackCnt=7, Rej_R01=4, Rej_R02=0))
        self.assertEqual(less['FinalR99'], 1)
        self.assertEqual(equal['FinalR99'], 0)
        self.assertEqual(greater['FinalR99'], 0)
        self.assertNotEqual(greater['Status'], 'READY')


if __name__ == '__main__':
    unittest.main()
