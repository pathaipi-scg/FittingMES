import unittest
from datetime import date, datetime, time, timezone

from app.shift_schedule import (period_contains_interval,
                                period_interval,
                                production_date_for_timestamp,
                                resolve_period_interval,
                                validate_periods)


class ShiftScheduleTests(unittest.TestCase):
    def test_cutoff_boundary_and_midnight_are_independent_of_shift_periods(self):
        self.assertEqual(
            production_date_for_timestamp(datetime(2026, 11, 11, 6, 59, 59), '07:00'),
            date(2026, 11, 10))
        self.assertEqual(
            production_date_for_timestamp(datetime(2026, 11, 11, 7, 0), '07:00'),
            date(2026, 11, 11))
        self.assertEqual(
            production_date_for_timestamp(datetime(2026, 11, 11, 0, 0), '07:00'),
            date(2026, 11, 10))

    def test_aware_timestamps_are_converted_to_bangkok_before_cutoff(self):
        timestamp = datetime(2026, 11, 11, 0, 1, tzinfo=timezone.utc)
        self.assertEqual(
            production_date_for_timestamp(timestamp, '07:00'),
            date(2026, 11, 11))

    def test_overnight_period_and_adjacent_assignment_boundary(self):
        start, end = period_interval(date(2026, 11, 10), '18:00', '04:00')
        self.assertEqual(start, datetime(2026, 11, 10, 18))
        self.assertEqual(end, datetime(2026, 11, 11, 4))
        self.assertTrue(period_contains_interval(
            date(2026, 11, 10), '08:00', '16:00',
            datetime(2026, 11, 10, 15), datetime(2026, 11, 10, 16)))
        self.assertFalse(period_contains_interval(
            date(2026, 11, 10), '08:00', '16:00',
            datetime(2026, 11, 10, 15), datetime(2026, 11, 10, 16, 1)))

    def test_04_to_08_period_crosses_cutoff_without_being_split(self):
        start, end = period_interval(date(2026, 11, 10), '04:00', '08:00', '07:00')
        self.assertEqual(start, datetime(2026, 11, 11, 4))
        self.assertEqual(end, datetime(2026, 11, 11, 8))
        self.assertEqual(
            resolve_period_interval(date(2026, 11, 10), '04:00', '08:00',
                                    '04:30', '07:30', '07:00'),
            (datetime(2026, 11, 11, 4, 30), datetime(2026, 11, 11, 7, 30)))

    def test_active_periods_reject_overlaps_and_allow_adjacency(self):
        validate_periods([
            {'ShiftPeriodID': 1, 'IsActive': True, 'StartTime': time(8), 'EndTime': time(16)},
            {'ShiftPeriodID': 2, 'IsActive': True, 'StartTime': time(16), 'EndTime': time(18)},
            {'ShiftPeriodID': 3, 'IsActive': True, 'StartTime': time(18), 'EndTime': time(4)},
            {'ShiftPeriodID': 4, 'IsActive': True, 'StartTime': time(4), 'EndTime': time(8)},
        ])
        with self.assertRaisesRegex(ValueError, 'cannot overlap'):
            validate_periods([
                {'ShiftPeriodID': 1, 'IsActive': True, 'StartTime': time(8), 'EndTime': time(16)},
                {'ShiftPeriodID': 2, 'IsActive': True, 'StartTime': time(15), 'EndTime': time(17)},
            ])

    def test_same_period_wraparound_overlap_is_detected(self):
        with self.assertRaisesRegex(ValueError, 'cannot overlap'):
            validate_periods([
                {'ShiftPeriodID': 1, 'IsActive': True, 'StartTime': time(22), 'EndTime': time(2)},
                {'ShiftPeriodID': 2, 'IsActive': True, 'StartTime': time(1), 'EndTime': time(3)},
            ])


if __name__ == '__main__':
    unittest.main()
