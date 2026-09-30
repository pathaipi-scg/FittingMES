import asyncio
import json
import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from starlette.requests import Request

from app.logger import LoggerMasters, LoggerValidationError
from app.logger_page import logger_form_input, logger_page_context
from app.main import (app, logger_page, logger_load_context, save_logger_form,
                      save_logger_route)


def request():
    return Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': []})


class FormRequest:
    def __init__(self, values):
        self.values = values

    async def form(self):
        return self.values


class LoggerPageTests(unittest.TestCase):
    def setUp(self):
        self.masters = LoggerMasters(
            main_machines=[{"McId": 7, "Machine": "F", "No": 2, "Relate": 0},
                         {"McId": 4, "Machine": "Robot", "No": 2, "Relate": 1}],
            sub_machines=[{"SubMcId": 2, "McId": 7, "SubMachine": "Mould", "No": 1, "IsRelated": 0},
                         {"SubMcId": 23, "McId": 4, "SubMachine": "Robot proxy", "No": 1, "IsRelated": 1}],
            stop_types=[{"StopId": 1, "StopType": "RUN"}],
            sub_stop_types=[{"SubStopId": 1, "StopId": 1, "SubStopType": "Reason"}],
            causes=[{"CauseId": 5, "Cause": "Robot cause", "McId": 4, "SubMcId": None,
                     "StopId": 1, "SubStopId": 1, "MEO": "E"}],
        )
        self.option = {"kind": "DIRECT_SUB", "related_mc_id": None,
                       "related_mc_instance_no": None, "sub_mc_id": 2,
                       "sub_mc_instance_no": 1, "display_label": "Mould1"}

    def form(self, **overrides):
        values = {
            "production_date": "2026-10-01", "stop": "23:55", "start": "00:05",
            "mc_id": "7", "mc_instance_no": "1",
            "sub_related_selection": json.dumps(self.option),
            "related_mc_id": "", "related_mc_instance_no": "",
            "sub_mc_id": "2", "sub_mc_instance_no": "1", "stop_id": "1",
            "sub_stop_id": "1", "cause_id": "", "meo": "E", "note": "note",
            "classification_edited": "false",
        }
        values.update(overrides)
        return values

    def test_context_renders_expanded_machines_and_normalized_options(self):
        context = logger_page_context(self.masters, date(2026, 10, 1), logger_events=[])
        self.assertEqual([item["display_label"] for item in context["main_instances"]],
                         ["F1", "F2", "Robot1", "Robot2"])
        options = json.loads(context["sub_related_options_json"])
        self.assertEqual(options[0]["kind"], "DIRECT_SUB")
        self.assertEqual(options[-1]["kind"], "RELATED_MAIN")
        self.assertEqual(context["active_tab"], "logger")

    def test_form_input_keeps_nullable_values_and_created_by_null(self):
        data, selection = logger_form_input(self.form(related_mc_id="", sub_mc_id=""))
        self.assertEqual(data.created_by, None)
        self.assertIsNone(data.related_mc_id)
        self.assertIsNone(data.sub_mc_id)
        self.assertEqual(selection["kind"], "DIRECT_SUB")

    def test_save_form_normalizes_selection_and_calls_service_once(self):
        conn = MagicMock()
        with patch("app.main.get_connection", return_value=conn), \
             patch("app.main.read_logger_masters", return_value=self.masters), \
             patch("app.main.save_logger_event", return_value=101) as save:
            result = save_logger_form(self.form())
        self.assertEqual(result, date(2026, 10, 1))
        save.assert_called_once()
        data = save.call_args.args[1]
        self.assertEqual(data.sub_mc_id, 2)
        self.assertIsNone(data.related_mc_id)
        self.assertIsNone(data.created_by)

    def test_malformed_selection_does_not_reach_service(self):
        with patch("app.main.save_logger_event") as save:
            with self.assertRaises(ValueError):
                save_logger_form(self.form(sub_related_selection="not-json"))
        save.assert_not_called()

    def test_validation_error_is_after_one_service_call(self):
        conn = MagicMock()
        with patch("app.main.get_connection", return_value=conn), \
             patch("app.main.read_logger_masters", return_value=self.masters), \
             patch("app.main.save_logger_event", side_effect=LoggerValidationError("EQUAL_STOP_START", "Stop and Start times must differ.")) as save:
            with self.assertRaises(LoggerValidationError):
                save_logger_form(self.form(stop="10:00", start="10:00"))
        save.assert_called_once()

    def test_logger_route_is_registered(self):
        paths = {(route.path, tuple(route.methods or ())) for route in app.routes}
        self.assertIn(("/logger", ("GET",)), paths)
        self.assertIn(("/logger/save", ("POST",)), paths)

    def test_get_logger_renders_selected_date_and_navigation(self):
        events = [{"LoggerEventID": 1, "ProductionDate": date(2026, 10, 1),
                   "StopDateTime": datetime(2026, 10, 1, 23, 55),
                   "StartDateTime": datetime(2026, 10, 2, 0, 5), "DurationMin": 10,
                   "MachineNameSnapshot": "F1", "RelatedMachineSnapshot": "LINE1",
                   "SubMachineSnapshot": "Conv3", "CauseSnapshot": "Cause snapshot",
                   "StopTypeSnapshot": "SMDT", "SubStopTypeSnapshot": "Other",
                   "MEO": None, "Note": None}]
        with patch("app.main.get_connection", return_value=MagicMock()), \
             patch("app.main.read_logger_masters", return_value=self.masters), \
             patch("app.main.read_logger_events", return_value=events) as read_events:
            response = logger_page(request(), date(2026, 10, 1))
        body = response.body.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="2026-10-01"', body)
        self.assertIn('LOGGER', body)
        self.assertIn('href="/logger?production_date=2026-10-01" aria-current="page"', body)
        self.assertIn('F1', body)
        self.assertIn('Mould1', body)
        self.assertIn('LINE1 / Conv3', body)
        self.assertIn('2026-10-02 00:05', body)
        self.assertNotIn('No LOGGER entries for this Production Date.', body)
        read_events.assert_called_once_with(unittest.mock.ANY, date(2026, 10, 1))

    def test_empty_logger_history_message(self):
        context = logger_page_context(self.masters, date(2026, 10, 1), logger_events=[])
        self.assertEqual(context["logger_events"], [])

    def test_history_renders_all_snapshot_hierarchy_shapes_and_nullable_values(self):
        events = [
            {"MachineNameSnapshot": "F1", "RelatedMachineSnapshot": None,
             "SubMachineSnapshot": "Mould1", "CauseSnapshot": None,
             "StopTypeSnapshot": "RUN", "SubStopTypeSnapshot": None, "MEO": None,
             "StopDateTime": datetime(2026, 10, 1, 8),
             "StartDateTime": datetime(2026, 10, 1, 8, 5), "DurationMin": 5, "Note": None},
            {"MachineNameSnapshot": "F1", "RelatedMachineSnapshot": "LINE1",
             "SubMachineSnapshot": None, "CauseSnapshot": "Line cause",
             "StopTypeSnapshot": "SETUP", "SubStopTypeSnapshot": "Setup", "MEO": "M",
             "StopDateTime": datetime(2026, 10, 1, 7),
             "StartDateTime": datetime(2026, 10, 1, 7, 5), "DurationMin": 5, "Note": "n"},
        ]
        context = logger_page_context(self.masters, date(2026, 10, 1), logger_events=events)
        with patch("app.main.get_connection", return_value=MagicMock()), \
             patch("app.main.read_logger_masters", return_value=self.masters), \
             patch("app.main.read_logger_events", return_value=events):
            response = logger_page(request(), date(2026, 10, 1))
        self.assertEqual(context["logger_events"][0]["SubMachineSnapshot"], "Mould1")
        self.assertEqual(context["logger_events"][1]["RelatedMachineSnapshot"], "LINE1")
        self.assertEqual(response.status_code, 200)
        body = response.body.decode()
        self.assertIn("Mould1", body)
        self.assertIn("LINE1", body)
        self.assertIn("-", body)

    def test_successful_save_redirects_without_stale_form_values(self):
        async def run_save(function, values):
            return date(2026, 10, 1)

        with patch("app.main.run_in_threadpool", side_effect=run_save):
            response = asyncio.run(save_logger_route(FormRequest(self.form(note="stale"))))
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/logger?production_date=2026-10-01&saved=true")
        self.assertNotIn("stale", response.headers["location"])

    def test_controller_parse_failure_does_not_call_save(self):
        async def reject_parse(function, values):
            raise ValueError("Enter a valid Production Date.")

        with patch("app.main.run_in_threadpool", side_effect=reject_parse), \
             patch("app.main.save_logger_event") as save:
            response = asyncio.run(save_logger_route(FormRequest({"production_date": "bad"})))
        self.assertEqual(response.status_code, 400)
        save.assert_not_called()

    def test_logger_validation_error_renders_without_redirect(self):
        async def reject_save(function, values):
            raise LoggerValidationError("EQUAL_STOP_START", "Stop and Start times must differ.")

        with patch("app.main.run_in_threadpool", side_effect=reject_save), \
             patch("app.main.save_logger_event") as save:
            response = asyncio.run(save_logger_route(FormRequest(self.form())))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("location", response.headers)
        save.assert_not_called()

    def test_unexpected_save_error_is_generic_and_not_redirected(self):
        async def reject_save(function, values):
            raise RuntimeError("SQL password and server details")

        with patch("app.main.run_in_threadpool", side_effect=reject_save), \
             patch("app.main.save_logger_event") as save:
            response = asyncio.run(save_logger_route(FormRequest(self.form())))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SQL password", response.body.decode())
        self.assertNotIn("location", response.headers)
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
