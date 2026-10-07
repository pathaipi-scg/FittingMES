import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from starlette.requests import Request
from app.reject import (
    RejectValidationError,
    read_reject_page_data,
    save_reject_entry,
)
from app.reject_page import reject_page_context
from app.reject_summary import read_reject_cal
from app.main import app, reject_cal_page, templates


class FakeCursor:
    def __init__(self, scope="LINE", reason_family=842, reason_exists=True,
                 source_valid=True, existing_ids=None, lot_family=842,
                 active_shifts=None, lot_valid=True, lot_date=None,
                 lot_shift_code="2"):
        self.scope = scope
        self.reason_family = reason_family
        self.reason_exists = reason_exists
        self.source_valid = source_valid
        self.existing_ids = existing_ids or {}
        self.lot_family = lot_family
        self.active_shifts = active_shifts or {733: "1", 734: "2"}
        self.lot_valid = lot_valid
        self.lot_date = lot_date or date(2026, 10, 6)
        self.lot_shift_code = lot_shift_code
        self.calls = []
        self.description = []
        self.result = []
        self.rowcount = -1

    def _set(self, columns, values):
        self.description = [(column,) for column in columns]
        self.result = list(values)

    def execute(self, query, *params):
        self.calls.append((query, params))
        if "SELECT id AS ShiftID,ShiftCode" in query:
            shift_id = params[0]
            self._set(
                ("ShiftID", "ShiftCode"),
                [(shift_id, self.active_shifts[shift_id])]
                if shift_id in self.active_shifts else [],
            )
        elif "FROM dbo.ProductionLot AS lot WITH" in query:
            lot_matches = (
                self.lot_valid
                and params[:2] == (17701, self.lot_date)
                and (
                    "LTRIM(RTRIM(lot.Shift))=?" not in query
                    or params[2] == self.lot_shift_code
                )
            )
            self._set(
                ("ProductionID", "ProductFamilyID", "LotShiftCode"),
                [(17701, self.lot_family, self.lot_shift_code)]
                if lot_matches else [],
            )
        elif "FROM dbo.RejectReason AS reason" in query:
            family_id = params[-1]
            if self.reason_exists and family_id == self.reason_family:
                self._set(
                    ("RejectReasonID", "RejectSourceScopeID", "SourceScopeCode"),
                    [(901, 95, self.scope)],
                )
            else:
                self._set(
                    ("RejectReasonID", "RejectSourceScopeID", "SourceScopeCode"),
                    [],
                )
        elif "SELECT id AS EquipmentID,EquipmentCode" in query:
            self._set(("EquipmentID", "EquipmentCode"), [(620, "LINE2")])
        elif "FROM dbo.vw_PressMcPressList AS press_view" in query:
            values = [(711,)] if self.source_valid else []
            self._set(("EquipmentID",), values)
        elif query.lstrip().startswith("SELECT id AS EntryID"):
            table = "ProductionRejectEntry" if "ProductionRejectEntry" in query else "DepalletRejectEntry"
            if params[0] in self.existing_ids.get(table, set()):
                self._set(("EntryID",), [(params[0],)])
            else:
                self._set(("EntryID",), [])
        elif query.lstrip().startswith("INSERT INTO dbo."):
            self._set(("id",), [(16003,)])
        elif query.lstrip().startswith("UPDATE dbo."):
            self.rowcount = 1
            self._set((), [])
        elif "FROM dbo.ProductionRejectEntry AS entry" in query or \
                "FROM dbo.DepalletRejectEntry AS entry" in query:
            self._set(
                ("RejectReasonID", "ReasonCode", "ReasonNameTH",
                 "SortOrder", "Qty", "EntryCount"),
                [(901, "R319", "Configured line reason", 19, 6, 2)],
            )
        else:
            raise AssertionError(f"Unexpected SQL: {query}")
        return self

    def fetchall(self):
        result, self.result = self.result, []
        return result

    def fetchone(self):
        if not self.result:
            return None
        return self.result.pop(0)


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def valid_form(**changes):
    value = {
        "workflow": "production",
        "production_date": "2026-10-06",
        "shift_id": "734",
        "line_equipment_id": "620",
        "production_id": "17701",
        "source_equipment_id": "620",
        "reject_reason_id": "901",
        "reject_source_scope_id": "95",
        "qty": "4",
    }
    value.update(changes)
    return value


class RejectEntryTests(unittest.TestCase):
    def test_workflow_selects_only_its_own_transaction_table(self):
        for workflow, table in (
            ("production", "ProductionRejectEntry"),
            ("depallet", "DepalletRejectEntry"),
        ):
            with self.subTest(workflow=workflow):
                cursor = FakeCursor()
                connection = FakeConnection(cursor)
                entry_id = save_reject_entry(
                    connection, valid_form(workflow=workflow)
                )
                insert = next(
                    query for query, _ in cursor.calls
                    if query.lstrip().startswith("INSERT INTO dbo.")
                )
                self.assertIn(f"dbo.{table}", insert)
                self.assertNotIn("RejectOf", insert)
                self.assertNotIn("DepalletID", insert)
                self.assertEqual(entry_id, 16003)
                self.assertEqual(connection.commits, 1)

    def test_production_shift_does_not_have_to_match_lot_shift(self):
        cursor = FakeCursor()
        save_reject_entry(
            FakeConnection(cursor), valid_form(shift_id="733")
        )
        lot_query, lot_params = next(
            call for call in cursor.calls
            if "FROM dbo.ProductionLot AS lot WITH" in call[0]
        )
        self.assertNotIn("AND LTRIM(RTRIM(lot.Shift))=?", lot_query)
        self.assertEqual(lot_params, (17701, date(2026, 10, 6)))

    def test_same_production_lot_saves_rows_for_both_actual_shifts(self):
        cursor = FakeCursor(lot_shift_code="1")
        connection = FakeConnection(cursor)
        save_reject_entry(
            connection, valid_form(shift_id="733", qty="3")
        )
        save_reject_entry(
            connection, valid_form(shift_id="734", qty="4")
        )

        inserts = [
            params for query, params in cursor.calls
            if query.lstrip().startswith("INSERT INTO dbo.ProductionRejectEntry")
        ]
        self.assertEqual(len(inserts), 2)
        self.assertEqual([params[1] for params in inserts], [733, 734])
        self.assertEqual([params[5] for params in inserts], [17701, 17701])
        self.assertEqual([params[7] for params in inserts], [3, 4])
        self.assertEqual(connection.commits, 2)

    def test_wrong_production_date_is_rejected(self):
        cursor = FakeCursor(lot_date=date(2026, 10, 5))
        with self.assertRaisesRegex(RejectValidationError, "Production Date"):
            save_reject_entry(
                FakeConnection(cursor), valid_form()
            )
        self.assertFalse(any(
            query.lstrip().startswith("INSERT INTO dbo.")
            for query, _ in cursor.calls
        ))

    def test_inactive_or_nonexistent_production_id_is_rejected(self):
        cursor = FakeCursor(lot_valid=False)
        with self.assertRaisesRegex(RejectValidationError, "active Product / Lot"):
            save_reject_entry(FakeConnection(cursor), valid_form())
        self.assertFalse(any(
            query.lstrip().startswith("INSERT INTO dbo.")
            for query, _ in cursor.calls
        ))

    def test_inactive_or_nonexistent_shift_id_is_rejected(self):
        cursor = FakeCursor()
        with self.assertRaisesRegex(RejectValidationError, "Shift is no longer active"):
            save_reject_entry(
                FakeConnection(cursor), valid_form(shift_id="999")
            )
        self.assertFalse(any(
            query.lstrip().startswith("INSERT INTO dbo.")
            for query, _ in cursor.calls
        ))

    def test_depallet_lot_shift_matching_is_unchanged(self):
        cursor = FakeCursor(lot_shift_code="1")
        with self.assertRaisesRegex(RejectValidationError, "active Product / Lot"):
            save_reject_entry(
                FakeConnection(cursor),
                valid_form(workflow="depallet", shift_id="734"),
            )
        lot_query = next(
            query for query, _ in cursor.calls
            if "FROM dbo.ProductionLot AS lot WITH" in query
        )
        self.assertIn("LTRIM(RTRIM(lot.Shift))=?", lot_query)

    def test_family_and_reason_applicability_use_product_family_ids(self):
        cursor = FakeCursor()
        save_reject_entry(FakeConnection(cursor), valid_form())
        reason_query, reason_params = next(
            call for call in cursor.calls
            if "FROM dbo.RejectReason AS reason" in call[0]
        )
        self.assertIn("RejectReasonProductFamily", reason_query)
        self.assertEqual(reason_params, (901, 842))

    def test_wrong_family_reason_is_rejected(self):
        cursor = FakeCursor(reason_family=843)
        with self.assertRaisesRegex(RejectValidationError, "does not apply"):
            save_reject_entry(FakeConnection(cursor), valid_form())
        self.assertFalse(any(
            query.lstrip().startswith("INSERT INTO dbo.")
            for query, _ in cursor.calls
        ))

    def test_null_lot_family_fails_closed(self):
        cursor = FakeCursor(lot_family=None)
        with self.assertRaisesRegex(RejectValidationError, "no Product Family"):
            save_reject_entry(FakeConnection(cursor), valid_form())
        self.assertFalse(any(
            query.lstrip().startswith("INSERT INTO dbo.")
            for query, _ in cursor.calls
        ))

    def test_tampered_source_scope_is_rejected(self):
        cursor = FakeCursor(scope="LINE")
        with self.assertRaisesRegex(RejectValidationError, "does not match"):
            save_reject_entry(
                FakeConnection(cursor),
                valid_form(reject_source_scope_id="96"),
            )
        self.assertFalse(any(
            query.lstrip().startswith("INSERT INTO dbo.")
            for query, _ in cursor.calls
        ))

    def test_nonpositive_quantity_is_rejected_before_database_queries(self):
        cursor = FakeCursor()
        with self.assertRaisesRegex(RejectValidationError, "Qty"):
            save_reject_entry(FakeConnection(cursor), valid_form(qty="0"))
        self.assertEqual(cursor.calls, [])
        with self.assertRaises(RejectValidationError):
            save_reject_entry(FakeConnection(FakeCursor()), valid_form(qty="-1"))

    def test_line_scope_reason_requires_selected_line_as_source(self):
        cursor = FakeCursor(scope="LINE")
        save_reject_entry(FakeConnection(cursor), valid_form())
        self.assertFalse(any(
            "vw_PressMcPressList" in query
            for query, _ in cursor.calls
        ))
        with self.assertRaisesRegex(RejectValidationError, "selected Line"):
            save_reject_entry(
                FakeConnection(FakeCursor(scope="LINE")),
                valid_form(source_equipment_id="711"),
            )

    def test_press_scope_requires_active_press_mapped_to_selected_line(self):
        cursor = FakeCursor(scope="PRESS", source_valid=True)
        save_reject_entry(
            FakeConnection(cursor),
            valid_form(source_equipment_id="711", reject_source_scope_id="95"),
        )
        query, params = next(
            call for call in cursor.calls
            if "FROM dbo.vw_PressMcPressList AS press_view" in call[0]
        )
        self.assertIn("press.IsActive=1 AND press_view.IsActive=1", query)
        self.assertEqual(params, (711, 620))

    def test_cross_line_press_source_is_rejected(self):
        cursor = FakeCursor(scope="PRESS", source_valid=False)
        with self.assertRaisesRegex(RejectValidationError, "configured for"):
            save_reject_entry(
                FakeConnection(cursor),
                valid_form(source_equipment_id="711"),
            )

    def test_r319_is_a_line_reason_only_when_database_scope_says_line(self):
        cursor = FakeCursor(scope="LINE")
        save_reject_entry(FakeConnection(cursor), valid_form())
        reason_query = next(
            query for query, _ in cursor.calls
            if "FROM dbo.RejectReason AS reason" in query
        )
        self.assertIn("scope.SourceScopeCode", reason_query)
        self.assertNotIn("R319", reason_query)

    def test_repeated_identical_saves_are_allowed(self):
        cursor = FakeCursor()
        connection = FakeConnection(cursor)
        save_reject_entry(connection, valid_form())
        save_reject_entry(connection, valid_form())
        inserts = [
            query for query, _ in cursor.calls
            if query.lstrip().startswith("INSERT INTO dbo.")
        ]
        self.assertEqual(len(inserts), 2)
        self.assertEqual(connection.commits, 2)

    def test_edit_updates_same_id_without_replacing_it(self):
        cursor = FakeCursor(existing_ids={"ProductionRejectEntry": {44}})
        entry_id = save_reject_entry(
            FakeConnection(cursor), valid_form(entry_id="44", qty="7")
        )
        update, params = next(
            call for call in cursor.calls
            if call[0].lstrip().startswith("UPDATE dbo.")
        )
        self.assertIn("WHERE id=? AND ProductionDate=?", update)
        self.assertNotIn("SET id=", update)
        self.assertEqual(params[-2:], (44, date(2026, 10, 6)))
        self.assertEqual(entry_id, 44)

    def test_cross_workflow_edit_cannot_update_other_workflow_row(self):
        for workflow, other in (
            ("production", "DepalletRejectEntry"),
            ("depallet", "ProductionRejectEntry"),
        ):
            with self.subTest(workflow=workflow):
                cursor = FakeCursor(existing_ids={other: {44}})
                with self.assertRaisesRegex(RejectValidationError, "does not belong"):
                    save_reject_entry(
                        FakeConnection(cursor),
                        valid_form(workflow=workflow, entry_id="44"),
                    )
                self.assertFalse(any(
                    query.lstrip().startswith("UPDATE dbo.")
                    for query, _ in cursor.calls
                ))

    def test_page_choices_use_family_mapping_and_active_press_configuration(self):
        class PageCursor:
            def __init__(self):
                self.description = []
                self.result = []
                self.calls = []

            def execute(self, query, *params):
                self.calls.append((query, params))
                if "FROM dbo.ShiftMaster" in query:
                    self.set(("ShiftID", "ShiftCode", "ShiftName"), [
                        (734, "2", "Shift 2"),
                    ])
                elif "FROM dbo.EquipmentMaster" in query:
                    self.set(("EquipmentID", "EquipmentCode", "EquipmentName", "DisplayOrder"), [
                        (620, "LINE2", "Line 2", 2),
                    ])
                elif "FROM dbo.vw_PressMcPressList" in query:
                    self.set(("EquipmentID", "EquipmentCode", "EquipmentName",
                              "LineEquipmentID", "LineEquipmentCode", "DisplayOrder"), [
                        (711, "F7", "Press 7", 620, "LINE2", 7),
                    ])
                elif "FROM dbo.ProductionLot AS lot" in query:
                    self.set(("ProductionID", "ProductionDate", "LotShiftCode",
                              "ShiftID", "ShiftCode", "ProductFamilyID",
                              "ProductCode", "LotNo", "ProductFamily", "ProductName"), [
                        (17701, date(2026, 10, 6), "2", 734, "2",
                         842, "06", "LOT-1", "NeuFit / NeuStile", "Tile 6"),
                    ])
                elif "FROM dbo.RejectReason AS reason" in query:
                    self.set(("ProductFamilyID", "RejectReasonID", "ReasonCode",
                              "ReasonNameTH", "SortOrder", "RejectSourceScopeID",
                              "SourceScopeCode", "CatalogCode"), [
                        (842, 901, "R319", "Configured line reason", 19, 95, "LINE", "R3"),
                        (843, 902, "R319", "Other family reason", 19, 96, "PRESS", "R3"),
                    ])
                else:
                    raise AssertionError(query)
                return self

            def set(self, keys, values):
                self.description = [(key,) for key in keys]
                self.result = list(values)

            def fetchall(self):
                result, self.result = self.result, []
                return result

        cursor = PageCursor()
        data = read_reject_page_data(cursor, date(2026, 10, 6))
        context = reject_page_context(
            data, date(2026, 10, 6), shift_id=734,
            line_equipment_id=620, production_id=17701,
        )
        self.assertEqual(
            [reason["RejectReasonID"] for reason in context["reasons"]],
            [901],
        )
        self.assertEqual(
            [source["EquipmentCode"] for source in context["source_options"]],
            ["LINE2", "F7"],
        )
        reason_query = next(
            query for query, _ in cursor.calls
            if "FROM dbo.RejectReason AS reason" in query
        )
        self.assertIn("RejectReasonProductFamily", reason_query)
        press_query = next(
            query for query, _ in cursor.calls
            if "FROM dbo.vw_PressMcPressList" in query
        )
        self.assertIn("press_view.IsActive=1", press_query)
        self.assertIn("press.IsActive=1", press_query)

    def test_inactive_press_is_excluded_by_database_configuration(self):
        from pathlib import Path

        source = Path("app/reject.py").read_text(encoding="utf-8")
        press_query = source.split(
            "FROM dbo.vw_PressMcPressList AS press_view", 1
        )[1].split('""")', 1)[0]
        self.assertIn("press.IsActive=1", press_query)
        self.assertIn("press_view.IsActive=1", press_query)
        self.assertNotIn("F6", source)

    def test_client_source_data_retains_all_line_instance_relationships(self):
        base = dict(
            shifts=[dict(ShiftID=734, ShiftCode="2", ShiftName="Shift 2")],
            lines=[
                dict(EquipmentID=15, EquipmentCode="LINE1", EquipmentName="Line 1"),
                dict(EquipmentID=16, EquipmentCode="LINE2", EquipmentName="Line 2"),
            ],
            presses=[
                dict(EquipmentID=1, EquipmentCode="F1", EquipmentName="Press 1",
                     LineEquipmentID=15),
                dict(EquipmentID=12, EquipmentCode="F7", EquipmentName="Press 7",
                     LineEquipmentID=16),
                dict(EquipmentID=13, EquipmentCode="F8", EquipmentName="Press 8",
                     LineEquipmentID=16),
            ],
            lots=[
                dict(ProductionID=17701, ShiftID=734, ShiftCode="2",
                     ProductFamilyID=842, LotNo="LOT-1", ProductFamily="NeuFit",
                     ProductName="Product 1"),
            ],
            reasons=[
                dict(ProductFamilyID=842, RejectReasonID=901, ReasonCode="R301",
                     ReasonNameTH="Press reason", SortOrder=1,
                     RejectSourceScopeID=95, SourceScopeCode="PRESS",
                     CatalogCode="R3"),
            ],
        )
        context = reject_page_context(
            base, date(2026, 10, 6), shift_id=734,
            line_equipment_id=15, production_id=17701,
        )

        self.assertEqual(
            [(item["EquipmentID"], item["LineEquipmentID"])
             for item in context["source_options"]],
            [(15, 15), (1, 15)],
        )
        self.assertEqual(
            {(item["EquipmentID"], item["LineEquipmentID"])
             for item in context["reject_client_data"]["sources"]},
            {(15, 15), (1, 15), (16, 16), (12, 16), (13, 16)},
        )
        self.assertEqual(
            [item["LineEquipmentID"] for item in context["reject_client_data"]["sources"]
             if item["EquipmentType"] == "PRESS" and item["EquipmentCode"] == "F7"],
            [16],
        )

    def test_workflow_page_labels_are_presentation_only(self):
        base = dict(
            shifts=[dict(ShiftID=734, ShiftCode="2", ShiftName="Shift 2")],
            lines=[dict(EquipmentID=620, EquipmentCode="LINE2", EquipmentName="Line 2")],
            presses=[], lots=[], reasons=[],
        )
        production = reject_page_context(
            base, date(2026, 10, 6), workflow="production"
        )
        depallet = reject_page_context(
            base, date(2026, 10, 6), workflow="depallet"
        )
        self.assertEqual(production["workflow"], "production")
        self.assertEqual(depallet["workflow"], "depallet")
        self.assertEqual(production["source_options"][0]["EquipmentID"], 620)
        self.assertEqual(depallet["source_options"][0]["EquipmentID"], 620)
        self.assertEqual(base["lines"][0]["EquipmentCode"], "LINE2")

    def test_production_lot_is_not_filtered_by_transaction_shift(self):
        production_date = date(2026, 10, 6)
        base = dict(
            shifts=[
                dict(ShiftID=733, ShiftCode="1", ShiftName="Shift 1"),
                dict(ShiftID=734, ShiftCode="2", ShiftName="Shift 2"),
            ],
            lines=[], presses=[],
            lots=[
                dict(ProductionID=13, ProductionDate=production_date,
                     ShiftID=733, ShiftCode="1", ProductFamilyID=842,
                     ProductCode="06", LotNo="LOT-13",
                     ProductFamily="Family", ProductName="Product"),
            ],
            reasons=[],
        )
        production = reject_page_context(
            base, production_date, workflow="production", shift_id=734,
            production_id=13,
        )
        depallet = reject_page_context(
            base, production_date, workflow="depallet", shift_id=734,
            production_id=13,
        )
        self.assertEqual(
            [item["ProductionID"] for item in production["lots"]], [13]
        )
        self.assertEqual(production["selected_production_id"], "13")
        self.assertEqual(depallet["lots"], [])
        self.assertEqual(depallet["selected_production_id"], "")

    def test_no_numeric_id_or_reason_range_business_rules(self):
        from pathlib import Path

        source = Path("app/reject.py").read_text(encoding="utf-8")
        page = Path("app/reject_page.py").read_text(encoding="utf-8")
        self.assertNotRegex(source + page, r"ShiftID\s*==\s*\d+")
        self.assertNotRegex(source + page, r"ProductFamilyID\s*==\s*\d+")
        self.assertNotRegex(source + page, r"ReasonCode\s*(?:>=|<=|>|<)")
        self.assertNotIn("R319", source + page)


class RejectCalTests(unittest.TestCase):
    @staticmethod
    def request():
        return Request({
            "type": "http", "asgi": {"version": "3.0"},
            "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": "/reject/cal", "raw_path": b"/reject/cal",
            "query_string": b"", "headers": [],
            "server": ("localhost", 80), "client": ("127.0.0.1", 12345),
            "root_path": "",
        })

    def test_production_cal_route_keeps_same_lot_for_shift_one_and_two(self):
        production_date = date(2026, 10, 1)
        data = dict(
            shifts=[
                dict(ShiftID=11, ShiftCode="1", ShiftName="Shift 1"),
                dict(ShiftID=12, ShiftCode="2", ShiftName="Shift 2"),
            ],
            lots=[
                dict(ProductionID=13, ProductionDate=production_date,
                     ShiftID=11, ShiftCode="1", ProductFamilyID=84,
                     ProductCode="06", LotNo="I11691001",
                     ProductFamily="Angle Ridge", ProductName="Angle Ridge"),
            ],
        )
        for shift_id, shift_code, expected_rows, expected_total in (
            (11, "1", 5, 23),
            (12, "2", 2, 10),
        ):
            with self.subTest(shift=shift_code):
                connection = MagicMock()
                summary = dict(
                    workflow="production",
                    totals=[dict(ReasonCode="R201", ReasonNameTH="Reason",
                                 Qty=expected_total, EntryCount=expected_rows)],
                    total_qty=expected_total,
                    entry_count=expected_rows,
                )
                with patch("app.main.get_connection", return_value=connection), \
                     patch("app.main.read_reject_page_data", return_value=data), \
                     patch("app.main.read_reject_cal", return_value=summary) as cal:
                    response = reject_cal_page(
                        self.request(), production_date=production_date,
                        workflow="production", shift_id=shift_id,
                        production_id=13,
                    )
                self.assertEqual(response.status_code, 200)
                self.assertIn("I11691001", response.body.decode())
                self.assertIn(f"Shift {shift_code}", response.body.decode())
                self.assertIn(
                    f"shift_id={shift_id}&amp;production_id=13",
                    response.body.decode(),
                )
                self.assertEqual(
                    cal.call_args.args[3:], (shift_id, 13)
                )

    def test_depallet_cal_route_still_requires_lot_shift_match(self):
        production_date = date(2026, 10, 1)
        data = dict(
            shifts=[
                dict(ShiftID=11, ShiftCode="1", ShiftName="Shift 1"),
                dict(ShiftID=12, ShiftCode="2", ShiftName="Shift 2"),
            ],
            lots=[
                dict(ProductionID=13, ProductionDate=production_date,
                     ShiftID=11, ShiftCode="1", ProductFamilyID=84,
                     ProductCode="06", LotNo="I11691001",
                     ProductFamily="Angle Ridge", ProductName="Angle Ridge"),
            ],
        )
        with patch("app.main.get_connection", return_value=MagicMock()), \
             patch("app.main.read_reject_page_data", return_value=data), \
             patch("app.main.read_reject_cal") as cal:
            response = reject_cal_page(
                self.request(), production_date=production_date,
                workflow="depallet", shift_id=12, production_id=13,
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Select an active Product / Lot", response.body.decode())
        cal.assert_not_called()

    def test_production_cal_reads_only_production_entry_table(self):
        cursor = FakeCursor()
        result = read_reject_cal(
            cursor, date(2026, 10, 6), "production", "734", "17701"
        )
        query, params = cursor.calls[-1]
        self.assertIn("FROM dbo.ProductionRejectEntry AS entry", query)
        self.assertNotIn("DepalletRejectEntry", query)
        self.assertEqual(params, (date(2026, 10, 6), 734, 17701))
        self.assertEqual(result["table"], "ProductionRejectEntry")

    def test_production_cal_for_same_lot_is_independently_shift_specific(self):
        production_date = date(2026, 10, 1)

        class ShiftRowsCursor:
            def __init__(self):
                self.description = []
                self.result = []
                self.calls = []
                self.raw = [
                    (production_date, 11, 13, 301, "R201", "Reason 201", 1, 3),
                    (production_date, 11, 13, 304, "R204", "Reason 204", 2, 2),
                    (production_date, 11, 13, 307, "R207", "Reason 207", 3, 6),
                    (production_date, 11, 13, 308, "R208", "Reason 208", 4, 4),
                    (production_date, 11, 13, 312, "R212", "Reason 212", 5, 8),
                    (production_date, 12, 13, 301, "R201", "Reason 201", 1, 5),
                    (production_date, 12, 13, 302, "R202", "Reason 202", 2, 5),
                ]

            def execute(self, query, *params):
                self.calls.append((query, params))
                selected = [
                    row for row in self.raw
                    if row[0] == params[0] and row[1] == params[1]
                    and row[2] == params[2]
                ]
                grouped = {}
                for row in selected:
                    grouped.setdefault(row[3], [row[4], row[5], row[6], 0, 0])
                    grouped[row[3]][3] += row[7]
                    grouped[row[3]][4] += 1
                self.description = [
                    ("RejectReasonID",), ("ReasonCode",), ("ReasonNameTH",),
                    ("SortOrder",), ("Qty",), ("EntryCount",),
                ]
                self.result = [
                    (reason_id, *values)
                    for reason_id, values in grouped.items()
                ]

            def fetchall(self):
                result, self.result = self.result, []
                return result

        cursor = ShiftRowsCursor()
        shift_one = read_reject_cal(
            cursor, production_date, "production", 11, 13
        )
        shift_two = read_reject_cal(
            cursor, production_date, "production", 12, 13
        )
        self.assertEqual(
            [(row["ReasonCode"], row["Qty"], row["EntryCount"])
             for row in shift_one["totals"]],
            [("R201", 3, 1), ("R204", 2, 1), ("R207", 6, 1),
             ("R208", 4, 1), ("R212", 8, 1)],
        )
        self.assertEqual(shift_one["total_qty"], 23)
        self.assertEqual(shift_one["entry_count"], 5)
        self.assertEqual(
            [(row["ReasonCode"], row["Qty"], row["EntryCount"])
             for row in shift_two["totals"]],
            [("R201", 5, 1), ("R202", 5, 1)],
        )
        self.assertEqual(shift_two["total_qty"], 10)
        self.assertEqual(shift_two["entry_count"], 2)
        self.assertTrue(all(
            params == (production_date, shift_id, 13)
            for (_, params), shift_id in zip(cursor.calls, (11, 12))
        ))

    def test_depallet_cal_reads_only_depallet_entry_table(self):
        class CalCursor:
            def __init__(self):
                self.description = []
                self.result = []
                self.query = ""

            def execute(self, query, *params):
                self.query = query
                self.description = [
                    ("RejectReasonID",), ("ReasonCode",),
                    ("ReasonNameTH",), ("SortOrder",),
                    ("Qty",), ("EntryCount",),
                ]
                self.result = [(901, "R319", "Configured line reason", 19, 6, 2)]

            def fetchall(self):
                result, self.result = self.result, []
                return result

        cursor = CalCursor()
        result = read_reject_cal(
            cursor, date(2026, 10, 6), "depallet", 734, 17701
        )
        self.assertIn("FROM dbo.DepalletRejectEntry AS entry", cursor.query)
        self.assertNotIn("ProductionRejectEntry", cursor.query)
        self.assertEqual(result["total_qty"], 6)
        self.assertEqual(result["entry_count"], 2)


class RejectPageRenderTests(unittest.TestCase):
    def test_reject_and_cal_templates_render_without_inner_production_date(self):
        production_date = date(2026, 10, 6)
        data = dict(
            shifts=[dict(ShiftID=734, ShiftCode="2", ShiftName="Shift 2")],
            lines=[dict(EquipmentID=620, EquipmentCode="LINE2",
                        EquipmentName="Line 2", DisplayOrder=2)],
            presses=[dict(EquipmentID=711, EquipmentCode="F7",
                          EquipmentName="Press 7", LineEquipmentID=620,
                          LineEquipmentCode="LINE2", DisplayOrder=7)],
            lots=[dict(ProductionID=17701, ProductionDate=production_date,
                       ShiftID=734, ShiftCode="2", ProductFamilyID=842,
                       ProductCode="06", LotNo="LOT-1",
                       ProductFamily="NeuFit / NeuStile", ProductName="Tile 6"),
                  dict(ProductionID=17702, ProductionDate=production_date,
                       ShiftID=733, ShiftCode="1", ProductFamilyID=843,
                       ProductCode="07", LotNo="LOT-2",
                       ProductFamily="Other family", ProductName="Tile 7")],
            reasons=[dict(ProductFamilyID=842, RejectReasonID=901,
                          ReasonCode="R319", ReasonNameTH="Configured line reason",
                          SortOrder=19, RejectSourceScopeID=95,
                          SourceScopeCode="LINE", CatalogCode="R3"),
                     dict(ProductFamilyID=843, RejectReasonID=902,
                          ReasonCode="R401", ReasonNameTH="Other family reason",
                          SortOrder=20, RejectSourceScopeID=96,
                          SourceScopeCode="PRESS", CatalogCode="R3")],
        )
        page = reject_page_context(
            data, production_date, shift_id=734, line_equipment_id=620,
            production_id=17701, form={"source_equipment_id": "711"},
        )
        page_body = templates.get_template("reject.html").render(
            request=None, **page
        )
        self.assertIn(
            'name="production_date" id="reject-production-date" value="2026-10-06"',
            page_body,
        )
        self.assertEqual(page_body.count('type="date"'), 1)
        self.assertIn("Reject Of", page_body)
        self.assertIn("REJECT CAL", page_body)
        self.assertEqual(page["selected_source_id"], "711")
        self.assertLess(
            page_body.index('id="reject-source"'),
            page_body.index('id="reject-qty"'),
        )
        self.assertIn(
            'value="711" data-equipment-type="PRESS" selected',
            page_body,
        )
        self.assertEqual(
            [item["RejectReasonID"] for item in page["reject_client_data"]["reasons"]],
            [901, 902],
        )
        self.assertEqual(
            [item["ProductionID"] for item in page["reject_client_data"]["lots"]],
            [17701, 17702],
        )
        self.assertIn('id="reject-cal" type="button"', page_body)
        self.assertNotIn("<h1>REJECT</h1>", page_body)
        self.assertNotIn("New Fitting REJECT quantities are separate", page_body)

        cal_body = templates.get_template("reject_summary.html").render(
            request=None, page_title="REJECT CAL", active_tab="reject-cal",
            production_date=production_date, workflow="production",
            workflow_label="Production",
            shift=dict(ShiftID=734, ShiftName="Shift 2"),
            lot=dict(ProductionID=17701, LotNo="LOT-1",
                     ProductName="Tile 6", ProductFamily="NeuFit / NeuStile"),
            totals=[dict(ReasonCode="R319", ReasonNameTH="Configured line reason",
                         Qty=6, EntryCount=2)],
            total_qty=6, entry_count=2, error=None,
        )
        self.assertIn("REJECT CAL · Production</h1>", cal_body)
        self.assertIn("LOT-1 · Tile 6 · Shift 2 · 2026-10-06", cal_body)
        self.assertIn('id="reject-cal-back" type="button"', cal_body)
        self.assertNotIn("<h2>LOT-1", cal_body)
        self.assertIn("ProductionRejectEntry", cal_body)
        self.assertIn("Legacy Wet Reject / Depallet reject totals are not included.", cal_body)

    def test_reject_routes_are_registered_separately_from_reject_api(self):
        paths = {route.path for route in app.routes}
        self.assertIn("/reject", paths)
        self.assertIn("/reject/save", paths)
        self.assertIn("/reject/cal", paths)
        self.assertIn("/reject-api", paths)


if __name__ == "__main__":
    unittest.main()
