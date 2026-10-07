import unittest
from datetime import date

from app.depallet_reject_final import (
    read_depallet_reject_cal,
    read_depallet_reject_context,
    save_depallet_reject_final,
)


DAY = date(2026, 9, 23)
REASONS = [
    dict(RejectReasonID=201, ReasonCode="R201", ReasonNameTH="Reason 201", SortOrder=1),
    dict(RejectReasonID=202, ReasonCode="R202", ReasonNameTH="Reason 202", SortOrder=2),
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
        if "sp_getapplock" in query:
            self._set(("result",), [(0,)])
        elif "FROM dbo.Depallet AS d" in query:
            run = self.connection.runs.get(params[0])
            self._set(
                ("DepalletID", "ProductionID", "DepalletDate", "Shift",
                 "DepalletQty", "GoodQty", "LotNo", "ProductionLotDate",
                 "ProductFamilyID", "IsActive", "ShiftID", "ShiftCode"),
                [(run["DepalletID"], run["ProductionID"], run["DepalletDate"],
                  run["Shift"], run["DepalletQty"], run["GoodQty"], run["LotNo"],
                  run["ProductionLotDate"], run["ProductFamilyID"], run["IsActive"],
                  run["ShiftID"], run["ShiftCode"])] if run else [],
            )
        elif "FROM dbo.RejectReason AS reason" in query:
            self._set(
                ("RejectReasonID", "ReasonCode", "ReasonNameTH", "SortOrder"),
                [tuple(item[key] for key in (
                    "RejectReasonID", "ReasonCode", "ReasonNameTH", "SortOrder"
                )) for item in REASONS],
            )
        elif "COUNT_BIG(*) AS MismatchedRows" in query:
            run = self.connection.runs[params[0]]
            count = sum(
                1 for item in self.connection.raw
                if item["DepalletID"] == params[0]
                and (item["ProductionDate"] != run["DepalletDate"]
                     or item["ProductionID"] != run["ProductionID"]
                     or item["ShiftID"] != run["ShiftID"])
            )
            self._set(("MismatchedRows",), [(count,)])
        elif "SUM(CONVERT(bigint,Qty)) AS RawQty" in query:
            totals = {}
            for item in self.connection.raw:
                if (item["DepalletID"] == params[0]
                        and item["ProductionDate"] == params[1]
                        and item["ProductionID"] == params[2]
                        and item["ShiftID"] == params[3]):
                    reason_id = item["RejectReasonID"]
                    totals[reason_id] = totals.get(reason_id, 0) + item["Qty"]
            self._set(("RejectReasonID", "RawQty"), list(totals.items()))
        elif "FROM dbo.DepalletRejectFinal WITH" in query:
            final_id = self.connection.final_ids.get(params[0])
            self._set(
                ("DepalletRejectFinalID",),
                [(final_id,)] if final_id is not None else [],
            )
        elif "FROM dbo.DepalletRejectFinalDetail" in query and query.lstrip().startswith("SELECT"):
            final_id = params[0]
            details = self.connection.details.get(final_id, [])
            self._set(
                ("RejectReasonID", "RawQtyAtSave", "FinalQty"),
                [(item["RejectReasonID"], item["RawQtyAtSave"], item["FinalQty"])
                 for item in details],
            )
        elif "FROM dbo.DepalletRejectFinal" in query:
            final_id = self.connection.final_ids.get(params[0])
            final = self.connection.finals.get(final_id)
            self._set(
                ("DepalletRejectFinalID", "Remark"),
                [(final_id, final["Remark"])] if final else [],
            )
        elif "FROM dbo.Depallet AS run" in query:
            totals = {}
            for final_id, final in self.connection.finals.items():
                if final["DepalletDate"] != params[0]:
                    continue
                for item in self.connection.details.get(final_id, []):
                    reason_id = item["RejectReasonID"]
                    totals[reason_id] = totals.get(reason_id, 0) + item["FinalQty"]
            self._set(("RejectReasonID", "QtyPerDay"), list(totals.items()))
        elif query.lstrip().startswith("INSERT INTO dbo.DepalletRejectFinalDetail"):
            final_id, reason_id, raw_qty, final_qty = params
            self.connection.details.setdefault(final_id, []).append(dict(
                RejectReasonID=reason_id, RawQtyAtSave=raw_qty, FinalQty=final_qty
            ))
            self._set((), [])
        elif query.lstrip().startswith("INSERT INTO dbo.DepalletRejectFinal\n"):
            final_id = max(self.connection.finals, default=0) + 1
            final = dict(
                DepalletID=params[0], ProductionID=params[1],
                DepalletDate=params[2], Remark=params[3],
            )
            self.connection.final_ids[params[0]] = final_id
            self.connection.finals[final_id] = final
            self._set(("DepalletRejectFinalID",), [(final_id,)])
        elif query.lstrip().startswith("UPDATE dbo.DepalletRejectFinal"):
            final_id = params[-1]
            self.connection.finals[final_id].update(
                ProductionID=params[0], DepalletDate=params[1], Remark=params[2]
            )
            self._set((), [])
        elif query.lstrip().startswith("DELETE FROM dbo.DepalletRejectFinalDetail"):
            self.connection.details[params[0]] = []
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
        self.runs = {
            71: dict(
                DepalletID=71, ProductionID=7, DepalletDate=DAY, Shift="2",
                DepalletQty=100, GoodQty=90, LotNo="LOT-1",
                ProductionLotDate=DAY, ProductFamilyID=41, IsActive=True,
                ShiftID=12, ShiftCode="2",
            ),
            72: dict(
                DepalletID=72, ProductionID=7, DepalletDate=DAY, Shift="2",
                DepalletQty=80, GoodQty=75, LotNo="LOT-1",
                ProductionLotDate=DAY, ProductFamilyID=41, IsActive=True,
                ShiftID=12, ShiftCode="2",
            ),
        }
        self.raw = [
            dict(DepalletID=71, ProductionDate=DAY, ProductionID=7,
                 ShiftID=12, RejectReasonID=201, Qty=3, SourceEquipmentID=711),
            dict(DepalletID=71, ProductionDate=DAY, ProductionID=7,
                 ShiftID=12, RejectReasonID=201, Qty=2, SourceEquipmentID=None),
            dict(DepalletID=71, ProductionDate=DAY, ProductionID=7,
                 ShiftID=12, RejectReasonID=202, Qty=1, SourceEquipmentID=None),
            dict(DepalletID=72, ProductionDate=DAY, ProductionID=7,
                 ShiftID=12, RejectReasonID=201, Qty=9, SourceEquipmentID=None),
        ]
        self.final_ids = {}
        self.finals = {}
        self.details = {}
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self._cursor = FinalCursor(self)

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class DepalletRejectFinalTests(unittest.TestCase):
    def test_cal_is_exact_run_shift_scoped_and_includes_null_sources(self):
        connection = FinalConnection()
        result = read_depallet_reject_cal(connection.cursor(), 71, DAY, 12)

        self.assertEqual(result["quantities"], {201: 5, 202: 1})
        self.assertEqual(result["raw_total"], 6)
        self.assertEqual(result["total_reject"], 10)
        raw_query = next(
            query for query, _ in connection.calls
            if "SUM(CONVERT(bigint,Qty)) AS RawQty" in query
        )
        self.assertIn("WHERE DepalletID=?", raw_query)
        self.assertNotIn("SourceEquipmentID IS NOT NULL", raw_query)
        self.assertNotIn("SourceEquipmentID IS NULL", raw_query)

    def test_cal_for_second_run_excludes_raw_from_first_run(self):
        connection = FinalConnection()
        result = read_depallet_reject_cal(connection.cursor(), 72, DAY, 12)

        self.assertEqual(result["quantities"], {201: 9})
        self.assertEqual(result["raw_total"], 9)
        self.assertEqual(result["depallet_id"], 72)

    def test_save_persists_run_snapshot_and_upserts_same_header(self):
        connection = FinalConnection()
        first = save_depallet_reject_final(
            connection, 71,
            {"Remark": "checked", "Quantities": {"qty_201": "7", "qty_202": "1"}},
        )
        first_header_id = first["depallet_reject_final_id"]
        self.assertEqual(first["raw_total_qty_at_save"], 6)
        self.assertEqual(first["final_classified_qty_at_save"], 8)
        self.assertEqual(first["unclassified_qty_at_save"], 2)
        self.assertEqual(len(connection.finals), 1)
        self.assertEqual(len(connection.details[first_header_id]), 2)
        self.assertEqual(
            {item["RejectReasonID"]: item["RawQtyAtSave"]
             for item in connection.details[first_header_id]},
            {201: 5, 202: 1},
        )
        self.assertEqual(
            {item["RejectReasonID"]: item["FinalQty"]
             for item in connection.details[first_header_id]},
            {201: 7, 202: 1},
        )

        second = save_depallet_reject_final(
            connection, 71,
            {"Remark": "reconciled", "Quantities": {"qty_201": "8", "qty_202": "1"}},
        )
        self.assertEqual(second["depallet_reject_final_id"], first_header_id)
        self.assertEqual(len(connection.finals), 1)
        self.assertEqual(connection.finals[first_header_id]["Remark"], "reconciled")
        self.assertEqual(connection.commits, 2)
        self.assertEqual(connection.rollbacks, 0)
        self.assertEqual(len(connection.raw), 4)

    def test_context_loads_saved_run_final_and_qty_day_from_final(self):
        connection = FinalConnection()
        save_depallet_reject_final(
            connection, 71,
            {"Quantities": {"qty_201": "7", "qty_202": "1"}},
        )
        save_depallet_reject_final(
            connection, 72,
            {"Quantities": {"qty_201": "4", "qty_202": "0"}},
        )
        context = read_depallet_reject_context(connection.cursor(), 71)
        reasons = {item["RejectReasonID"]: item for item in context["depallet_reject_reasons"]}
        self.assertEqual(reasons[201]["FinalQty"], 7)
        self.assertEqual(reasons[201]["RawQtyAtSave"], 5)
        self.assertEqual(reasons[201]["QtyPerDay"], 11)
        self.assertEqual(reasons[202]["QtyPerDay"], 1)
        self.assertEqual(context["depallet_reject_total"], 10)
        self.assertEqual(context["depallet_reject_difference"], 2)

    def test_saving_one_run_does_not_change_the_other_runs_final(self):
        connection = FinalConnection()
        save_depallet_reject_final(
            connection, 71,
            {"Quantities": {"qty_201": "7", "qty_202": "1"}},
        )
        save_depallet_reject_final(
            connection, 72,
            {"Quantities": {"qty_201": "4", "qty_202": "0"}},
        )
        run_72_id = connection.final_ids[72]
        run_72_final = dict(connection.finals[run_72_id])
        run_72_details = list(connection.details[run_72_id])

        save_depallet_reject_final(
            connection, 71,
            {"Quantities": {"qty_201": "6", "qty_202": "2"}},
        )

        self.assertEqual(set(connection.final_ids), {71, 72})
        self.assertEqual(len(connection.finals), 2)
        self.assertEqual(connection.final_ids[72], run_72_id)
        self.assertEqual(connection.finals[run_72_id], run_72_final)
        self.assertEqual(connection.details[run_72_id], run_72_details)
        self.assertEqual(
            {item["RejectReasonID"]: item["FinalQty"]
             for item in connection.details[connection.final_ids[71]]},
            {201: 6, 202: 2},
        )
        self.assertEqual(len(connection.raw), 4)


if __name__ == "__main__":
    unittest.main()
