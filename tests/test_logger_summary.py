import inspect
import unittest
from datetime import date, datetime

from app.logger_summary import read_logger_time_summary
from app.main import app


class SummaryCursor:
    def __init__(self, aggregate, events, overlap=0):
        self.aggregate = aggregate
        self.events = events
        self.overlap = overlap
        self.calls = []
        self.result = []

    def execute(self, query, *params):
        self.calls.append((query, params))
        if 'FROM dbo.Fitting_StopType' in query:
            self.result = [(2, 'SETUP'), (3, 'CHGOVER'), (5, 'CLEAN'),
                           (6, 'SMDT'), (7, 'BD')]
        elif 'GROUP BY event.McId' in query:
            self.result = self.aggregate
        elif 'SELECT event.LoggerEventID' in query:
            self.result = self.events
        elif 'COUNT(*)' in query:
            self.result = [(self.overlap,)]
        else:
            raise AssertionError(query)

    def fetchall(self):
        result, self.result = self.result, []
        return result

    def fetchone(self):
        result, self.result = self.result[0], []
        return result


class LoggerSummaryTests(unittest.TestCase):
    def test_summary_uses_saved_stop_ids_and_keeps_instances_separate(self):
        cursor = SummaryCursor([
            (7, 1, 'F', 10, 5, 12, 20, 5),
            (7, 2, 'F', 0, 0, 4, 0, 0),
        ], [], overlap=0)
        result = read_logger_time_summary(cursor, date(2026, 10, 1))
        self.assertEqual([row['MachineLabel'] for row in result['summary']], ['F1', 'F2'])
        self.assertEqual(result['summary'][0]['TotalLoggedMin'], 52)
        self.assertEqual(result['summary'][1]['TotalLoggedMin'], 4)
        aggregate_call = next(call for call in cursor.calls if 'GROUP BY event.McId' in call[0])
        self.assertEqual(aggregate_call[1][:5], (2, 3, 6, 7, 5))
        self.assertEqual(aggregate_call[1][5], date(2026, 10, 1))
        self.assertEqual(aggregate_call[1][6:], (2, 3, 6, 7, 5))

    def test_idle_is_excluded_and_saved_classification_is_authoritative(self):
        cursor = SummaryCursor([(7, 1, 'F', 10, 0, 5, 20, 3)], [
            (1, 7, 1, datetime(2026, 10, 1, 23, 55), datetime(2026, 10, 2, 0, 5), 5, 6,
             'SMDT', 'CABLE CAR1', None, 'waiting'),
        ])
        result = read_logger_time_summary(cursor, date(2026, 10, 1))
        row = result['summary'][0]
        self.assertEqual((row['SmdtMin'], row['BreakdownMin'], row['TotalLoggedMin']), (5, 20, 38))
        self.assertEqual(result['events'][0]['DurationMin'], 5)
        self.assertEqual(result['events'][0]['StopId'], 6)
        self.assertEqual(result['events'][0]['RelatedMachineSnapshot'], 'CABLE CAR1')

    def test_overlap_warning_is_read_only_and_route_is_get_only(self):
        cursor = SummaryCursor([(7, 1, 'F', 0, 0, 0, 5, 0)], [], overlap=1)
        result = read_logger_time_summary(cursor, date(2026, 10, 1))
        self.assertTrue(result['overlap_warning'])
        self.assertEqual(result['overlap_count'], 1)
        source = inspect.getsource(read_logger_time_summary).upper()
        self.assertFalse(any(word in source for word in ('INSERT ', 'UPDATE ', 'DELETE ', 'MERGE ')))
        paths = {(route.path, tuple(route.methods or ())) for route in app.routes if hasattr(route, 'methods')}
        self.assertIn(('/logger/summary', ('GET',)), paths)


if __name__ == '__main__':
    unittest.main()