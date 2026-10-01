import unittest

from app.logger import (
    DIRECT_SUB,
    RELATED_MAIN,
    RELATED_SUB,
    LoggerResolutionError,
    LoggerSaveInput,
    LoggerValidationError,
    expand_main_machine,
    expand_sub_related_options,
    main_machine_categories,
    normalize_sub_related_selection,
    read_logger_events,
    read_logger_masters,
    save_logger_event,
    suggest_cause,
    sub_related_options_for_instance,
)


class QueueCursor:
    def __init__(self, result_sets):
        self.result_sets = iter(result_sets)
        self.queries = []

    def execute(self, query, *params):
        self.queries.append((query, params))

    def fetchall(self):
        return next(self.result_sets)


class SaveCursor:
    def __init__(self, event_id=101, fail=False):
        self.event_id = event_id
        self.fail = fail
        self.executed = []

    def execute(self, query, *params):
        if self.fail:
            raise RuntimeError("simulated INSERT failure")
        self.executed.append((query, params))

    def fetchone(self):
        return (self.event_id,)


class SaveConnection:
    def __init__(self, event_id=101, fail=False):
        self.cursor_instance = SaveCursor(event_id=event_id, fail=fail)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


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
        self.stop_types = [
            {"StopId": 1, "StopType": "RUN"},
            {"StopId": 2, "StopType": "SETUP"},
            {"StopId": 6, "StopType": "SMDT"},
            {"StopId": 7, "StopType": "BD"},
        ]
        self.sub_stop_types = [
            {"SubStopId": 1, "StopId": 1, "SubStopType": "--"},
            {"SubStopId": 2, "StopId": 2, "SubStopType": "Setup reason"},
            {"SubStopId": 20, "StopId": 6, "SubStopType": "Other"},
            {"SubStopId": 21, "StopId": 7, "SubStopType": "--"},
        ]
        self.causes = [
            {"CauseId": 1, "Cause": "Setup cause", "McId": 7, "SubMcId": 2,
             "StopId": 2, "SubStopId": 2, "MEO": "M"},
            {"CauseId": 2, "Cause": "SMDT cause", "McId": 7, "SubMcId": 2,
             "StopId": 6, "SubStopId": 20, "MEO": "E"},
            {"CauseId": 3, "Cause": "Mixed shortcut", "McId": 5, "SubMcId": 2,
             "StopId": 1, "SubStopId": 1, "MEO": None},
        ]

    def masters(self):
        return type("Masters", (), {
            "main_machines": self.main_machines,
            "sub_machines": self.sub_machines[:4],
            "stop_types": self.stop_types,
            "sub_stop_types": self.sub_stop_types,
            "causes": self.causes,
        })()

    def save_input(self, **overrides):
        values = dict(
            production_date="2026-10-01", stop="08:00", start="08:15",
            mc_id=7, mc_instance_no=1, sub_mc_id=2, sub_mc_instance_no=1,
            stop_id=1, sub_stop_id=1, classification_edited=False,
        )
        values.update(overrides)
        return LoggerSaveInput(**values)

    def test_main_machine_instance_expansion(self):
        instances = expand_main_machine(self.main_machines[0])
        self.assertEqual(len(instances), 14)
        self.assertEqual(instances[0]["display_label"], "F1")
        self.assertEqual(instances[-1]["display_label"], "F14")

    def test_main_machine_categories_are_broad_master_names(self):
        categories = main_machine_categories(self.main_machines)
        self.assertEqual([item["machine"] for item in categories], ["F", "Robot", "LINE"])
        self.assertEqual([item["mc_id"] for item in categories], [7, 4, 5])

    def test_instance_options_are_scoped_to_selected_machine_instance(self):
        line_one = sub_related_options_for_instance(
            self.main_machines, self.sub_machines, 5, 1)
        line_two = sub_related_options_for_instance(
            self.main_machines, self.sub_machines, 5, 2)
        self.assertEqual([item["display_label"] for item in line_one],
                         ["Conv1", "Conv2", "Conv3", "Conv4", "Conv5"])
        self.assertEqual([item["display_label"] for item in line_two],
                         ["Conv1", "Conv2", "Conv3", "Conv4", "Conv5"])
        self.assertTrue(all(item["owner_mc_id"] == 5 for item in line_one))
        self.assertTrue(all(item["owner_mc_instance_no"] == 1 for item in line_one))
        self.assertEqual(sub_related_options_for_instance(
            self.main_machines, self.sub_machines, 4, 1), [])

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
        self.assertTrue(all("IsActive=1" in query for query, _ in cursor.queries))

    def test_read_logger_events_filters_and_orders_with_snapshots(self):
        cursor = QueueCursor([[
            (2, "2026-10-01", "stop", "start", 10, "F2", "LINE1", None,
             "Cause", "RUN", None, "M", "note"),
        ]])
        events = read_logger_events(cursor, "2026-10-01")
        query, params = cursor.queries[0]
        self.assertIn("WHERE ProductionDate=?", query)
        self.assertIn("ORDER BY StopDateTime DESC, LoggerEventID DESC", query)
        self.assertEqual(params, ("2026-10-01",))
        self.assertEqual(events[0]["MachineNameSnapshot"], "F2")
        self.assertEqual(events[0]["RelatedMachineSnapshot"], "LINE1")
        self.assertIsNone(events[0]["SubMachineSnapshot"])

    def test_save_direct_sub_builds_snapshots_and_returns_identity(self):
        connection = SaveConnection(event_id=501)
        event_id = save_logger_event(connection, self.save_input(), self.masters())
        self.assertEqual(event_id, 501)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        query, params = connection.cursor_instance.executed[0]
        self.assertIn("OUTPUT INSERTED.LoggerEventID", query)
        self.assertIn("?", query)
        self.assertNotIn("F1", query)
        self.assertEqual(params[14:20], ("F1", None, "Mould1", "RUN", "--", None))

    def test_save_related_main_and_related_sub(self):
        related_main = save_logger_event(
            SaveConnection(), self.save_input(related_mc_id=5, related_mc_instance_no=1,
                                               sub_mc_id=None, sub_mc_instance_no=None), self.masters())
        related_sub = save_logger_event(
            SaveConnection(), self.save_input(related_mc_id=5, related_mc_instance_no=1,
                                               sub_mc_id=9, sub_mc_instance_no=3), self.masters())
        self.assertEqual((related_main, related_sub), (101, 101))

    def test_save_robot_proxy_uses_related_main_not_physical_submachine(self):
        connection = SaveConnection()
        save_logger_event(connection, self.save_input(
            related_mc_id=4, related_mc_instance_no=2,
            sub_mc_id=None, sub_mc_instance_no=None), self.masters())
        params = connection.cursor_instance.executed[0][1]
        self.assertEqual(params[8], None)
        self.assertEqual(params[12], None)

    def test_proxy_submachine_is_rejected(self):
        with self.assertRaisesRegex(LoggerValidationError, "proxy"):
            save_logger_event(SaveConnection(), self.save_input(
                sub_mc_id=23, sub_mc_instance_no=1), self.masters())

    def test_invalid_instance_numbers_are_rejected(self):
        for overrides, text in (
            ({"mc_instance_no": 15}, "McInstanceNo"),
            ({"related_mc_id": 5, "related_mc_instance_no": 3,
              "sub_mc_id": None, "sub_mc_instance_no": None}, "RelatedMcInstanceNo"),
            ({"sub_mc_instance_no": 2}, "SubMcInstanceNo"),
        ):
            with self.subTest(text=text):
                with self.assertRaises(LoggerValidationError):
                    save_logger_event(SaveConnection(), self.save_input(**overrides), self.masters())

    def test_time_rules_and_equal_time_rejection(self):
        same_day = save_logger_event(SaveConnection(event_id=1), self.save_input(), self.masters())
        midnight_connection = SaveConnection(event_id=2)
        save_logger_event(midnight_connection, self.save_input(stop="23:55", start="00:05"), self.masters())
        params = midnight_connection.cursor_instance.executed[0][1]
        self.assertEqual(same_day, 1)
        self.assertEqual(params[3], 10)
        self.assertEqual(str(params[1]), "2026-10-01 23:55:00")
        self.assertEqual(str(params[2]), "2026-10-02 00:05:00")
        with self.assertRaisesRegex(LoggerValidationError, "differ"):
            save_logger_event(SaveConnection(), self.save_input(stop="10:00", start="10:00"), self.masters())

    def test_classification_provenance_and_duration_rule(self):
        cause_shortcut = SaveConnection()
        save_logger_event(cause_shortcut, self.save_input(cause_id=1, stop_id=2, sub_stop_id=2), self.masters())
        self.assertEqual(cause_shortcut.cursor_instance.executed[0][1][22], "CAUSE_SHORTCUT")

        manual = SaveConnection()
        save_logger_event(manual, self.save_input(cause_id=1, classification_edited=True), self.masters())
        self.assertEqual(manual.cursor_instance.executed[0][1][22], "MANUAL")

        manual_smdt_subtype = SaveConnection()
        save_logger_event(manual_smdt_subtype, self.save_input(
            cause_id=2, stop_id=6, sub_stop_id=20, classification_edited=True,
            stop="08:00", start="08:09"), self.masters())
        self.assertEqual(manual_smdt_subtype.cursor_instance.executed[0][1][10:13], (6, 20, 2))

        no_cause = SaveConnection()
        save_logger_event(no_cause, self.save_input(cause_id=None), self.masters())
        self.assertEqual(no_cause.cursor_instance.executed[0][1][22], "MANUAL")

        mismatch = self.save_input(cause_id=1, stop_id=1, sub_stop_id=1)
        with self.assertRaisesRegex(LoggerValidationError, "classification"):
            save_logger_event(SaveConnection(), mismatch, self.masters())

        smdt_short = SaveConnection()
        save_logger_event(smdt_short, self.save_input(cause_id=2, stop_id=6, sub_stop_id=20,
                                                       stop="08:00", start="08:09"), self.masters())
        short_params = smdt_short.cursor_instance.executed[0][1]
        self.assertEqual(short_params[10:13], (6, 20, 2))
        self.assertEqual(short_params[22], "CAUSE_SHORTCUT")

        smdt_long = SaveConnection()
        save_logger_event(smdt_long, self.save_input(cause_id=2, stop_id=6, sub_stop_id=20,
                                                      stop="08:00", start="08:10"), self.masters())
        long_params = smdt_long.cursor_instance.executed[0][1]
        self.assertEqual(long_params[10:13], (7, 21, 2))
        self.assertEqual(long_params[17:20], ("BD", "--", "SMDT cause"))
        self.assertEqual(long_params[22], "DURATION_RULE")

    def test_setup_is_not_duration_converted_and_nullable_fields_are_supported(self):
        connection = SaveConnection()
        save_logger_event(connection, self.save_input(
            cause_id=None, stop_id=2, sub_stop_id=2, stop="08:00", start="08:10",
            related_mc_id=5, related_mc_instance_no=1,
            sub_mc_id=None, sub_mc_instance_no=None), self.masters())
        params = connection.cursor_instance.executed[0][1]
        self.assertEqual(params[10:13], (2, 2, None))
        self.assertEqual(params[17:20], ("SETUP", "Setup reason", None))

    def test_cause_owner_mismatch_is_allowed(self):
        connection = SaveConnection()
        save_logger_event(connection, self.save_input(
            cause_id=3, stop_id=1, sub_stop_id=1), self.masters())
        self.assertEqual(connection.commits, 1)

    def test_validation_and_database_failures_rollback(self):
        validation_connection = SaveConnection()
        with self.assertRaises(LoggerValidationError):
            save_logger_event(validation_connection, self.save_input(mc_instance_no=99), self.masters())
        self.assertEqual(validation_connection.rollbacks, 1)
        self.assertEqual(validation_connection.commits, 0)

        database_connection = SaveConnection(fail=True)
        with self.assertRaisesRegex(LoggerValidationError, "INSERT"):
            save_logger_event(database_connection, self.save_input(), self.masters())
        self.assertEqual(database_connection.rollbacks, 1)
        self.assertEqual(database_connection.commits, 0)


if __name__ == "__main__":
    unittest.main()
