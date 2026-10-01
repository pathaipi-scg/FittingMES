"""Read-only daily production report data assembled from existing sources."""
from app.lots import rows
from app.prod_api import read_prod_records
from app.production_data import read_shift_rules, resolve_shift
from app.usage import read_usage_context


def read_print_prod_context(cursor, production_date):
    records = read_prod_records(cursor, production_date)
    shift_rules = read_shift_rules(cursor, production_date)
    for record in records:
        try:
            record["Shift"] = resolve_shift(production_date, record.get("ProductionStartTime"),
                                             record.get("Shift"), shift_rules)
        except (TypeError, ValueError):
            pass
    cursor.execute("""SELECT ProductFamily,ProductCode,ProductName
        FROM dbo.ProductCodeMaster WHERE IsActive=1""")
    product_names = {(row[0], row[1]): row[2] for row in cursor.fetchall()}
    for record in records:
        record["ProductName"] = product_names.get((record.get("ProductFamily"), record.get("ProductCode")))
    usage = read_usage_context(cursor, production_date)
    daily_totals = {field: sum(record.get(field) or 0 for record in records)
                    for field in ("PlanQty", "CounterQty", "CuringQty")}
    shifts = []
    for shift in usage["shifts"]:
        shift_records = [record for record in records if str(record.get("Shift")) == str(shift["shift"])]
        totals = {field: sum(record.get(field) or 0 for record in shift_records)
                  for field in ("PlanQty", "CounterQty", "CuringQty")}
        shifts.append(dict(shift=shift["shift"], records=shift_records, totals=totals,
                           materials=shift["materials"]))
    return dict(records=records, shifts=shifts, daily_totals=daily_totals,
                daily_materials=usage["daily"])