import inspect
import unittest
from datetime import date, datetime

from app.logger_summary import read_logger_time_summary, read_logger_press_guide
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
    def test_f_machine_mapping_uses_matching_instance_and_active_master_count(self):
        for equipment_code, instance_no in (('F1', 1), ('F2', 2)):
            cursor = GuideCursor()
            result = read_logger_press_guide(cursor, date(2026, 10, 1), equipment_code)
            self.assertTrue(result['HasSetup'])
            guide_query = next(query for query, _ in cursor.calls if 'FROM dbo.LoggerEvent' in query)
            self.assertIn('event.McId=? AND event.McInstanceNo=?', guide_query)
            self.assertEqual(cursor.guide_params[10:13], (date(2026, 10, 1), 7, instance_no))

    def test_f_machine_mapping_rejects_instance_above_active_master_count(self):
        cursor = GuideCursor(instance_count=2)
        result = read_logger_press_guide(cursor, date(2026, 10, 1), 'F3')
        self.assertFalse(result['HasSetup'])
        self.assertFalse(any('FROM dbo.LoggerEvent' in query for query, _ in cursor.calls))

    def test_guide_query_keeps_primary_machine_ownership_for_related_events(self):
        cursor = GuideCursor()
        read_logger_press_guide(cursor, date(2026, 10, 1), 'F1')
        guide_query = next(query for query, _ in cursor.calls if 'FROM dbo.LoggerEvent' in query)
        self.assertIn('event.McId=?', guide_query)
        self.assertNotIn('RelatedMachineSnapshot', guide_query)

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


class GuideCursor:
    def __init__(self, instance_count=14):
        self.instance_count = instance_count
        self.calls = []
        self.result = []
        self.guide_params = ()

    def execute(self, query, *params):
        self.calls.append((query, params))
        if 'FROM dbo.Fitting_MainMachine' in query:
            self.result = [(7, self.instance_count)]
        elif 'FROM dbo.Fitting_StopType' in query:
            self.result = [(2, 'SETUP'), (3, 'CHGOVER'), (5, 'CLEAN'),
                           (6, 'SMDT'), (7, 'BD')]
        elif 'FROM dbo.LoggerEvent' in query:
            self.guide_params = params
            self.result = [(10, 5, 8, 370, 16, 1, 1, 1, 1, 1)]
        else:
            raise AssertionError(query)

    def fetchall(self):
        result, self.result = self.result, []
        return result

    def fetchone(self):
        result, self.result = (self.result[0] if self.result else None), []
        return result


if __name__ == '__main__':
    unittest.main()