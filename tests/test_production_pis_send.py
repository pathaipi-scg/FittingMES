import json
import unittest
from datetime import datetime
from unittest.mock import Mock

from app.production_pis_send import (FAILED, SUCCESS, UNKNOWN, classify_response,
                                     send_ready_groups)
from test_prod_api import DAY, PLAN_SOURCE, RECORD
from app.prod_api import resolve_plan


class HistoryConnection:
    def __init__(self, states=None):
        self.states = dict(states or {})
        self.attempts = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return HistoryCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class HistoryCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = []
        self.result = []

    def execute(self, sql, *args):
        if sql.startswith('SELECT 1'):
            self.result = [(1,)] if args[0] in self.connection.states and self.connection.states[args[0]]['Outcome'] == SUCCESS else []
            self.description = [('value',)]
        elif sql.startswith('SELECT TOP'):
            state = self.connection.states.get(args[0])
            self.result = [tuple(state.values())] if state else []
            self.description = [(key,) for key in state] if state else []
        elif 'FROM Ranked' in sql:
            self.result = []
            self.description = [('PISLogID',), ('ProductionID',), ('LotNo',), ('ProductionDate',),
                                ('ShiftCode',), ('PlantCode',), ('MachineCode',), ('RequestGroupID',),
                                ('HTTPStatus',), ('Outcome',), ('ErrorMessage',), ('AttemptedAt',), ('CreatedAt',)]
        elif sql.startswith('INSERT INTO'):
            values = args
            self.connection.attempts.append(values)
        else:
            raise AssertionError(sql)
        return self

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return self.result


class ProductionSendTests(unittest.TestCase):
    def records(self):
        base = dict(RECORD, **resolve_plan(RECORD, [PLAN_SOURCE]))
        return [base, dict(base, ProductionID=3, LotNo='OTHER', Shift='2'),
                dict(base, ProductionID=4, LotNo='THIRD', Shift='1', Machine='OTHER')]

    def test_classification(self):
        self.assertEqual(classify_response(200, '{"message":"SUCCESS"}'), SUCCESS)
        self.assertEqual(classify_response(500, '{"message":"success"}'), FAILED)
        self.assertEqual(classify_response(200, '{"message":"rejected"}'), FAILED)
        self.assertEqual(classify_response(200, 'not-json'), UNKNOWN)
        self.assertEqual(classify_response(error=TimeoutError()), UNKNOWN)

    def test_group_attempts_share_ids_and_failure_does_not_stop_other_group(self):
        conn = HistoryConnection()
        client = Mock()
        client.post_prodorders.side_effect = [
            {'status_code': 500, 'body': '{"message":"failed"}'},
            {'status_code': 200, 'body': '{"message":"success"}'},
            {'status_code': 200, 'body': '{"message":"success"}'},
        ]
        results = send_ready_groups(conn, self.records(), client, attempted_at=datetime(2026, 9, 29))
        self.assertEqual(len(results), 3)
        self.assertEqual(len(conn.attempts), 3)
        self.assertEqual(len({attempt[6] for attempt in conn.attempts}), 3)
        self.assertEqual([result['outcome'] for result in results], [FAILED, SUCCESS, SUCCESS])
        self.assertTrue(all('password' not in attempt[7].lower() and 'authorization' not in attempt[7].lower()
                            for attempt in conn.attempts))

    def test_success_is_excluded_failed_retryable_unknown_requires_explicit_retry(self):
        conn = HistoryConnection({
            2: {'PISLogID': 1, 'ProductionID': 2, 'LotNo': 'A', 'ProductionDate': DAY,
                'ShiftCode': '1', 'PlantCode': '30A1', 'MachineCode': 'SB2-3', 'RequestGroupID': 'g',
                'HTTPStatus': 200, 'Outcome': SUCCESS, 'ErrorMessage': None, 'AttemptedAt': None, 'CreatedAt': None},
            3: {'PISLogID': 2, 'ProductionID': 3, 'LotNo': 'B', 'ProductionDate': DAY,
                'ShiftCode': '2', 'PlantCode': '30A1', 'MachineCode': 'SB2-3', 'RequestGroupID': 'g',
                'HTTPStatus': 500, 'Outcome': FAILED, 'ErrorMessage': None, 'AttemptedAt': None, 'CreatedAt': None},
            4: {'PISLogID': 3, 'ProductionID': 4, 'LotNo': 'C', 'ProductionDate': DAY,
                'ShiftCode': '1', 'PlantCode': '30A1', 'MachineCode': 'OTHER', 'RequestGroupID': 'g',
                'HTTPStatus': None, 'Outcome': UNKNOWN, 'ErrorMessage': 'PIS request failed.', 'AttemptedAt': None, 'CreatedAt': None},
        })
        client = Mock()
        client.post_prodorders.return_value = {'status_code': 200, 'body': '{"message":"success"}'}
        send_ready_groups(conn, self.records(), client)
        self.assertEqual([attempt[0] for attempt in conn.attempts], [3])
        conn.attempts.clear()
        send_ready_groups(conn, self.records(), client, include_unknown=True)
        self.assertEqual([attempt[0] for attempt in conn.attempts], [3, 4])


if __name__ == '__main__':
    unittest.main()
