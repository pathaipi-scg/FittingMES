import unittest

from app.logger import (
    DIRECT_SUB,
    RELATED_MAIN,
    RELATED_SUB,
    LoggerResolutionError,
    expand_main_machine,
    expand_sub_related_options,
    normalize_sub_related_selection,
    read_logger_masters,
    suggest_cause,
)


class QueueCursor:
    def __init__(self, result_sets):
        self.result_sets = iter(result_sets)
        self.queries = []

    def execute(self, query):
        self.queries.append(query)

    def fetchall(self):
        return next(self.result_sets)


class LoggerResolverTests(unittest.TestCase):
    def setUp(self):
        self.main_machines = [
            {"McId": 7, "Machine": "F", "No": 14, "Relate": 0},
            {"McId": 4, "Machine": "Robot", "No": 7, "Relate": 1},
            {"McId": 5, "Machine": "LINE", "No": 2, "Relate": 1},
        ]
        self.sub_machines = [
            {"SubMcId": 2, "McId": 7, "SubMachine": "Mould", "No": 1, "IsRelated": 0},
            {"SubMcId": 9, "McId": 5, "SubMachine": "Conv", "No": 5, "IsRelated": 0},
            {"SubMcId": 23, "McId": 4, "SubMachine": "Robot proxy", "No": 1, "IsRelated": 1},
            {"SubMcId": 24, "McId": 5, "SubMachine": "LINE proxy", "No": 1, "IsRelated": 1},
            {"SubMcId": 99, "McId": 7, "SubMachine": "Inactive", "No": 4, "IsRelated": 0},
        ]

    def test_main_machine_instance_expansion(self):
        instances = expand_main_machine(self.main_machines[0])
        self.assertEqual(len(instances), 14)
        self.assertEqual(instances[0]["display_label"], "F1")
        self.assertEqual(instances[-1]["display_label"], "F14")

    def test_physical_submachine_instance_expansion(self):
        options = expand_sub_related_options(self.main_machines, self.sub_machines[1:2])
        self.assertEqual([option["display_label"] for option in options],
                         ["Conv1", "Conv2", "Conv3", "Conv4", "Conv5"])
        self.assertTrue(all(option["kind"] == DIRECT_SUB for option in options))
        self.assertTrue(all(option["sub_mc_id"] == 9 for option in options))

    def test_related_proxy_uses_main_machine_count_and_never_returns_proxy_id(self):
        options = expand_sub_related_options(self.main_machines, self.sub_machines[2:3])
        self.assertEqual([option["display_label"] for option in options],
                         ["Robot1", "Robot2", "Robot3", "Robot4", "Robot5", "Robot6", "Robot7"])
        self.assertTrue(all(option["kind"] == RELATED_MAIN for option in options))
        self.assertTrue(all(option["related_mc_id"] == 4 for option in options))
        self.assertTrue(all(option["sub_mc_id"] is None for option in options))

    def test_direct_sub_normalization(self):
        options = expand_sub_related_options(self.main_machines, self.sub_machines[:1])
        normalized = normalize_sub_related_selection(options[0], self.main_machines, self.sub_machines)
        self.assertEqual(normalized["kind"], DIRECT_SUB)
        self.assertEqual(normalized["sub_mc_id"], 2)
        self.assertEqual(normalized["sub_mc_instance_no"], 1)

    def test_related_main_normalization(self):
        options = expand_sub_related_options(self.main_machines, self.sub_machines[3:4])
        selected = next(option for option in options if option["display_label"] == "LINE1")
        normalized = normalize_sub_related_selection(selected, self.main_machines, self.sub_machines)
        self.assertEqual(normalized["kind"], RELATED_MAIN)
        self.assertEqual(normalized["related_mc_id"], 5)
        self.assertIsNone(normalized["sub_mc_id"])

    def test_related_sub_normalization(self):
        options = expand_sub_related_options(self.main_machines, self.sub_machines)
        selected = next(option for option in options if option["display_label"] == "LINE1 / Conv3")
        normalized = normalize_sub_related_selection(selected, self.main_machines, self.sub_machines)
        self.assertEqual(normalized["kind"], RELATED_SUB)
        self.assertEqual(normalized["related_mc_id"], 5)
        self.assertEqual(normalized["sub_mc_id"], 9)
        self.assertEqual(normalized["sub_mc_instance_no"], 3)

    def test_machine_first_cause_does_not_overwrite_selected_machine(self):
        cause = {"CauseId": 1, "McId": 5, "SubMcId": 9, "StopId": 2, "SubStopId": 3, "MEO": "M"}
        options = expand_sub_related_options(self.main_machines, self.sub_machines[1:2])
        suggestion = suggest_cause(cause, selected_machine_id=7, sub_related_options=options)
        self.assertEqual(suggestion["machine_id"], 7)
        self.assertEqual(suggestion["sub_related_option"]["sub_mc_id"], 9)

    def test_cause_first_can_suggest_initial_machine(self):
        cause = {"CauseId": 1, "McId": 5, "SubMcId": None, "StopId": 2, "SubStopId": None, "MEO": "E"}
        suggestion = suggest_cause(cause)
        self.assertEqual(suggestion["machine_id"], 5)

    def test_cause_with_different_submachine_owner_is_not_rejected(self):
        cause = {"CauseId": 1, "McId": 5, "SubMcId": 2, "StopId": 2, "SubStopId": None, "MEO": None}
        options = expand_sub_related_options(self.main_machines, self.sub_machines[:1])
        suggestion = suggest_cause(cause, selected_machine_id=7, sub_related_options=options)
        self.assertEqual(suggestion["sub_related_option"]["sub_mc_id"], 2)

    def test_inactive_rows_are_absent_from_active_input(self):
        options = expand_sub_related_options(self.main_machines, self.sub_machines[:1])
        self.assertNotIn(99, {option["sub_mc_id"] for option in options})

    def test_missing_proxy_main_machine_is_skipped_without_guessing(self):
        missing_proxy = [{"SubMcId": 25, "McId": 999, "SubMachine": "Unknown", "No": 1, "IsRelated": 1}]
        self.assertEqual(expand_sub_related_options(self.main_machines, missing_proxy), [])

    def test_invalid_selection_fails_safely(self):
        with self.assertRaises(LoggerResolutionError):
            normalize_sub_related_selection(
                {"kind": DIRECT_SUB, "sub_mc_id": 999, "sub_mc_instance_no": 1,
                 "related_mc_id": None, "related_mc_instance_no": None},
                self.main_machines, self.sub_machines,
            )

    def test_read_logger_masters_loads_each_active_master(self):
        cursor = QueueCursor([
            [(7, "F", 14, 0)],
            [(2, 7, "Mould", 1, 0)],
            [(1, "RUN")],
            [(1, 1, "Unplanned")],
            [(1, "Cause", 7, 2, 1, None, "M")],
        ])
        masters = read_logger_masters(cursor)
        self.assertEqual(len(cursor.queries), 5)
        self.assertEqual(masters.main_machines[0]["McId"], 7)
        self.assertEqual(masters.sub_machines[0]["IsRelated"], 0)
        self.assertEqual(masters.stop_types[0]["StopType"], "RUN")
        self.assertEqual(masters.sub_stop_types[0]["StopId"], 1)
        self.assertEqual(masters.causes[0]["SubMcId"], 2)
        self.assertTrue(all("IsActive=1" in query for query in cursor.queries))


if __name__ == "__main__":
    unittest.main()
