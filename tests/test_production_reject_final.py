import asyncio
import json
import unittest
from datetime import date
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch

from starlette.responses import HTMLResponse
from app.main import production_reject_cal_route, save_production_reject_final_route
from app.production_reject_final import (
    read_production_reject_cal,
    read_production_reject_context,
    save_production_reject_final,
)


DAY = date(2026, 10, 1)
REASONS = [
    dict(RejectReasonID=301, ReasonCode="R201", ReasonNameTH="Press defect", SortOrder=1),
    dict(RejectReasonID=302, ReasonCode="R202", ReasonNameTH="Line defect", SortOrder=2),
]


class FinalCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = []
        self.result = []
        self.rowcount = -1

    def _set(self, columns, values):
        self.description = [(column,) for column in columns]
        self.result = list(values)

    def execute(self, query, *params):
        self.connection.calls.append((query, params))
        if "FROM dbo.ProductionLot AS lot" in query:
            totals = {}
            for final in self.connection.finals.values():
                if not final["active"] or final["ProductionDate"] != params[0]:
                    continue
                for detail in self.connection.details.get(
                    final["ProductionRejectFinalID"], []
                ):
                    reason_id = detail["RejectReasonID"]
                    totals[reason_id] = totals.get(reason_id, 0) + detail["FinalQty"]
            self._set(
                ("RejectReasonID", "QtyPerDay"),
                list(totals.items()),
            )
        elif "FROM dbo.ProductionLot" in query:
            if self.connection.lot_active and params[0] == self.connection.production_id:
                self._set(
                    ("ProductionID", "ProductionDate", "ProductFamilyID", "LotNo"),
                    [(self.connection.production_id, self.connection.production_date,
                      self.connection.product_family_id, "LOT-1")],
                )
            else:
                self._set(
                    ("ProductionID", "ProductionDate", "ProductFamilyID", "LotNo"),
                    [],
                )
        elif "FROM dbo.RejectReason AS reason" in query:
            self._set(
                ("RejectReasonID", "ReasonCode", "ReasonNameTH", "SortOrder"),
                [tuple(reason[key] for key in
                      ("RejectReasonID", "ReasonCode", "ReasonNameTH", "SortOrder"))
                 for reason in self.connection.reasons],
            )
        elif "FROM dbo.ProductionData" in query:
            data = self.connection.production_data
            self._set(
                ("CounterQty", "CuringQty"),
                [(data["CounterQty"], data["CuringQty"])]
                if data is not None else [],
            )
        elif "COUNT_BIG(*) AS MismatchedDateCount" in query:
            count = sum(
                1 for item in self.connection.raw
                if item["ProductionID"] == params[0]
                and item["ProductionDate"] != params[1]
            )
            self._set(("MismatchedDateCount",), [(count,)])
        elif "SUM(CONVERT(bigint,Qty)) AS RawQty" in query:
            totals = {}
            for item in self.connection.raw:
                if (item["ProductionID"] == params[0]
                        and item["ProductionDate"] == params[1]):
                    reason_id = item["RejectReasonID"]
                    totals[reason_id] = totals.get(reason_id, 0) + item["Qty"]
            self._set(
                ("RejectReasonID", "RawQty"),
                list(totals.items()),
            )
        elif query.lstrip().startswith("DELETE FROM dbo.ProductionRejectFinalDetail"):
            self.connection.details[params[0]] = []
            self._set((), [])
        elif "FROM dbo.ProductionRejectFinalDetail" in query:
            self._set(
                ("RejectReasonID", "RawQtyAtSave", "FinalQty"),
                [(item["RejectReasonID"], item["RawQtyAtSave"], item["FinalQty"])
                 for item in self.connection.details.get(params[0], [])],
            )
        elif "FROM dbo.ProductionRejectFinal WITH" in query:
            final = self.connection.final_by_production.get(params[0])
            self._set(
                ("ProductionRejectFinalID",),
                [(final,)] if final is not None else [],
            )
        elif "FROM dbo.ProductionRejectFinal" in query:
            final_id = self.connection.final_by_production.get(params[0])
            if final_id is None:
                self._set(("ProductionRejectFinalID", "Remark"), [])
            else:
                final = self.connection.finals[final_id]
                self._set(
                    ("ProductionRejectFinalID", "Remark"),
                    [(final_id, final["Remark"])],
                )
        elif query.lstrip().startswith("INSERT INTO dbo.ProductionRejectFinalDetail"):
            final_id, reason_id, raw_qty, final_qty = params
            self.connection.details.setdefault(final_id, []).append(dict(
                ProductionRejectFinalID=final_id,
                RejectReasonID=reason_id,
                RawQtyAtSave=raw_qty,
                FinalQty=final_qty,
            ))
            self._set((), [])
        elif query.lstrip().startswith("INSERT INTO dbo.ProductionRejectFinal"):
            final_id = self.connection.next_final_id
            self.connection.next_final_id += 1
            production_id, production_date, remark, total, raw_total, classified, difference = params
            self.connection.final_by_production[production_id] = final_id
            self.connection.finals[final_id] = dict(
                ProductionRejectFinalID=final_id,
                ProductionID=production_id,
                ProductionDate=production_date,
                Remark=remark,
                TotalWetRejectAtSave=total,
                RawTotalQtyAtSave=raw_total,
                FinalClassifiedQtyAtSave=classified,
                UnclassifiedQtyAtSave=difference,
                active=True,
            )
            self._set(("ProductionRejectFinalID",), [(final_id,)])
        elif query.lstrip().startswith("UPDATE dbo.ProductionRejectFinal"):
            production_date, remark, total, raw_total, classified, difference, final_id = params
            self.connection.finals[final_id].update(
                ProductionDate=production_date,
                Remark=remark,
                TotalWetRejectAtSave=total,
                RawTotalQtyAtSave=raw_total,
                FinalClassifiedQtyAtSave=classified,
                UnclassifiedQtyAtSave=difference,
            )
            self._set((), [])
        else:
            raise AssertionError(f"Unexpected SQL: {query}")
        return self

    def fetchall(self):
        result, self.result = self.result, []
        return result

    def fetchone(self):
        return self.result.pop(0) if self.result else None


class FinalConnection:
    def __init__(self):
        self.production_id = 13
        self.production_date = DAY
        self.product_family_id = 84
        self.lot_active = True
        self.production_data = dict(CounterQty=25, CuringQty=5)
        self.reasons = list(REASONS)
        self.raw = []
        self.finals = {}
        self.final_by_production = {}
        self.details = {}
        self.next_final_id = 100
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self.cursor_instance = FinalCursor(self)

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def submit(**quantities):
    values = {"qty_301": "0", "qty_302": "0"}
    values.update(quantities)
    return {"Quantities": values, "Remark": "whole lot note"}


class ProductionRejectCalTests(unittest.TestCase):
    def test_cal_succeeds_when_all_raw_reasons_are_applicable(self):
        connection = FinalConnection()
        connection.raw = [
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=11,
                 SourceEquipmentID=71, LineEquipmentID=61,
                 RejectReasonID=301, Qty=3),
        ]
        result = read_production_reject_cal(
            connection.cursor_instance, 13, expected_date=DAY
        )
        self.assertEqual(result["quantities"], {301: 3})
        self.assertEqual(result["raw_total"], 3)

    def test_cal_rejects_stale_reason_without_returning_partial_totals(self):
        connection = FinalConnection()
        connection.raw = [
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=11,
                 SourceEquipmentID=71, LineEquipmentID=61,
                 RejectReasonID=301, Qty=3),
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=12,
                 SourceEquipmentID=72, LineEquipmentID=62,
                 RejectReasonID=999, Qty=4),
        ]
        with self.assertRaisesRegex(
            ValueError, r"RejectReasonID\(s\) 999.*valid/applicable"
        ):
            read_production_reject_cal(connection.cursor_instance, 13)
        self.assertFalse(any(
            query.lstrip().startswith(("INSERT ", "UPDATE ", "DELETE "))
            for query, _ in connection.calls
        ))

    def test_cal_sums_whole_lot_across_shifts_sources_and_lines(self):
        connection = FinalConnection()
        connection.raw = [
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=11,
                 SourceEquipmentID=71, LineEquipmentID=61,
                 RejectReasonID=301, Qty=3),
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=12,
                 SourceEquipmentID=72, LineEquipmentID=62,
                 RejectReasonID=301, Qty=2),
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=12,
                 SourceEquipmentID=73, LineEquipmentID=62,
                 RejectReasonID=302, Qty=4),
        ]
        result = read_production_reject_cal(
            connection.cursor_instance, 13, expected_date=DAY
        )
        self.assertEqual(result["quantities"], {301: 5, 302: 4})
        self.assertEqual(result["raw_total"], 9)
        raw_query = next(
            query for query, _ in connection.calls
            if "SUM(CONVERT(bigint,Qty)) AS RawQty" in query
        )
        self.assertIn("ProductionDate=?", raw_query)
        self.assertIn("ProductionID=?", raw_query)
        self.assertNotIn("ShiftID", raw_query)
        self.assertNotIn("SourceEquipmentID", raw_query)
        self.assertNotIn("LineEquipmentID", raw_query)
        self.assertEqual(connection.commits, 0)

    def test_cal_rejects_requested_or_raw_date_mismatch(self):
        connection = FinalConnection()
        with self.assertRaisesRegex(ValueError, "requested Production Date"):
            read_production_reject_cal(
                connection.cursor_instance, 13, expected_date=date(2026, 10, 2)
            )
        connection.raw = [
            dict(ProductionID=13, ProductionDate=date(2026, 9, 30),
                 ShiftID=11, SourceEquipmentID=71, LineEquipmentID=61,
                 RejectReasonID=301, Qty=1),
        ]
        with self.assertRaisesRegex(ValueError, "RAW REJECT entries"):
            read_production_reject_cal(connection.cursor_instance, 13)


class ProductionRejectFinalTests(unittest.TestCase):
    def test_load_uses_dynamic_reasons_saved_final_and_saved_daily_total(self):
        connection = FinalConnection()
        connection.final_by_production[13] = 100
        connection.finals[100] = dict(
            ProductionRejectFinalID=100, ProductionID=13,
            ProductionDate=DAY, Remark="Saved remark", active=True,
        )
        connection.details[100] = [
            dict(RejectReasonID=301, RawQtyAtSave=7, FinalQty=8),
            dict(RejectReasonID=302, RawQtyAtSave=1, FinalQty=2),
        ]
        context = read_production_reject_context(connection.cursor_instance, 13)
        self.assertEqual(
            [(row["RejectReasonID"], row["FinalQty"], row["QtyPerDay"])
             for row in context["production_reject_reasons"]],
            [(301, 8, 8), (302, 2, 2)],
        )
        self.assertEqual(context["production_reject_remark"], "Saved remark")
        self.assertEqual(context["production_reject_total"], 20)
        self.assertEqual(context["production_reject_final_classified"], 10)
        self.assertEqual(context["production_reject_difference"], 10)
        self.assertFalse(any(
            "ProductionRejectEntry" in query
            for query, _ in connection.calls
        ))

    def test_load_without_final_uses_zero_and_does_not_calculate_raw(self):
        connection = FinalConnection()
        connection.raw = [
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=12,
                 SourceEquipmentID=72, LineEquipmentID=62,
                 RejectReasonID=301, Qty=7),
        ]
        context = read_production_reject_context(connection.cursor_instance, 13)
        self.assertEqual(
            [row["FinalQty"] for row in context["production_reject_reasons"]],
            [0, 0],
        )
        self.assertFalse(context["production_reject_has_final"])
        self.assertFalse(any(
            "ProductionRejectEntry" in query
            for query, _ in connection.calls
        ))

    def test_saved_qty_day_aggregates_only_active_lots_for_lot_date(self):
        connection = FinalConnection()
        connection.final_by_production[13] = 100
        connection.finals[100] = dict(
            ProductionRejectFinalID=100, ProductionID=13,
            ProductionDate=DAY, Remark="", active=True,
        )
        connection.details[100] = [
            dict(RejectReasonID=301, RawQtyAtSave=3, FinalQty=4),
        ]
        context = read_production_reject_context(connection.cursor_instance, 13)
        self.assertEqual(
            context["production_reject_reasons"][0]["QtyPerDay"], 4
        )
        daily_query = next(
            query for query, _ in connection.calls
            if "SUM(detail.FinalQty) AS QtyPerDay" in query
        )
        self.assertIn("lot.IsActive=1", daily_query)
        self.assertIn("lot.ProdDate=?", daily_query)
        self.assertNotIn("ProductionRejectEntry", daily_query)

    def test_save_creates_header_and_complete_reason_snapshot_without_mutating_raw(self):
        connection = FinalConnection()
        connection.raw = [
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=11,
                 SourceEquipmentID=71, LineEquipmentID=61,
                 RejectReasonID=301, Qty=3),
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=12,
                 SourceEquipmentID=72, LineEquipmentID=62,
                 RejectReasonID=301, Qty=2),
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=12,
                 SourceEquipmentID=73, LineEquipmentID=62,
                 RejectReasonID=302, Qty=4),
        ]
        before = list(connection.raw)
        result = save_production_reject_final(
            connection, 13, submit(qty_301="7", qty_302="2")
        )
        self.assertEqual(result["production_reject_final_id"], 100)
        self.assertEqual(result["total_wet_reject"], 20)
        self.assertEqual(result["raw_total_qty_at_save"], 9)
        self.assertEqual(result["final_classified_qty_at_save"], 9)
        self.assertEqual(result["unclassified_qty_at_save"], 11)
        self.assertEqual(connection.final_by_production, {13: 100})
        self.assertEqual(
            connection.finals[100]["RawTotalQtyAtSave"],
            sum(item["RawQtyAtSave"] for item in connection.details[100]),
        )
        self.assertEqual(
            [(item["RejectReasonID"], item["RawQtyAtSave"], item["FinalQty"])
             for item in connection.details[100]],
            [(301, 5, 7), (302, 4, 2)],
        )
        self.assertEqual(connection.raw, before)
        self.assertEqual(connection.commits, 1)
        self.assertFalse(any(
            "WetReject" in query and "ProductionReject" not in query
            for query, _ in connection.calls
        ))

    def test_save_rejects_stale_raw_reason_without_changing_existing_final_or_raw(self):
        connection = FinalConnection()
        connection.final_by_production[13] = 100
        connection.finals[100] = dict(
            ProductionRejectFinalID=100,
            ProductionID=13,
            ProductionDate=DAY,
            Remark="Keep this",
            TotalWetRejectAtSave=20,
            RawTotalQtyAtSave=8,
            FinalClassifiedQtyAtSave=6,
            UnclassifiedQtyAtSave=14,
            active=True,
        )
        connection.details[100] = [
            dict(ProductionRejectFinalID=100, RejectReasonID=301,
                 RawQtyAtSave=8, FinalQty=6),
            dict(ProductionRejectFinalID=100, RejectReasonID=302,
                 RawQtyAtSave=0, FinalQty=0),
        ]
        connection.raw = [
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=11,
                 SourceEquipmentID=71, LineEquipmentID=61,
                 RejectReasonID=301, Qty=3),
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=12,
                 SourceEquipmentID=72, LineEquipmentID=62,
                 RejectReasonID=999, Qty=4),
        ]
        original_header = dict(connection.finals[100])
        original_details = [dict(item) for item in connection.details[100]]
        original_raw = [dict(item) for item in connection.raw]
        with self.assertRaisesRegex(ValueError, r"RejectReasonID\(s\) 999"):
            save_production_reject_final(
                connection, 13, submit(qty_301="3", qty_302="1")
            )
        self.assertEqual(connection.finals[100], original_header)
        self.assertEqual(connection.details[100], original_details)
        self.assertEqual(connection.raw, original_raw)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertFalse(any(
            query.lstrip().startswith(("INSERT ", "UPDATE ", "DELETE "))
            and "ProductionRejectFinal" in query
            for query, _ in connection.calls
        ))

    def test_save_stores_zero_raw_and_final_for_every_applicable_reason(self):
        connection = FinalConnection()
        connection.raw = [
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=11,
                 SourceEquipmentID=71, LineEquipmentID=61,
                 RejectReasonID=301, Qty=3),
        ]
        save_production_reject_final(
            connection, 13, submit(qty_301="1", qty_302="0")
        )
        details = {
            item["RejectReasonID"]: item
            for item in connection.details[100]
        }
        self.assertEqual(set(details), {301, 302})
        self.assertEqual(details[302]["RawQtyAtSave"], 0)
        self.assertEqual(details[302]["FinalQty"], 0)
        self.assertEqual(
            connection.finals[100]["RawTotalQtyAtSave"],
            sum(item["RawQtyAtSave"] for item in details.values()),
        )

    def test_resave_replaces_same_final_and_daily_contribution(self):
        connection = FinalConnection()
        first = save_production_reject_final(
            connection, 13, submit(qty_301="5", qty_302="2")
        )
        second = save_production_reject_final(
            connection, 13, submit(qty_301="6", qty_302="3")
        )
        self.assertEqual(first["production_reject_final_id"], 100)
        self.assertEqual(second["production_reject_final_id"], 100)
        self.assertEqual(len(connection.finals), 1)
        self.assertEqual(
            sum(item["FinalQty"] for item in connection.details[100]), 9
        )
        self.assertEqual(connection.commits, 2)

    def test_final_total_cannot_exceed_total_wet_reject(self):
        connection = FinalConnection()
        with self.assertRaisesRegex(ValueError, "exceeds Total Wet Reject"):
            save_production_reject_final(
                connection, 13, submit(qty_301="15", qty_302="6")
            )
        self.assertEqual(connection.finals, {})


    def test_invalid_or_nonapplicable_reason_is_rejected(self):
        connection = FinalConnection()
        with self.assertRaisesRegex(ValueError, "inactive or does not apply"):
            save_production_reject_final(
                connection, 13,
                {"Quantities": {"qty_301": "1", "qty_999": "0"}, "Remark": ""},
            )
        self.assertEqual(connection.finals, {})
        self.assertEqual(connection.rollbacks, 1)

    def test_all_applicable_reasons_must_be_submitted(self):
        connection = FinalConnection()
        with self.assertRaisesRegex(ValueError, "every active Reject Reason"):
            save_production_reject_final(
                connection, 13,
                {"Quantities": {"qty_301": "1"}, "Remark": ""},
            )
        self.assertEqual(connection.finals, {})

    def test_invalid_negative_or_fractional_qty_is_rejected(self):
        for value in ("-1", "1.5", "", "2147483648"):
            with self.subTest(value=value):
                connection = FinalConnection()
                with self.assertRaisesRegex(ValueError, "Qty"):
                    save_production_reject_final(
                        connection, 13, submit(qty_301=value)
                    )
                self.assertEqual(connection.finals, {})

    def test_inconsistent_production_counters_block_final_save(self):
        connection = FinalConnection()
        connection.production_data = dict(CounterQty=3, CuringQty=4)
        with self.assertRaisesRegex(ValueError, "Curing Qty exceeds Counter Qty"):
            save_production_reject_final(
                connection, 13, submit(qty_301="1")
            )
        self.assertEqual(connection.finals, {})
        self.assertEqual(connection.rollbacks, 1)

    def test_missing_production_or_inactive_lot_blocks_save(self):
        for setup in ("missing_data", "inactive_lot"):
            with self.subTest(setup=setup):
                connection = FinalConnection()
                if setup == "missing_data":
                    connection.production_data = None
                else:
                    connection.lot_active = False
                with self.assertRaises(ValueError):
                    save_production_reject_final(connection, 13, submit())
                self.assertEqual(connection.finals, {})


class ProductionRejectRouteTests(unittest.TestCase):
    def test_cal_route_returns_whole_lot_totals_without_a_commit(self):
        connection = FinalConnection()
        connection.raw = [
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=11,
                 SourceEquipmentID=71, LineEquipmentID=61,
                 RejectReasonID=301, Qty=3),
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=12,
                 SourceEquipmentID=72, LineEquipmentID=62,
                 RejectReasonID=301, Qty=2),
        ]
        with patch("app.main.get_connection", return_value=connection):
            response = production_reject_cal_route(13, DAY)
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["quantities"], {"301": 5})
        self.assertEqual(payload["raw_total"], 5)
        self.assertEqual(payload["total_wet_reject"], 20)
        self.assertEqual(connection.commits, 0)

    def test_cal_route_returns_only_clear_error_for_stale_raw_reason(self):
        connection = FinalConnection()
        connection.raw = [
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=11,
                 SourceEquipmentID=71, LineEquipmentID=61,
                 RejectReasonID=301, Qty=3),
            dict(ProductionID=13, ProductionDate=DAY, ShiftID=12,
                 SourceEquipmentID=72, LineEquipmentID=62,
                 RejectReasonID=999, Qty=4),
        ]
        with patch("app.main.get_connection", return_value=connection):
            response = production_reject_cal_route(13, DAY)
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 400)
        self.assertIn("RejectReasonID(s) 999", payload["error"])
        self.assertNotIn("quantities", payload)
        self.assertNotIn("raw_total", payload)
        self.assertEqual(connection.commits, 0)

    def test_save_route_redirects_to_authoritative_date_after_success(self):
        class Form:
            def multi_items(self):
                return [("remark", "memo"), ("qty_301", "3"), ("qty_302", "4")]

            def get(self, key, default=None):
                return {"remark": "memo"}.get(key, default)

        class Request:
            async def form(self):
                return Form()

        with patch(
            "app.main.save_production_reject_final_change",
            return_value=dict(production_date=DAY),
        ) as save:
            response = asyncio.run(save_production_reject_final_route(Request(), 13))
        query = parse_qs(urlsplit(response.headers["location"]).query)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(query["production_id"], ["13"])
        self.assertEqual(query["production_date"], [DAY.isoformat()])
        self.assertEqual(query["production_reject_message_type"], ["success"])
        self.assertEqual(
            save.call_args.args[1],
            dict(Quantities={"qty_301": "3", "qty_302": "4"}, Remark="memo"),
        )

    def test_failed_save_rerenders_with_submitted_qty_and_explicit_error(self):
        class Form:
            def multi_items(self):
                return [("remark", "memo"), ("qty_301", "x"), ("qty_302", "4")]

            def get(self, key, default=None):
                return {"remark": "memo"}.get(key, default)

        class Request:
            async def form(self):
                return Form()

        with patch(
            "app.main.save_production_reject_final_change",
            side_effect=ValueError("Reject Qty must be whole."),
        ), patch(
            "app.main.production_page",
            return_value=HTMLResponse("error", status_code=200),
        ) as render:
            response = asyncio.run(save_production_reject_final_route(Request(), 13))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            render.call_args.kwargs["production_reject_form"],
            dict(Quantities={"qty_301": "x", "qty_302": "4"}, Remark="memo"),
        )
        self.assertEqual(
            render.call_args.kwargs["production_reject_message"],
            "Reject Qty must be whole.",
        )
