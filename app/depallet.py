"""Depallet entry using the existing schema; no DDL or PIS writes."""
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from app.lots import rows, lock_lots, day

MAX_QTY = 2147483647
MANUAL_CODES = frozenset(f'R{i:02d}' for i in range(1, 25))


def read_day_start_time(cursor, production_date):
    cursor.execute("""SELECT TOP (1) DayStartTime FROM dbo.ProductionDayRuleHistory
        WHERE EffectiveFromDate<=? ORDER BY EffectiveFromDate DESC,RuleID DESC""", production_date)
    found = cursor.fetchone()
    if not found:
        raise ValueError('No Production Day rule exists for this Production Date.')
    if not isinstance(found[0], time):
        raise ValueError('The effective Production Day rule has an invalid DayStartTime.')
    return found[0]


def production_clock_datetime(production_date, clock_value, day_start_time):
    value = str(clock_value or '').strip()
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
        raise ValueError('Start and End must use HH:mm (24-hour time).')
    clock = time.fromisoformat(value)
    calendar_date = production_date + timedelta(days=1) if clock < day_start_time else production_date
    return datetime.combine(calendar_date, clock)


def resolve_run_times(production_date, start_value, end_value, day_start_time, allow_missing=False):
    start_value = str(start_value or '').strip()
    end_value = str(end_value or '').strip()
    if not start_value and not end_value:
        return None, None
    if not start_value or not end_value:
        raise ValueError('Enter both Start and End times for this Depallet run.')
    start = production_clock_datetime(production_date, start_value, day_start_time)
    end = production_clock_datetime(production_date, end_value, day_start_time)
    if end < start:
        raise ValueError('End time must be at or after Start within the selected Production Date.')
    return start, end


def clock_display(value):
    return value.strftime('%H:%M') if value is not None else ''


def read_reasons(cursor, include_r99=False):
    cursor.execute("""SELECT ReasonCode,ReasonNameTH,SortOrder,IsActive FROM dbo.RejectReasonMaster
        WHERE IsActive=1 ORDER BY SortOrder,ReasonCode""")
    return [r for r in rows(cursor) if r['ReasonCode'] in MANUAL_CODES or (include_r99 and r['ReasonCode'] == 'R99')]


def read_curing_lots(cursor):
    cursor.execute("""SELECT b.ProductionID,b.ProdDate,b.Shift,b.PlanName,p.ProductFamily,
        b.MaterialCode,b.MaterialName,b.ProductCode,b.LotPrefix,b.LotNo,
        b.ProductionQty,b.DepalletQtyTotal,b.RemainingCuringQty,b.DepalletCount,
        b.FirstDepalletDate,b.LastDepalletDate,p.RunningNo AS RunNo,pm.ProductName
        FROM dbo.vw_DepalletCuringBalance b
        JOIN dbo.ProductionLot p ON p.ProductionID=b.ProductionID AND p.IsActive=1
        LEFT JOIN dbo.ProductCodeMaster pm ON pm.ProductFamily=p.ProductFamily
            AND pm.ProductCode=b.ProductCode
        ORDER BY b.ProdDate DESC,p.RunningNo DESC,b.ProductionID DESC""")
    return rows(cursor)


def read_daily_work(cursor, production_date, lots):
    reasons = read_reasons(cursor, include_r99=True)
    day_start_time = read_day_start_time(cursor, production_date)
    cursor.execute("""SELECT v.*,d.RunSequence,d.StartDateTime,d.EndDateTime,
        b.ProductionQty,b.DepalletQtyTotal,b.RemainingCuringQty,p.RunningNo AS RunNo,
        pm.ProductName,p.ProductFamily,
                ISNULL((SELECT SUM(prior.DepalletQty) FROM dbo.Depallet prior
            WHERE prior.ProductionID=d.ProductionID
              AND (prior.DepalletDate<d.DepalletDate
                                     OR (prior.DepalletDate=d.DepalletDate AND prior.RunSequence<d.RunSequence))),0)
            AS AlreadyDepalletedBeforeRun
        FROM dbo.vw_DepalletValidation v
        JOIN dbo.Depallet d ON d.DepalletID=v.DepalletID
        LEFT JOIN dbo.vw_DepalletCuringBalance b ON b.ProductionID=v.ProductionID
        LEFT JOIN dbo.ProductionLot p ON p.ProductionID=v.ProductionID
        LEFT JOIN dbo.ProductCodeMaster pm ON pm.ProductFamily=p.ProductFamily AND pm.ProductCode=v.ProductCode
        WHERE v.DepalletDate=? ORDER BY d.RunSequence,d.DepalletID""", production_date)
    saved = rows(cursor)

    cursor.execute("""SELECT r.DepalletID,r.ReasonCode,r.Qty,m.ReasonNameTH,m.IsActive,m.SortOrder
        FROM dbo.DepalletReject r
        JOIN dbo.Depallet d ON d.DepalletID=r.DepalletID
        LEFT JOIN dbo.RejectReasonMaster m ON m.ReasonCode=r.ReasonCode
        WHERE d.DepalletDate=? ORDER BY d.ProductionID,d.DepalletID,m.SortOrder,r.ReasonCode""", production_date)
    daily_rejects = rows(cursor)
    daily_totals = {}
    rejects_by_depallet = {}
    for reject in daily_rejects:
        code = reject['ReasonCode']
        daily_totals[code] = daily_totals.get(code, 0) + reject['Qty']
        rejects_by_depallet.setdefault(reject['DepalletID'], {})[code] = reject['Qty']
        if (code in MANUAL_CODES and not any(reason['ReasonCode'] == code for reason in reasons)):
            reasons.append(dict(ReasonCode=code, ReasonNameTH=reject['ReasonNameTH'],
                                IsActive=reject['IsActive'], SortOrder=reject['SortOrder']))

    entries = {str(lot['ProductionID']):dict(depallet=default_entry(lot, production_date),
        reject_values={},inactive_rejects=[],original_reject_values={},original_r99=0)
        for lot in lots}
    runs = []
    for lot in lots:
        saved_for_lot = [entry for entry in saved if entry['ProductionID'] == lot['ProductionID']]
        for entry in saved_for_lot:
            entry.update(LotNo=lot['LotNo'],ProductCode=lot['ProductCode'],
                         ProductFamily=lot.get('ProductFamily'),ProductName=lot.get('ProductName'))
            rejects = rejects_by_depallet.get(entry['DepalletID'], {})
            entry.update(summary(entry['DepalletQty'], entry['GoodQty'], rejects))
            already = int(entry.get('AlreadyDepalletedBeforeRun') or 0)
            entry['AlreadyDepalletedBeforeRun'] = already
            entry['RemainingCuringBeforeRun'] = max(int(entry.get('ProductionQty') or 0) - entry['AlreadyDepalletedBeforeRun'], 0)
            run_entry = dict(
                depallet=entry,
                reject_values={code: qty for code, qty in rejects.items() if code in MANUAL_CODES
                               and next((reason['IsActive'] for reason in reasons
                                         if reason['ReasonCode'] == code), False)},
                inactive_rejects=[dict(reason, Qty=rejects[reason['ReasonCode']])
                    for reason in reasons if reason['ReasonCode'] in rejects
                    and reason['ReasonCode'] in MANUAL_CODES and not reason['IsActive']],
                original_reject_values={code: qty for code, qty in rejects.items() if code in MANUAL_CODES},
                original_r99=rejects.get('R99', 0),
            )
            run_key = f"run:{entry['DepalletID']}"
            entries[run_key] = run_entry
            runs.append(dict(entry, run_key=run_key, reject_values=run_entry['reject_values'],
                             inactive_rejects=run_entry['inactive_rejects'],
                             original_reject_values=run_entry['original_reject_values'],
                             original_r99=run_entry['original_r99'],
                             StartClock=clock_display(entry.get('StartDateTime')),
                             EndClock=clock_display(entry.get('EndDateTime'))))
    runs.sort(key=lambda row:(row['RunSequence'],row['DepalletID']))
    for index, run in enumerate(runs):
        run['CanMoveUp'] = index > 0
        run['CanMoveDown'] = index < len(runs) - 1
    return entries, runs, reasons, daily_totals, day_start_time


def summary(quantity, good, rejects):
    classified = sum(qty for code, qty in rejects.items() if code in MANUAL_CODES)
    physical = quantity - good
    difference = physical - classified
    r99 = max(difference, 0)
    total = classified + r99
    return dict(PhysicalRejectQty=physical, ClassifiedRejectQty=classified,
                R99=r99, DifferenceQty=difference, IsBalanced=difference == 0,
                RejectQty=total, RejectPct=Decimal(total) * 100 / quantity if quantity else Decimal(0),
                AccountedQty=good + total)


def default_entry(lot, depallet_date):
    return dict(ProductionID=lot['ProductionID'], DepalletDate=depallet_date,
                Shift=lot.get('Shift') or '', LotNo=lot['LotNo'],
                DepalletQty='', GoodQty='', Remark='')


def read_rejects(cursor, depallet_id):
    cursor.execute("""SELECT r.ReasonCode,r.Qty,m.ReasonNameTH,m.IsActive,m.SortOrder
        FROM dbo.DepalletReject r LEFT JOIN dbo.RejectReasonMaster m ON m.ReasonCode=r.ReasonCode
        WHERE r.DepalletID=? ORDER BY m.SortOrder,r.ReasonCode""", depallet_id)
    return rows(cursor)


def read_context(cursor, lot, depallet_date=None, depallet_id=None):
    reasons = read_reasons(cursor)
    if depallet_id is not None:
        cursor.execute("""SELECT * FROM dbo.vw_DepalletValidation
            WHERE ProductionID=? AND DepalletID=? ORDER BY DepalletDate""",
            lot['ProductionID'], depallet_id)
    elif depallet_date is None:
        cursor.execute("""SELECT * FROM dbo.vw_DepalletValidation
            WHERE ProductionID=? ORDER BY DepalletDate,DepalletID""", lot['ProductionID'])
    else:
        cursor.execute("""SELECT * FROM dbo.vw_DepalletValidation
            WHERE ProductionID=? AND DepalletDate=? ORDER BY DepalletID""", lot['ProductionID'], depallet_date)
    found = rows(cursor)
    if depallet_date is None and len(found) > 1:
        # Records are date-keyed: require an explicit date rather than choosing one.
        return dict(depallet=default_entry(lot, ''), reject_reasons=reasons,
                    reject_values={}, inactive_rejects=[],
                    depallet_dates=sorted({day(entry['DepalletDate']) for entry in found}))
    if len(found) > 1:
        raise ValueError('Multiple Depallet runs exist for this Lot. Select a DepalletID before editing.')
    entry = found[0] if found else default_entry(lot, depallet_date if depallet_date is not None else day(lot['ProdDate']))
    rejects = read_rejects(cursor, entry['DepalletID']) if found else []
    if found:
        entry.update(summary(entry['DepalletQty'], entry['GoodQty'],
                             {r['ReasonCode']: r['Qty'] for r in rejects}))
    return dict(depallet=entry, reject_reasons=reasons,
                reject_values={r['ReasonCode']: r['Qty'] for r in rejects if r['ReasonCode'] in MANUAL_CODES},
                inactive_rejects=[r for r in rejects if not r['IsActive'] and r['ReasonCode'] in MANUAL_CODES])


def quantity(value, label, blank_zero=False):
    text = str(value if value is not None else '').strip()
    if not text and blank_zero:
        return 0
    if not re.fullmatch(r'[0-9]+', text) or len(text) > 10 or int(text) > MAX_QTY:
        raise ValueError(label + ' must be whole pieces from 0 to 2147483647.')
    return int(text)


def validate(raw, active_codes, retained=None):
    active_codes = set(active_codes) & MANUAL_CODES
    retained = {code: qty for code, qty in (retained or {}).items() if code in MANUAL_CODES}
    try:
        depallet_date = date.fromisoformat(str(raw.get('DepalletDate', '')))
    except ValueError:
        raise ValueError('Enter a valid Depallet Date.') from None
    shift = str(raw.get('Shift') or '').strip()
    lot_no = str(raw.get('LotNo') or '').strip()
    remark = str(raw.get('Remark') or '').strip()
    if not shift or not shift.isascii() or len(shift) > 10:
        raise ValueError('Depallet Shift is required (maximum 10 ASCII characters).')
    if not lot_no or not lot_no.isascii() or len(lot_no) > 50:
        raise ValueError('Depallet Lot is required (maximum 50 ASCII characters).')
    if len(remark.encode('utf-16-le')) // 2 > 500:
        raise ValueError('Depallet Remark must be at most 500 characters.')
    supplied = raw.get('rejects', {})
    if not isinstance(supplied, dict):
        raise ValueError('Invalid reject quantities.')
    if set(supplied) - active_codes - {'R99'}:
        raise ValueError('Reject reasons changed or are invalid. Reload the Depallet date.')
    rejects = {code: quantity(supplied.get(code, ''), code, blank_zero=True) for code in active_codes}
    rejects = {code: qty for code, qty in rejects.items() if qty}
    rejects.update(retained)
    data = dict(DepalletDate=depallet_date, Shift=shift, LotNo=lot_no,
                DepalletQty=quantity(raw.get('DepalletQty'), 'Depallet Qty'),
                GoodQty=quantity(raw.get('GoodQty'), 'Good Qty'), Remark=remark)
    if data['GoodQty'] > data['DepalletQty']:
        raise ValueError('Good Qty cannot exceed Depallet Qty.')
    total_reject = data['DepalletQty'] - data['GoodQty']
    classified = sum(qty for code, qty in rejects.items() if code in MANUAL_CODES)
    if classified > total_reject:
        raise ValueError(f'Classified Reject {classified} exceeds Total Reject {total_reject}.')
    # R99 is derived independently of any client or previously stored value.
    r99 = total_reject - classified
    if r99:
        rejects['R99'] = r99
    return data, rejects


def _save_depallet_locked(cursor, production_id, raw, day_start_time=None):
    cursor.execute('SELECT * FROM dbo.ProductionLot WITH (UPDLOCK,HOLDLOCK) WHERE ProductionID=? AND IsActive=1', production_id)
    lots = rows(cursor)
    if not lots:
        raise ValueError('This Production Lot is no longer active.')
    lot = lots[0]
    cursor.execute("""SELECT ProductionID,ProductionQty,DepalletQtyTotal,RemainingCuringQty
        FROM dbo.vw_DepalletCuringBalance WHERE ProductionID=?""", production_id)
    balances = rows(cursor)
    if not balances:
        raise ValueError('Production data is unavailable for this Lot.')
    balance = balances[0]
    reasons = read_reasons(cursor)
    active_codes = {reason['ReasonCode'] for reason in reasons}
    try:
        selected_date = date.fromisoformat(str(raw.get('DepalletDate', '')))
    except ValueError:
        raise ValueError('Enter a valid Depallet Date.') from None
    requested_id = raw.get('DepalletID')
    if requested_id in ('', None):
        depallet_id = None
        old_quantity = 0
        old_start = old_end = None
    else:
        try:
            depallet_id = int(requested_id)
        except (TypeError, ValueError):
            raise ValueError('Invalid Depallet run selection.') from None
        cursor.execute("""SELECT DepalletID,DepalletQty,StartDateTime,EndDateTime
            FROM dbo.Depallet WITH (UPDLOCK,HOLDLOCK)
            WHERE DepalletID=? AND ProductionID=? AND DepalletDate=?""",
            depallet_id, production_id, selected_date)
        existing = cursor.fetchone()
        if not existing:
            raise ValueError('This Depallet run no longer exists for the selected Production Date.')
        old_quantity, old_start, old_end = existing[1], existing[2], existing[3]
    old_rejects = read_rejects(cursor, depallet_id) if depallet_id is not None else []
    retained = {r['ReasonCode']: r['Qty'] for r in old_rejects if r['ReasonCode'] not in active_codes}
    authoritative = dict(raw, LotNo=lot['LotNo'])
    data, rejects = validate(authoritative, active_codes, retained)
    if day_start_time is None:
        day_start_time = read_day_start_time(cursor, selected_date)
    start_datetime, end_datetime = resolve_run_times(
        selected_date, raw.get('Start'), raw.get('End'), day_start_time,
        allow_missing=True)
    data['StartDateTime'] = start_datetime
    data['EndDateTime'] = end_datetime
    max_quantity = int(balance['RemainingCuringQty']) + int(old_quantity)
    if data['DepalletQty'] > max_quantity:
        raise ValueError(f"Depallet Qty {data['DepalletQty']} exceeds Remaining Curing Qty {max_quantity}.")
    if depallet_id is None:
        cursor.execute("""SELECT ISNULL(MAX(RunSequence),0)+1
            FROM dbo.Depallet WITH (UPDLOCK,HOLDLOCK) WHERE DepalletDate=?""", selected_date)
        run_sequence = int(cursor.fetchone()[0])
        cursor.execute("""INSERT INTO dbo.Depallet
            (ProductionID,DepalletDate,Shift,LotNo,ProductFamily,ProductCode,MaterialCode,
             MaterialName,DepalletQty,GoodQty,Remark,StartDateTime,EndDateTime,RunSequence)
            OUTPUT INSERTED.DepalletID VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            production_id, data['DepalletDate'], data['Shift'], data['LotNo'],
            lot.get('ProductFamily'), lot['ProductCode'], lot['MaterialCode'], lot.get('MaterialName'),
            data['DepalletQty'], data['GoodQty'], data['Remark'],data['StartDateTime'],data['EndDateTime'],run_sequence)
        depallet_id = cursor.fetchone()[0]
    else:
        cursor.execute("""UPDATE dbo.Depallet SET Shift=?,LotNo=?,DepalletQty=?,GoodQty=?,
            Remark=?,StartDateTime=?,EndDateTime=?,UpdatedAt=SYSDATETIME()
            WHERE DepalletID=? AND ProductionID=?""",
            data['Shift'], data['LotNo'], data['DepalletQty'], data['GoodQty'], data['Remark'],
            data['StartDateTime'],data['EndDateTime'],depallet_id,production_id)
    old_codes = {r['ReasonCode'] for r in old_rejects}
    for code in sorted(active_codes | {'R99'}):
        qty = rejects.get(code, 0)
        if not qty:
            if code in old_codes:
                cursor.execute('DELETE FROM dbo.DepalletReject WHERE DepalletID=? AND ReasonCode=?', depallet_id, code)
        elif code in old_codes:
            cursor.execute('UPDATE dbo.DepalletReject SET Qty=?,UpdatedAt=SYSDATETIME() WHERE DepalletID=? AND ReasonCode=?', qty, depallet_id, code)
        else:
            cursor.execute('INSERT INTO dbo.DepalletReject (DepalletID,ReasonCode,Qty) VALUES (?,?,?)', depallet_id, code, qty)
    cursor.execute('SELECT * FROM dbo.vw_DepalletValidation WHERE DepalletID=?', depallet_id)
    saved = rows(cursor)
    if not saved:
        raise ValueError('Depallet validation failed. Nothing was saved.')
    saved[0].update(summary(data['DepalletQty'], data['GoodQty'], rejects))
    saved[0].update(StartDateTime=data['StartDateTime'],EndDateTime=data['EndDateTime'])
    cursor.execute('SELECT RunSequence FROM dbo.Depallet WHERE DepalletID=?', depallet_id)
    saved[0]['RunSequence'] = cursor.fetchone()[0]
    return saved[0]


def save_depallet(conn, production_id, raw):
    try:
        cursor = conn.cursor()
        lock_lots(cursor)
        saved = _save_depallet_locked(cursor, production_id, raw)
        conn.commit()
        return saved
    except Exception:
        conn.rollback()
        raise


def save_depallet_batch(conn, depallet_date, items):
    try:
        selected_date = date.fromisoformat(str(depallet_date))
    except ValueError:
        raise ValueError('Enter a valid Depallet Date.') from None
    if not isinstance(items, list) or not items:
        raise ValueError('Add at least one Production Lot before saving.')
    production_ids = [item.get('ProductionID') for item in items if isinstance(item, dict)]
    if len(production_ids) != len(items) or any(not isinstance(value, int) or isinstance(value, bool) for value in production_ids):
        raise ValueError('Invalid Production Lot selection.')
    depallet_ids = [item.get('DepalletID') for item in items if item.get('DepalletID') not in ('', None)]
    if len(depallet_ids) != len(set(depallet_ids)):
        raise ValueError('A saved Depallet run can only be submitted once.')
    try:
        cursor = conn.cursor()
        lock_lots(cursor)
        day_start_time = read_day_start_time(cursor, selected_date)
        saved = []
        for item in items:
            raw = dict(item, DepalletDate=selected_date)
            saved.append(_save_depallet_locked(cursor, item['ProductionID'], raw, day_start_time))
        conn.commit()
        return saved
    except Exception:
        conn.rollback()
        raise


def reorder_depallet_run(conn, depallet_date, depallet_id, direction):
    try:
        selected_date = date.fromisoformat(str(depallet_date))
    except ValueError:
        raise ValueError('Enter a valid Production Date.') from None
    if direction not in ('up', 'down'):
        raise ValueError('Direction must be up or down.')
    try:
        cursor = conn.cursor()
        lock_lots(cursor)
        cursor.execute("""SELECT DepalletID,RunSequence FROM dbo.Depallet WITH (UPDLOCK,HOLDLOCK)
            WHERE DepalletDate=? ORDER BY RunSequence,DepalletID""", selected_date)
        runs = rows(cursor)
        index = next((i for i, run in enumerate(runs) if run['DepalletID'] == depallet_id), None)
        if index is None:
            raise ValueError('This Depallet run no longer exists for the selected Production Date.')
        neighbor_index = index - 1 if direction == 'up' else index + 1
        if neighbor_index < 0 or neighbor_index >= len(runs):
            conn.commit()
            return dict(moved=False, DepalletID=depallet_id, RunSequence=runs[index]['RunSequence'])
        selected = runs[index]
        runs[index], runs[neighbor_index] = runs[neighbor_index], runs[index]
        cursor.execute('SELECT ISNULL(MAX(RunSequence),0) FROM dbo.Depallet WITH (UPDLOCK,HOLDLOCK) WHERE DepalletDate=?', selected_date)
        temporary_base = int(cursor.fetchone()[0]) + len(runs) + 1
        for offset, run in enumerate(runs, start=1):
            cursor.execute('UPDATE dbo.Depallet SET RunSequence=? WHERE DepalletID=? AND DepalletDate=?',
                           temporary_base + offset, run['DepalletID'], selected_date)
        for sequence, run in enumerate(runs, start=1):
            cursor.execute('UPDATE dbo.Depallet SET RunSequence=? WHERE DepalletID=? AND DepalletDate=?',
                           sequence, run['DepalletID'], selected_date)
        conn.commit()
        return dict(moved=True, DepalletID=depallet_id, RunSequence=neighbor_index + 1)
    except Exception:
        conn.rollback()
        raise
