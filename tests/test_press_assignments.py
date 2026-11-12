import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.main import app, press_assignment_page
from app.press_assignments import read_press_assignment_context
from starlette.requests import Request


PRODUCTION_DATE = date(2026, 11, 10)
ASSIGNMENT_COLUMNS = (
    'PressProductionID', 'ProductionID', 'LotNo', 'ProdDate', 'LotIsActive',
    'MachineCode', 'PressName', 'MouldID', 'MouldNo', 'MouldName',
    'ShiftCode', 'ProductionStartTime', 'ProductionEndTime', 'ReleasedAt',
)


def assignment(assignment_id, *, press='F7', mould_id=32, shift='2',
               start=None, end=None, released=None,
               prod_date=PRODUCTION_DATE):
    return dict(
        PressProductionID=assignment_id,
        ProductionID=98 + assignment_id,
        LotNo=f'LOT{assignment_id}',
        ProdDate=prod_date,
        LotIsActive=True,
        MachineCode=press,
        PressName=f'Press {press}',
        MouldID=mould_id,
        MouldNo=f'M{mould_id:06d}' if mould_id else None,
        MouldName=f'Mould {mould_id}' if mould_id else None,
        ShiftCode=shift,
        ProductionStartTime=start,
        ProductionEndTime=end,
        ReleasedAt=released,
    )


class AssignmentCursor:
    def __init__(self, data):
        self.data = data
        self.description = [(column,) for column in ASSIGNMENT_COLUMNS]
        self.query = None
        self.params = None

    def execute(self, query, *params):
        self.query = query
        self.params = params
        return self

    def fetchall(self):
        return [
            tuple(row[column] for column in ASSIGNMENT_COLUMNS)
            for row in self.data if row['ProdDate'] == self.params[0]
        ]


def request(path='/assign'):
    return Request({'type': 'http', 'method': 'GET', 'path': path,
                    'headers': []})


class PressAssignmentPageTests(unittest.TestCase):
    def test_selects_existing_schema_rows_for_production_date(self):
        cursor = AssignmentCursor([])
        read_press_assignment_context(cursor, PRODUCTION_DATE)
        self.assertTrue(cursor.query.lstrip().upper().startswith('SELECT'))
        self.assertEqual(cursor.params, (PRODUCTION_DATE,))
        self.assertIn('FROM dbo.PressProduction AS pp', cursor.query)
        self.assertIn('WHERE lot.ProdDate=?', cursor.query)
        self.assertNotIn('DATEADD(day, 2', cursor.query)
        self.assertIn('LEFT JOIN dbo.ShiftMaster AS shift', cursor.query)
        self.assertNotIn('ShiftPeriod', cursor.query)
        self.assertNotIn('ShiftMasterVersion', cursor.query)

    def test_cross_midnight_timeline_and_only_actual_active_overlaps(self):
        rows = [
            assignment(131, start=datetime(2026, 11, 10, 19),
                       end=datetime(2026, 11, 11, 6)),
            assignment(132, mould_id=33, start=datetime(2026, 11, 10, 18),
                       end=datetime(2026, 11, 10, 20)),
            assignment(133, press='F8', start=datetime(2026, 11, 10, 20),
                       end=datetime(2026, 11, 10, 21)),
            assignment(134, press='F7', start=None,
                       end=datetime(2026, 11, 10, 22)),
            assignment(135, press='F7', start=datetime(2026, 11, 10, 19),
                       end=datetime(2026, 11, 10, 21),
                       released=datetime(2026, 11, 10, 21)),
            assignment(136, press='F7', mould_id=34,
                       start=datetime(2026, 11, 10, 19, 30),
                       end=datetime(2026, 11, 10, 20, 30),
                       prod_date=date(2026, 11, 9)),
            assignment(137, press='F9', mould_id=35,
                       start=datetime(2026, 11, 10, 23), end=None),
            assignment(138, press='F7', mould_id=36,
                       start=datetime(2026, 11, 11, 0),
                       end=datetime(2026, 11, 11, 3),
                       prod_date=date(2026, 11, 11)),
        ]
        context = read_press_assignment_context(
            AssignmentCursor(rows), PRODUCTION_DATE)
        target = next(row for row in context['assignments']
                      if row['PressProductionID'] == 131)
        incomplete = next(row for row in context['assignments']
                          if row['PressProductionID'] == 134)
        missing_end = next(row for row in context['assignments']
                           if row['PressProductionID'] == 137)
        released = next(row for row in context['assignments']
                        if row['PressProductionID'] == 135)

        self.assertEqual(context['overlap_count'], 2)
        self.assertEqual(len(target['OverlapWarnings']), 2)
        self.assertEqual(
            {row['PressProductionID'] for row in context['assignments']},
            {131, 132, 133, 134, 135, 137})
        self.assertEqual(target['StartDisplay'], '19:00')
        self.assertEqual(target['EndDisplay'], '06:00 (+1 day)')
        self.assertAlmostEqual(target['TimelineLeft'], 39.5833, places=3)
        self.assertAlmostEqual(target['TimelineWidth'], 22.9167, places=3)
        self.assertEqual(incomplete['StartDisplay'], '—')
        self.assertIsNone(incomplete['TimelineWidth'])
        self.assertIn('Missing start time', incomplete['IntervalWarning'])
        self.assertIn('Missing end time', missing_end['IntervalWarning'])
        self.assertIsNone(missing_end['TimelineWidth'])
        self.assertEqual(released['ReleasedStatus'], 'Released')
        self.assertFalse(released['OverlapWarnings'])
        self.assertEqual(len(context['timeline_ticks']), 9)

    def test_filters_assignments_without_removing_global_options(self):
        rows = [
            assignment(1, press='F7', mould_id=32,
                       start=datetime(2026, 11, 10, 8),
                       end=datetime(2026, 11, 10, 10)),
            assignment(2, press='F8', mould_id=33, shift='1',
                       start=datetime(2026, 11, 10, 10),
                       end=datetime(2026, 11, 10, 12)),
        ]
        context = read_press_assignment_context(
            AssignmentCursor(rows), PRODUCTION_DATE,
            press_filter='F7', shift_filter='2', mould_filter='32')
        self.assertEqual([row['PressProductionID']
                          for row in context['assignments']], [1])
        self.assertEqual(context['press_options'], ['F7', 'F8'])
        self.assertEqual(context['shift_options'], ['1', '2'])
        self.assertEqual(context['selected_mould'], '32')

    def test_route_is_get_only_and_renders_date_and_read_only_assignments(self):
        route_methods = {
            (route.path, tuple(route.methods or ()))
            for route in app.routes if hasattr(route, 'methods')
        }
        self.assertIn(('/assign', ('GET',)), route_methods)
        context = dict(
            assignments=[dict(
                PressProductionID=131, ProductionID=98, LotNo='I11691117',
                MachineCode='F7', PressName='Press F7', MouldID=32,
                MouldNo='M000032', ShiftCode='2', ShiftPeriodDisplay='—',
                StartDisplay='19:00', EndDisplay='06:00 (+1 day)',
                ReleasedStatus='Active', LotStatus='Active Lot',
                OverlapWarnings=[], IntervalWarning=None,
                TimelineLeft=39.5833, TimelineWidth=22.9167,
            )],
            press_options=['F7'], shift_options=['2'],
            mould_options=[dict(MouldID='32', Label='M000032')],
            selected_press='', selected_shift='', selected_mould='',
            overlap_count=0, timeline_ticks=[], production_date=PRODUCTION_DATE,
        )
        with patch('app.main.get_connection', return_value=MagicMock()), \
             patch('app.main.read_press_assignment_context',
                   return_value=context) as reader:
            response = press_assignment_page(request(), PRODUCTION_DATE)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_tab'], 'assign')
        reader.assert_called_once()
        body = response.body.decode()
        self.assertIn('ASSIGN', body)
        self.assertIn('production_date=2026-11-10', body)
        self.assertIn('I11691117', body)
        self.assertIn('06:00 (+1 day)', body)
        self.assertNotIn('<form method="post"', body)


if __name__ == '__main__':
    unittest.main()
