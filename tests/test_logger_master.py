import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from app.logger_master import build_master_review, read_logger_master_review
from app.main import app, logger_master_page
from starlette.requests import Request


def request():
    return Request({'type': 'http', 'method': 'GET', 'path': '/logger/master', 'headers': []})


class LoggerMasterReviewTests(unittest.TestCase):
    def setUp(self):
        self.main = [
            {'McId': 7, 'Machine': 'F', 'No': 2, 'Relate': 0, 'IsActive': True},
            {'McId': 5, 'Machine': 'LINE', 'No': 2, 'Relate': 1, 'IsActive': True},
        ]
        self.sub = [
            {'SubMcId': 17, 'Equipment': 'Conv', 'McId': 7, 'No': 2, 'IsActive': True, 'IsRelated': False},
            {'SubMcId': 22, 'Equipment': 'CABLE CAR', 'McId': 3, 'No': 2, 'IsActive': True, 'IsRelated': True},
            {'SubMcId': 24, 'Equipment': 'LINE', 'McId': 5, 'No': 2, 'IsActive': True, 'IsRelated': True},
        ]
        self.stops = [
            {'StopId': 6, 'StopType': 'SMDT', 'IsActive': True},
            {'StopId': 7, 'StopType': 'BD', 'IsActive': False},
        ]
        self.sub_stops = [
            {'SubStopId': 20, 'SubStopType': 'Other', 'StopId': 6, 'IsActive': True},
            {'SubStopId': 21, 'SubStopType': 'BD reason', 'StopId': 7, 'IsActive': True},
        ]
        self.causes = [
            {'CauseId': 11, 'Cause': 'รอปูน', 'McId': 3, 'SubMcId': 22, 'StopId': 6, 'SubStopId': 20, 'IsActive': True, 'MEO': 'O'},
            {'CauseId': 12, 'Cause': 'รอแบบ', 'McId': 5, 'SubMcId': 24, 'StopId': 6, 'SubStopId': 20, 'IsActive': True, 'MEO': 'M'},
            {'CauseId': 7, 'Cause': 'วางครอบไม่ได้', 'McId': 5, 'SubMcId': 17, 'StopId': 6, 'SubStopId': 20, 'IsActive': True, 'MEO': 'M'},
        ]

    def test_review_derives_instances_and_mapping_kinds(self):
        review = build_master_review(self.main, self.sub, self.stops, self.sub_stops, self.causes)
        self.assertEqual(review['main_machines'][0]['instances'], ['F1', 'F2'])
        self.assertFalse(review['sub_machines'][0]['IsRelated'])
        self.assertEqual(review['causes'][0]['mapping_kind'], 'RELATED_PROXY')
        self.assertEqual(review['causes'][1]['mapping_kind'], 'RELATED_PROXY')

    def test_known_inconsistent_cause_is_warned(self):
        review = build_master_review(self.main, self.sub, self.stops, self.sub_stops, self.causes)
        cause = next(row for row in review['causes'] if row['CauseId'] == 7)
        self.assertTrue(any('ownership differs' in warning for warning in cause['warnings']))

    def test_inactive_and_reference_warnings_are_diagnostic(self):
        causes = [dict(self.causes[0], McId=99, StopId=99, SubStopId=21, MEO='X')]
        review = build_master_review(self.main, self.sub, self.stops, self.sub_stops, causes)
        warning_text = ' '.join(review['causes'][0]['warnings'])
        self.assertIn('missing Main Machine', warning_text)
        self.assertIn('missing Stop Type', warning_text)
        self.assertIn('different Stop Type', warning_text)
        self.assertIn('MEO', warning_text)

    def test_active_and_inactive_rows_are_counted(self):
        review = build_master_review(self.main, self.sub, self.stops, self.sub_stops, self.causes)
        stop_count = next(item for item in review['counts'] if item['name'] == 'Stop Type')
        self.assertEqual((stop_count['active'], stop_count['inactive']), (1, 1))

    def test_all_master_queries_are_select_only(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [(7, 'F', 2, 0, True)],
            [(17, 'Conv', 5, 2, True, False)],
            [(6, 'SMDT', True)],
            [(20, 'Other', 6, True)],
            [(11, 'Cause', 5, 17, 6, 20, True, 'M')],
        ]
        read_logger_master_review(cursor)
        for call in cursor.execute.call_args_list:
            self.assertTrue(call.args[0].lstrip().upper().startswith('SELECT'))

    def test_route_is_registered_and_renders_review(self):
        paths = {(route.path, tuple(route.methods or ())) for route in app.routes if hasattr(route, 'methods')}
        self.assertIn(('/logger/master', ('GET',)), paths)
        review = build_master_review(self.main, self.sub, self.stops, self.sub_stops, self.causes)
        with patch('app.main.read_logger_master_review', return_value=review), \
             patch('app.main.get_connection', return_value=MagicMock()):
            response = logger_master_page(request(), date(2026, 10, 1))
        body = response.body.decode()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "logger-master")
        self.assertIn('LOGGER MASTER MAINTENANCE', body)
        self.assertIn('RELATED_MAIN PROXY', body)
        self.assertIn('รอปูน', body)
        self.assertIn('วางครอบไม่ได้', body)
        self.assertIn('read-only', body)


if __name__ == '__main__':
    unittest.main()
