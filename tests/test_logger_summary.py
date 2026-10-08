import inspect
import json
import unittest
from datetime import date, datetime
from unittest.mock import patch

from app.logger_summary import read_logger_time_summary, read_logger_press_guide
from app.main import app, read_press_logger_guide, templates


class SummaryCursor:
    def __init__(self, aggregate, events, overlap=0):
        self.aggregate = aggregate
        self.events = events
        self.overlap = overlap
        self.calls = []
        self.result = []
        self.description = []

    def execute(self, query, *params):
        self.calls.append((query, params))
        if 'FROM dbo.ProductionShiftRuleHistory' in query:
            self.description = [('EffectiveFromDate',), ('ShiftID',), ('StartTime',)]
            self.result = [(date(2026, 1, 1), 1, datetime.min.time().replace(hour=7)),
                           (date(2026, 1, 1), 2, datetime.min.time().replace(hour=19))]
        elif 'FROM dbo.Fitting_StopType' in query:
            self.description = []
            self.result = [(2, 'SETUP'), (3, 'CHGOVER'), (4, 'IDLE'),
                           (5, 'CLEAN'), (6, 'SMDT'), (7, 'BD')]
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
    def test_summary_uses_shared_date_header_and_compact_back_header(self):
        production_date = date(2026, 10, 1)
        body = templates.get_template('logger_summary.html').render(
            page_title='LOGGER TIME SUMMARY',
            active_tab='logger-summary',
            production_date=production_date,
            summary=[dict(MachineLabel='F1', SetupMin=1, ChgOverMin=2,
                          SmdtMin=3, BreakdownMin=4, CleanMin=5,
                          TotalLoggedMin=15,
                          Shift1SetupMin=1, Shift1ChgOverMin=0,
                          Shift1SmdtMin=0, Shift1BreakdownMin=0,
                          Shift1CleanMin=0, Shift2SetupMin=0,
                          Shift2ChgOverMin=0, Shift2SmdtMin=0,
                          Shift2BreakdownMin=0, Shift2CleanMin=0)],
            events=[dict(McId=7, McInstanceNo=1, StopTypeSnapshot='SETUP',
                         DurationMin=1, RelatedMachineSnapshot=None,
                         SubMachineSnapshot=None, CauseSnapshot=None,
                         StopId=2)],
            overlap_warning=False,
            overlap_count=0,
        )
        self.assertIn('action="/logger/summary"', body)
        self.assertIn('name="production_date" type="date" value="2026-10-01"', body)
        self.assertEqual(body.count('type="date"'), 1)
        self.assertIn('>REFRESH</button>', body)
        self.assertIn('href="/logger?production_date=2026-10-01">BACK TO LOGGER</a>', body)
        self.assertIn('href="/logger?production_date=2026-10-01" aria-current="page">LOGGER</a>', body)
        self.assertIn('<th class="logger-summary-group" colspan="6">SHIFT 1</th>', body)
        self.assertIn('<th class="logger-summary-group" colspan="6">SHIFT 2</th>', body)
        self.assertIn('<th class="logger-summary-group" colspan="6">TOTAL</th>', body)
        self.assertEqual(body.count('<th>SETUP</th>'), 3)
        self.assertNotIn('<th>TOTAL</th>', body)
        self.assertNotIn('>VIEW</button>', body)
        self.assertNotIn('Return to LOGGER', body)
        heading_end = body.index('>BACK TO LOGGER</a>')
        description_start = body.index(
            'Calculated from saved LOGGER events - guide values')
        summary_table = body.index('aria-label="LOGGER time summary"')
        self.assertLess(heading_end, description_start)
        self.assertLess(description_start, summary_table)

    def test_f_machine_mapping_uses_matching_instance_and_active_master_count(self):
        for equipment_code, instance_no in (('F1', 1), ('F2', 2)):
            cursor = GuideCursor()
            result = read_logger_press_guide(cursor, date(2026, 10, 1), equipment_code)
            self.assertTrue(result['HasSetup'])
            guide_query = next(query for query, _ in cursor.calls if 'FROM dbo.LoggerEvent' in query)
            self.assertIn('event.McId=? AND event.McInstanceNo=?', guide_query)
            self.assertEqual(cursor.guide_params[:3], (date(2026, 10, 1), 7, instance_no))

    def test_f_machine_mapping_rejects_instance_above_active_master_count(self):
        cursor = GuideCursor(instance_count=2)
        result = read_logger_press_guide(cursor, date(2026, 10, 1), 'F3')
        self.assertFalse(result['HasSetup'])
        self.assertFalse(any('FROM dbo.LoggerEvent' in query for query, _ in cursor.calls))

    def test_guide_isolates_date_press_instance_maps_categories_and_keeps_zero_presence(self):
        production_date = date(2026, 10, 1)
        events = [
            (production_date, 7, 1, 2, 5, datetime(2026, 10, 1, 8), 1),
            (production_date, 7, 1, 3, 7, datetime(2026, 10, 1, 20), 2),
            (production_date, 7, 1, 4, 0, datetime(2026, 10, 1, 21), 2),
            (production_date, 7, 2, 2, 99, datetime(2026, 10, 1, 8), 1),
            (date(2026, 10, 2), 7, 1, 7, 88, datetime(2026, 10, 2, 8), 1),
        ]
        cursor = GuideCursor(events=events)

        guide = read_logger_press_guide(cursor, production_date, 'F1')

        self.assertEqual(guide['shifts']['1']['SETUP'],
                         {'minutes': 5, 'present': True})
        self.assertEqual(guide['shifts']['2']['CHGOVER'],
                         {'minutes': 7, 'present': True})
        self.assertEqual(guide['shifts']['2']['IDLE'],
                         {'minutes': 0, 'present': True})
        self.assertEqual(guide['shifts']['1']['BD'],
                         {'minutes': 0, 'present': False})
        self.assertEqual(cursor.guide_params[:3], (production_date, 7, 1))
        self.assertEqual(events[0][0], production_date)
        self.assertEqual(events[0][2], 1)

    def test_press_guide_route_is_read_only_and_returns_selected_lot_date(self):
        production_date = date(2026, 10, 1)
        events = [(production_date, 7, 1, 2, 5,
                   datetime(2026, 10, 1, 8), 1)]
        cursor = GuideCursor(events=events, assignment=(production_date, 'F1'))

        class Connection:
            def cursor(self):
                return cursor

            def close(self):
                pass

        with patch('app.main.get_connection', return_value=Connection()):
            response = read_press_logger_guide(7, 45)

        payload = json.loads(response.body)
        self.assertEqual(payload['production_date'], production_date.isoformat())
        self.assertEqual(payload['equipment_code'], 'F1')
        self.assertEqual(payload['shifts']['1']['SETUP'],
                         {'minutes': 5, 'present': True})
        self.assertFalse(any(
            any(token in query.upper() for token in
                ('INSERT ', 'UPDATE ', 'DELETE ', 'MERGE '))
            for query, _ in cursor.calls))
        self.assertEqual(events, [(production_date, 7, 1, 2, 5,
                                   datetime(2026, 10, 1, 8), 1)])
        route_methods = {
            tuple(route.methods or ()) for route in app.routes
            if getattr(route, 'path', '') ==
            '/lots/{production_id}/press-production/{press_production_id}/logger-guide'
        }
        self.assertEqual(route_methods, {('GET',)})

    def test_guide_query_keeps_primary_machine_ownership_for_related_events(self):
        cursor = GuideCursor()
        read_logger_press_guide(cursor, date(2026, 10, 1), 'F1')
        guide_query = next(query for query, _ in cursor.calls if 'FROM dbo.LoggerEvent' in query)
        self.assertIn('event.McId=?', guide_query)
        self.assertNotIn('RelatedMachineSnapshot', guide_query)

    def test_summary_uses_saved_stop_ids_and_keeps_instances_separate(self):
        cursor = SummaryCursor([
            (7, 1, 'F', 10, 5, 0, 5, 12, 20),
            (7, 2, 'F', 0, 0, 0, 0, 4, 0),
        ], [], overlap=0)
        result = read_logger_time_summary(cursor, date(2026, 10, 1))
        self.assertEqual([row['MachineLabel'] for row in result['summary']], ['F1', 'F2'])
        self.assertEqual(result['summary'][0]['TotalLoggedMin'], 52)
        self.assertEqual(result['summary'][1]['TotalLoggedMin'], 4)
        aggregate_call = next(call for call in cursor.calls if 'GROUP BY event.McId' in call[0])
        self.assertEqual(aggregate_call[1][:6], (2, 3, 4, 5, 6, 7))
        self.assertEqual(aggregate_call[1][6], date(2026, 10, 1))
        self.assertEqual(aggregate_call[1][7:], (2, 3, 4, 5, 6, 7))

    def test_summary_aggregates_shift_one_shift_two_and_unassigned_total(self):
        cursor = SummaryCursor([
            (7, 1, 'F', 3, 4, 0, 7, 5, 6),
        ], [
            (1, 7, 1, datetime(2026, 10, 1, 8, 0), datetime(2026, 10, 1, 8, 3),
             3, 2, 'SETUP', None, None, None, None),
            (2, 7, 1, datetime(2026, 10, 1, 20, 0), datetime(2026, 10, 1, 20, 4),
             4, 3, 'CHGOVER', None, None, None, None),
            (3, 7, 1, None, None, 5, 6, 'SMDT', None, None, None, None),
            (4, 7, 1, datetime(2026, 10, 1, 8, 30), datetime(2026, 10, 1, 8, 36),
             6, 7, 'BD', None, None, None, 2),
        ], overlap=0)
        result = read_logger_time_summary(cursor, date(2026, 10, 1))
        row = result['summary'][0]
        self.assertEqual(
            [row[field] for field in (
                'Shift1SetupMin', 'Shift1ChgOverMin', 'Shift1IdleMin',
                'Shift1CleanMin', 'Shift1SmdtMin', 'Shift1BreakdownMin')],
            [3, 0, 0, 0, 0, 0])
        self.assertEqual(
            [row[field] for field in (
                'Shift2SetupMin', 'Shift2ChgOverMin', 'Shift2IdleMin',
                'Shift2CleanMin', 'Shift2SmdtMin', 'Shift2BreakdownMin')],
            [0, 4, 0, 0, 0, 6])
        self.assertEqual(
            [row[field] for field in (
                'SetupMin', 'ChgOverMin', 'IdleMin', 'CleanMin',
                'SmdtMin', 'BreakdownMin')],
            [3, 4, 0, 7, 5, 6])

    def test_idle_is_excluded_and_saved_classification_is_authoritative(self):
        cursor = SummaryCursor([(7, 1, 'F', 10, 0, 0, 3, 5, 20)], [
            (1, 7, 1, datetime(2026, 10, 1, 23, 55), datetime(2026, 10, 2, 0, 5), 5, 6,
             'SMDT', 'CABLE CAR1', None, 'waiting', None),
        ])
        result = read_logger_time_summary(cursor, date(2026, 10, 1))
        row = result['summary'][0]
        self.assertEqual((row['SmdtMin'], row['BreakdownMin'], row['TotalLoggedMin']), (5, 20, 38))
        self.assertEqual(result['events'][0]['DurationMin'], 5)
        self.assertEqual(result['events'][0]['StopId'], 6)
        self.assertEqual(result['events'][0]['RelatedMachineSnapshot'], 'CABLE CAR1')

    def test_overlap_warning_is_read_only_and_route_is_get_only(self):
        cursor = SummaryCursor([(7, 1, 'F', 0, 0, 0, 0, 5, 0)], [], overlap=1)
        result = read_logger_time_summary(cursor, date(2026, 10, 1))
        self.assertTrue(result['overlap_warning'])
        self.assertEqual(result['overlap_count'], 1)
        source = inspect.getsource(read_logger_time_summary).upper()
        self.assertFalse(any(word in source for word in ('INSERT ', 'UPDATE ', 'DELETE ', 'MERGE ')))
        paths = {(route.path, tuple(route.methods or ())) for route in app.routes if hasattr(route, 'methods')}
        self.assertIn(('/logger/summary', ('GET',)), paths)


class GuideCursor:
    def __init__(self, instance_count=14, events=None, assignment=None):
        self.instance_count = instance_count
        self.calls = []
        self.result = []
        self.guide_params = ()
        self.assignment = assignment
        self.events = events if events is not None else [
            (date(2026, 10, 1), 7, 1, 2, 5, datetime(2026, 10, 1, 8, 0), 1),
            (date(2026, 10, 1), 7, 2, 2, 6, datetime(2026, 10, 1, 8, 0), 1)]

    def execute(self, query, *params):
        self.calls.append((query, params))
        if 'SELECT lot.ProdDate, press.MachineCode' in query:
            self.result = [self.assignment] if self.assignment else []
        elif 'FROM dbo.Fitting_MainMachine' in query:
            self.result = [(7, self.instance_count)]
        elif 'FROM dbo.Fitting_StopType' in query:
            self.result = [(2, 'SETUP'), (3, 'CHGOVER'), (4, 'IDLE'),
                           (5, 'CLEAN'), (6, 'SMDT'), (7, 'BD')]
        elif 'FROM dbo.ProductionShiftRuleHistory' in query:
            self.description = [('EffectiveFromDate',), ('ShiftID',), ('StartTime',)]
            self.result = [(date(2026, 1, 1), 1, datetime(2026, 1, 1, 6, 0).time()),
                           (date(2026, 1, 1), 2, datetime(2026, 1, 1, 19, 0).time())]
        elif 'FROM dbo.LoggerEvent' in query:
            self.guide_params = params
            production_date, mc_id, instance_no, *stop_ids = params
            self.result = [
                (stop_id, duration, stop_datetime, shift_id)
                for event_date, event_mc_id, event_instance, stop_id, duration,
                    stop_datetime, shift_id in self.events
                if (event_date, event_mc_id, event_instance) ==
                   (production_date, mc_id, instance_no) and stop_id in stop_ids
            ]
        else:
            raise AssertionError(query)

    def fetchall(self):
        result, self.result = self.result, []
        return result

    def fetchone(self):
        result, self.result = (self.result[0] if self.result else None), []
        return result

    def cursor(self):
        return self

    def close(self):
        pass


class PressGuideRouteConnection:
    def __init__(self, cursor):
        self.guide_cursor = cursor

    def cursor(self):
        return self

    def execute(self, query, *params):
        if 'SELECT lot.ProdDate, press.MachineCode' in query:
            self.guide_cursor.result = [(date(2026, 10, 1), 'F1')]
            self.guide_cursor.calls.append((query, params))
            return self
        return self.guide_cursor.execute(query, *params)

    def fetchone(self):
        return self.guide_cursor.fetchone()

    def fetchall(self):
        return self.guide_cursor.fetchall()

    def close(self):
        self.guide_cursor.close()


if __name__ == '__main__':
    unittest.main()