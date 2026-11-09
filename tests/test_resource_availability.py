import unittest
from datetime import date, datetime, time

from app.resource_availability import (find_assignment_conflict,
                                       validate_lot_resource_availability,
                                       resolve_effective_interval)


DAY = date(2026, 11, 7)
DAY_START = time(7, 0)


class AssignmentCursor:
    def __init__(self, assignments):
        self.assignments = assignments
        self.result = []

    def execute(self, query, *args):
        resource_id, excluded_id = args
        self.result = [
            row[:8] for row in self.assignments
            if row[8] == resource_id and row[0] != (excluded_id or 0)
        ]

    def fetchall(self):
        return self.result


class LotUpdateCursor:
    def __init__(self, assignments, conflicts):
        self.assignments = assignments
        self.conflicts = conflicts
        self.result = []

    def execute(self, query, *args):
        if 'FROM dbo.PressProduction' in query and 'WHERE ProductionID=?' in query:
            self.result = self.assignments
        elif 'SELECT TOP (1) DayStartTime' in query:
            self.result = [(DAY_START,)]
        else:
            resource_id, excluded_id = args
            self.result = [
                row[:8] for row in self.conflicts
                if row[0] != (excluded_id or 0)
                and row[8] == resource_id
            ]

    def fetchone(self):
        return self.result.pop(0) if self.result else None

    def fetchall(self):
        result, self.result = self.result, []
        return result


def assignment(assignment_id, lot, prod_date, assignment_start, assignment_end,
               lot_start, lot_end, day_start=DAY_START, resource_id='F1'):
    return (assignment_id, lot, prod_date, assignment_start, assignment_end,
            lot_start, lot_end, day_start, resource_id)


class ResourceAvailabilityTests(unittest.TestCase):
    def test_inherits_both_lot_boundaries(self):
        self.assertEqual(
            resolve_effective_interval(DAY, DAY_START, None, None,
                                       time(8), time(12)),
            (datetime(2026, 11, 7, 8), datetime(2026, 11, 7, 12)))

    def test_explicit_times_override_lot_interval(self):
        self.assertEqual(
            resolve_effective_interval(DAY, DAY_START,
                                       datetime(2026, 11, 7, 9),
                                       datetime(2026, 11, 7, 11),
                                       time(8), time(16)),
            (datetime(2026, 11, 7, 9), datetime(2026, 11, 7, 11)))

    def test_partial_assignment_times_inherit_missing_boundary(self):
        self.assertEqual(
            resolve_effective_interval(DAY, DAY_START,
                                       time(10), None, time(8), time(16)),
            (datetime(2026, 11, 7, 10), datetime(2026, 11, 7, 16)))

    def test_missing_lot_end_is_ongoing(self):
        self.assertEqual(
            resolve_effective_interval(DAY, DAY_START, None, None,
                                       time(8), None),
            (datetime(2026, 11, 7, 8), None))

    def test_unresolved_start_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'no resolvable start'):
            resolve_effective_interval(DAY, DAY_START, None, None, None, None)

    def test_end_equal_or_before_start_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'later than its start'):
            resolve_effective_interval(DAY, DAY_START, None, None,
                                       time(8), time(8))

    def test_overnight_and_cross_date_intervals_resolve_by_day_rule(self):
        self.assertEqual(
            resolve_effective_interval(DAY, DAY_START, None, None,
                                       time(16), time(1)),
            (datetime(2026, 11, 7, 16), datetime(2026, 11, 8, 1)))

    def test_adjacent_assignment_does_not_conflict(self):
        cursor = AssignmentCursor([assignment(
            1, 'I02691112', DAY, None, None, time(8), time(16))])
        reason = find_assignment_conflict(
            cursor, 'press', 'F1',
            (datetime(2026, 11, 7, 16), datetime(2026, 11, 8, 1)))
        self.assertIsNone(reason)

    def test_overlapping_press_conflicts_across_shifts_and_lots(self):
        cursor = AssignmentCursor([assignment(
            1, 'I02691112', DAY, None, None, time(8), time(16))])
        reason = find_assignment_conflict(
            cursor, 'press', 'F1',
            (datetime(2026, 11, 7, 15), datetime(2026, 11, 7, 18)))
        self.assertIn('Lot I02691112', reason)

    def test_mould_conflicts_across_different_press_machines(self):
        cursor = AssignmentCursor([assignment(
            1, 'I02691112', DAY, None, None, time(8), time(12), resource_id=9)])
        reason = find_assignment_conflict(
            cursor, 'mould', 9,
            (datetime(2026, 11, 7, 11), datetime(2026, 11, 7, 15)))
        self.assertIn('Lot I02691112', reason)

    def test_ongoing_assignment_conflicts_with_later_request(self):
        cursor = AssignmentCursor([assignment(
            1, 'I02691112', DAY, None, None, time(8), None)])
        reason = find_assignment_conflict(
            cursor, 'press', 'F1',
            (datetime(2026, 11, 8, 8), datetime(2026, 11, 8, 12)))
        self.assertIn('ongoing', reason)

    def test_edit_excludes_its_own_assignment(self):
        cursor = AssignmentCursor([assignment(
            1, 'I02691112', DAY, None, None, time(8), time(12))])
        reason = find_assignment_conflict(
            cursor, 'press', 'F1',
            (datetime(2026, 11, 7, 8), datetime(2026, 11, 7, 12)), 1)
        self.assertIsNone(reason)

    def test_changing_lot_times_rejects_overlap_with_inherited_assignment(self):
        current = (1, 'F1', 9, None, None)
        occupied = assignment(
            2, 'I02691112', DAY, None, None, time(11), time(13),
            resource_id='F1')
        cursor = LotUpdateCursor([current], [occupied])
        with self.assertRaisesRegex(ValueError, 'Lot I02691112'):
            validate_lot_resource_availability(
                cursor, 7, DAY, time(10), time(12))


if __name__ == '__main__':
    unittest.main()
