import unittest
from datetime import datetime
from unittest.mock import patch
from uuid import UUID

from app.reject_api import REJECT_SKIP_REASONS, evaluate_reject_send
from app.pis_config import PISConfig
from app.reject_pis_send import evaluate_reject_lots, send_reject_single


class AuditConnection:
    def __init__(self):
        self.rows = []
        self.attempts = []
        self.commits = 0

    def cursor(self):
        return self

    def execute(self, sql, *args):
        if 'PIS_Send_Log' in sql:
            self.rows.append(args)
        elif 'RejectPISLog' in sql:
            self.attempts.append(args)

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

    def test_empty_outputdetails_is_no_output_details_skip(self):
        result = evaluate_reject_lots(AuditConnection(), [self.record],
                                       lambda record: [], lambda record: self.row)
        self.assertEqual(result['results'][0]['result'], 'SKIP')
        self.assertEqual(result['results'][0]['reason'], 'NO_OUTPUT_DETAILS')

    def test_malformed_outputdetails_is_error(self):
        result = evaluate_reject_lots(AuditConnection(), [self.record],
                                      lambda record: {'unexpected': True}, lambda record: self.row)
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

    def test_disabled_single_never_calls_client(self):
        class Client:
            def post_change_status(self, payload):
                raise AssertionError('POST must not be called')
        result = send_reject_single(AuditConnection(), self.record,
                                    lambda item: self.summary, lambda item: self.row,
                                    config=PISConfig('https://pis.example:443', 'u', 'p'), client=Client())
        self.assertEqual(result['reason'], 'REJECT SEND DISABLED')

    def test_ready_success_posts_exact_evaluator_payload_and_audits(self):
        class Client:
            def __init__(self):
                self.payload = None
            def post_change_status(self, payload):
                self.payload = payload
                return {'status_code': 200, 'body': '{"message":"success"}'}
        client = Client()
        connection = AuditConnection()
        expected = evaluate_reject_send(self.record, self.summary, self.row)['changeStatusPayload']
        result = send_reject_single(connection, self.record, lambda item: self.summary,
                                     lambda item: self.row,
                                     config=PISConfig('https://pis.example:443', 'u', 'p', reject_send_enabled=True),
                                     client=client, duplicate_checker=lambda *args: False)
        self.assertEqual(client.payload, expected)
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(connection.attempts[0][8], 'SUCCESS')
        self.assertEqual(connection.rows[0][5:7], ('SUCCESS', 'SUCCESS'))

    def test_business_failure_is_error_without_credentials_in_audit(self):
        class Client:
            def post_change_status(self, payload):
                return {'status_code': 200, 'body': '{"message":"failed"}'}
        connection = AuditConnection()
        result = send_reject_single(connection, self.record, lambda item: self.summary,
                                     lambda item: self.row,
                                     config=PISConfig('https://pis.example:443', 'secret-user', 'secret-pass', reject_send_enabled=True),
                                     client=Client(), duplicate_checker=lambda *args: False)
        self.assertEqual(result['status'], 'ERROR')
        self.assertEqual(connection.attempts[0][8], 'FAILED')
        self.assertEqual(connection.rows[0][5:7], ('ERROR', 'API ERROR'))
        self.assertNotIn('secret-user', repr(connection.rows))
        self.assertNotIn('secret-pass', repr(connection.rows))

    def test_non_reference_success_fields_are_not_success(self):
        from app.reject_pis_send import _business_success
        for body in ('{"retmsgDB":"SUCCESS"}', '{"success":true}',
                     '{"status":"SUCCESS"}', '{"message":"OK"}'):
            with self.subTest(body=body):
                self.assertFalse(_business_success({'body': body}))

    def test_api_failures_and_malformed_responses_are_errors(self):
        class Client:
            def __init__(self, failure): self.failure = failure
            def post_change_status(self, payload):
                if isinstance(self.failure, BaseException): raise self.failure
                return self.failure
        for failure in (TimeoutError('timeout'), ConnectionError('connection'),
                        RuntimeError('http failure'), {'status_code': 200, 'body': 'not json'}):
            with self.subTest(failure=type(failure).__name__):
                result = send_reject_single(AuditConnection(), self.record,
                    lambda item: self.summary, lambda item: self.row,
                    config=PISConfig('https://pis.example:443', 'u', 'p', reject_send_enabled=True),
                    client=Client(failure), duplicate_checker=lambda *args: False)
                self.assertEqual(result['status'], 'ERROR')

    def test_skip_duplicate_and_stale_ready_never_post(self):
        class Client:
            calls = 0
            def post_change_status(self, payload): self.calls += 1
        for record, summary, row, duplicate in (
                (dict(self.record, RejectReadiness={'ready': False, 'missing': ['Machine']}), self.summary, self.row, False),
                (self.record, self.summary, self.row, True),
                (self.record, dict(self.summary, curingRemaining=4), self.row, False)):
            client = Client()
            result = send_reject_single(AuditConnection(), record, lambda item: summary,
                lambda item: row, config=PISConfig('https://pis.example:443', 'u', 'p', reject_send_enabled=True),
                client=client, duplicate_checker=lambda *args, value=duplicate: value)
            self.assertIn(result['result'], ('SKIP', 'ERROR'))
            self.assertEqual(client.calls, 0)

    def test_persistence_failure_after_success_does_not_repost(self):
        class Connection(AuditConnection):
            def commit(self): raise RuntimeError('database unavailable')
        class Client:
            calls = 0
            def post_change_status(self, payload):
                self.calls += 1
                return {'status_code': 200, 'body': '{"message":"success"}'}
        client = Client()
        result = send_reject_single(Connection(), self.record, lambda item: self.summary,
            lambda item: self.row, config=PISConfig('https://pis.example:443', 'u', 'p', reject_send_enabled=True),
            client=client, duplicate_checker=lambda *args: False)
        self.assertEqual(client.calls, 1)
        self.assertTrue(result['pis_may_have_succeeded'])
        self.assertEqual(result['status'], 'ERROR')

    def test_serialized_duplicate_attempts_allow_at_most_one_post(self):
        state = {'sent': False}
        class Client:
            calls = 0
            def post_change_status(self, payload):
                self.calls += 1
                state['sent'] = True
                return {'status_code': 200, 'body': '{"message":"success"}'}
        client = Client()
        checker = lambda *args: state['sent']
        config = PISConfig('https://pis.example:443', 'u', 'p', reject_send_enabled=True)
        first = send_reject_single(AuditConnection(), self.record, lambda item: self.summary,
            lambda item: self.row, config=config, client=client, duplicate_checker=checker)
        second = send_reject_single(AuditConnection(), self.record, lambda item: self.summary,
            lambda item: self.row, config=config, client=client, duplicate_checker=checker)
        self.assertEqual(client.calls, 1)
        self.assertEqual(first['status'], 'SUCCESS')
        self.assertEqual(second['result'], 'SKIP')

    def test_feature_switch_only_explicit_true_enables(self):
        for value in (None, '', 'invalid'):
            environment = {} if value is None else {'PIS_REJECT_SEND_ENABLED': value}
            with patch.dict('os.environ', environment, clear=True):
                from app.pis_config import PISConfig
                self.assertFalse(PISConfig.from_environment().reject_send_enabled)
        for value in ('true', '1', 'yes', 'on'):
            with patch.dict('os.environ', {'PIS_REJECT_SEND_ENABLED': value}, clear=True):
                from app.pis_config import PISConfig
                self.assertTrue(PISConfig.from_environment().reject_send_enabled)


if __name__ == '__main__':
    unittest.main()
