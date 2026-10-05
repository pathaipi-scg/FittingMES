import unittest
from datetime import date, time
from decimal import Decimal
from unittest.mock import MagicMock, patch
from app.production_data import (validate, calculate, save_production_data, read_production_data,
                                  read_shift_rules, resolve_shift)
from app.main import production_page, save_production
from app.lots import insert_lot, update_lot
from test_production import LOT, PLAN, DAY, request

RAW = dict(Shift='2',ProductionStartTime='08:10',ProductionEndTime='14:25',
           CounterQty='3648',CuringQty='3310',Remark='Operator note')


class ProductionDataTests(unittest.TestCase):
    RULES = [
        dict(EffectiveFromDate=date(2026, 1, 1), ShiftID=1, StartTime=time(6)),
        dict(EffectiveFromDate=date(2026, 1, 1), ShiftID=2, StartTime=time(20)),
    ]

    def test_resolve_shift_current_boundaries_and_midnight_wrap(self):
        expected = {
            '05:59': '2', '06:00': '1', '06:01': '1', '19:59': '1',
            '20:00': '2', '20:01': '2', '23:59': '2', '00:00': '2',
        }
        for start, shift in expected.items():
            with self.subTest(start=start):
                self.assertEqual(resolve_shift(date(2026, 10, 1), start, '1', self.RULES), shift)

    def test_resolve_shift_uses_latest_effective_rule_and_ignores_future(self):
        rules = [
            dict(EffectiveFromDate=date(2026, 1, 1), ShiftID=1, StartTime=time(6)),
            dict(EffectiveFromDate=date(2026, 1, 1), ShiftID=2, StartTime=time(20)),
            dict(EffectiveFromDate=date(2026, 9, 1), ShiftID=4, StartTime=time(7)),
            dict(EffectiveFromDate=date(2026, 9, 1), ShiftID=5, StartTime=time(15)),
            dict(EffectiveFromDate=date(2026, 11, 1), ShiftID=8, StartTime=time(8)),
        ]
        self.assertEqual(resolve_shift(date(2026, 8, 31), '21:00', '1', self.RULES), '2')
        self.assertEqual(resolve_shift(date(2026, 10, 1), '16:00', '1', rules[2:4]), '5')
        self.assertEqual(resolve_shift(date(2026, 10, 1), '06:30', '1', rules[2:4]), '5')

    def test_resolve_shift_supports_changed_three_shift_schedule(self):
        rules = [
            dict(EffectiveFromDate=date(2027, 1, 1), ShiftID=10, StartTime=time(5)),
            dict(EffectiveFromDate=date(2027, 1, 1), ShiftID=20, StartTime=time(13)),
            dict(EffectiveFromDate=date(2027, 1, 1), ShiftID=30, StartTime=time(21)),
        ]
        self.assertEqual(resolve_shift(date(2027, 1, 1), '04:59', '10', rules), '30')
        self.assertEqual(resolve_shift(date(2027, 1, 1), '13:00', '10', rules), '20')
        self.assertEqual(resolve_shift(date(2027, 1, 1), '22:00', '10', rules), '30')

    def test_resolve_shift_blank_start_preserves_planned_shift(self):
        self.assertEqual(resolve_shift(date(2026, 10, 1), '', '7', self.RULES), '7')

    def test_read_shift_rules_uses_latest_effective_date(self):
        cursor = MagicMock()
        cursor.description = [('EffectiveFromDate',), ('ShiftID',), ('StartTime',)]
        cursor.fetchall.return_value = [(date(2026, 1, 1), 1, time(6))]
        result = read_shift_rules(cursor, date(2026, 10, 1))
        query, parameter = cursor.execute.call_args.args
        self.assertIn('MAX(EffectiveFromDate)', query)
        self.assertIn('EffectiveFromDate<=?', query)
        self.assertEqual(parameter, date(2026, 10, 1))
        self.assertEqual(result[0]['ShiftID'], 1)

    def test_save_replaces_incorrect_submitted_shift_from_start(self):
        conn = self.connection(exists=False)
        rules = self.RULES
        with patch('app.production_data.read_shift_rules', return_value=rules):
            save_production_data(conn, 7, dict(RAW, Shift='1', ProductionStartTime='21:00'), date(2026, 10, 1))
        shift = next(a for a in (item.args for item in conn.cursor.return_value.execute.call_args_list)
                     if 'UPDATE dbo.ProductionLot' in a[0])
        self.assertEqual(shift[1:], ('2', 7))

    def test_save_path_persists_shift_from_start_and_ignores_end(self):
        cases = (
            ('22:00', '03:00', '1', '2'),
            ('10:00', '15:00', '2', '1'),
            ('07:00', '08:00', '2', '1'),
            ('05:59', '06:00', '1', '2'),
            ('20:00', '03:00', '1', '2'),
        )
        for start, end, submitted, expected in cases:
            with self.subTest(start=start, end=end):
                conn = self.connection(exists=False)
                with patch('app.production_data.read_shift_rules', return_value=self.RULES):
                    save_production_data(conn, 7, dict(RAW, Shift=submitted,
                                                        ProductionStartTime=start,
                                                        ProductionEndTime=end),
                                         date(2026, 10, 1))
                shift = next(a for a in (item.args for item in conn.cursor.return_value.execute.call_args_list)
                             if 'UPDATE dbo.ProductionLot' in a[0])
                self.assertEqual(shift[1:], (expected, 7))

    def test_calculations_and_zero_missing(self):
        result=calculate(3648,3310)
        self.assertEqual(result['WetRejectQty'],338)
        self.assertEqual(round(result['WetRejectPercent'],2),Decimal('9.27'))
        self.assertEqual(calculate(0,0)['WetRejectPercent'],0)
        self.assertIsNone(calculate(None,None)['WetRejectPercent'])
        self.assertIsNone(calculate(5,None)['WetRejectQty'])

    def test_validation(self):
        for key,value in [('CounterQty','-1'),('CuringQty','-1'),('CounterQty','1.5'),
                          ('CuringQty','2.5'),('CounterQty','1e3'),('CounterQty',''),
                          ('CounterQty','2147483648'),('CuringQty','4000'),
                          ('Shift',''),('Shift','12345678901'),
                          ('ProductionStartTime','25:10'),('ProductionEndTime',''),
                          ('Remark','x'*1001)]:
            with self.subTest(key=key,value=value):
                with self.assertRaises(ValueError): validate(dict(RAW,**{key:value}))
        self.assertEqual(validate(dict(RAW,CounterQty='0',CuringQty='0'))['CounterQty'],0)
        self.assertEqual(validate(RAW)['ProductionStartTime'],time(8,10))

    def connection(self, exists=False):
        conn=MagicMock()
        conn.cursor.return_value.fetchone.side_effect=[(0,),('B006690901','Plan 1'),(7,) if exists else None]
        return conn

    def test_insert_update_operator_shift_and_no_calculated_storage(self):
        for exists in (False,True):
            with self.subTest(exists=exists):
                conn=self.connection(exists)
                result=save_production_data(conn,7,RAW)
                self.assertEqual(result['WetRejectQty'],338)
                calls=[c.args for c in conn.cursor.return_value.execute.call_args_list]
                writes=[a for a in calls if ('UPDATE dbo.ProductionData' in a[0] or 'INSERT INTO dbo.ProductionData' in a[0])]
                self.assertEqual(len(writes),1)
                self.assertEqual(writes[0][1:],(time(8,10),time(14,25),3648,3310,'Operator note',7))
                self.assertEqual('UPDATE' in writes[0][0],exists)
                self.assertFalse(any('WetReject' in a[0] for a in calls))
                shift=next(a for a in calls if 'UPDATE dbo.ProductionLot' in a[0])
                self.assertEqual(shift[1:],('2',7))
                self.assertNotIn('PlanQty',shift[0])
                conn.commit.assert_called_once()

    def test_repeated_save_updates_same_row(self):
        conn=MagicMock()
        cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),('L','P'),None,(0,),('L','P'),(7,)]
        save_production_data(conn,7,RAW)
        save_production_data(conn,7,dict(RAW,CounterQty='4000'))
        sql=[c.args[0] for c in cursor.execute.call_args_list]
        self.assertEqual(sum('INSERT INTO dbo.ProductionData' in q for q in sql),1)
        self.assertEqual(sum('UPDATE dbo.ProductionData' in q for q in sql),1)

    def test_invalid_never_writes(self):
        conn=MagicMock()
        with self.assertRaises(ValueError): save_production_data(conn,7,dict(RAW,CuringQty='9999'))
        conn.cursor.assert_not_called()
        conn.commit.assert_not_called()

    def test_void_lot_cannot_save(self):
        conn=MagicMock(); conn.cursor.return_value.fetchone.side_effect=[(0,),None]
        with self.assertRaises(ValueError): save_production_data(conn,7,RAW)
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()

    def test_write_failure_rolls_back_shift_and_data(self):
        conn=self.connection()
        def execute(sql,*args):
            if 'ProductionLotHistory' in sql: raise RuntimeError('audit failed')
        conn.cursor.return_value.execute.side_effect=execute
        with self.assertRaises(RuntimeError): save_production_data(conn,7,RAW)
        conn.rollback.assert_called_once(); conn.commit.assert_not_called()

    def test_new_lot_defaults_shift_from_effective_plan(self):
        conn=MagicMock(); conn.cursor.return_value.fetchone.side_effect=[(0,),('NeuFit / NeuStile',),(1,'06'),None,(1,),(1,),(7,)]
        with patch('app.lots.lot_prefix', return_value='B066909'):
            insert_lot(conn,dict(PLAN,Shift='3'),'06','B066909',1,product_family_id=1)
        args=next(c.args for c in conn.cursor.return_value.execute.call_args_list if 'INSERT INTO dbo.ProductionLot\n' in c.args[0])
        self.assertEqual(args[2],'3')

    def test_plan_change_preserves_stored_shift(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.description=[(k,) for k in LOT]
        cursor.fetchall.return_value=[tuple(dict(LOT,Shift='2').values())]
        cursor.fetchone.side_effect=[(0,),None]
        update_lot(conn,7,dict(PLAN,Shift='3'))
        sql=next(c.args[0] for c in cursor.execute.call_args_list if 'UPDATE dbo.ProductionLot' in c.args[0])
        self.assertNotIn('Shift=',sql)

    def test_existing_data_and_shift_reload(self):
        data=dict(ProductionID=7,ProductionStartTime=time(8,10),ProductionEndTime=time(14,25),
                  CounterQty=3648,CuringQty=3310,Remark='Saved note')
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.description=[(k,) for k in data]; cursor.fetchall.return_value=[tuple(data.values())]
        self.assertEqual(read_production_data(cursor,7),data)
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[dict(LOT,Shift='2')]),patch('app.main.read_plans',return_value=[dict(PLAN,Shift='3')]),patch('app.main.read_production_data',return_value=data):
            response=production_page(request(),production_id=7,production_date=DAY)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['current']['Shift'],'2')
        self.assertEqual(response.context['calculated']['WetRejectQty'],338)
        text=response.body.decode()
        for value in ('PRODUCTION LOT','338','3648','3310','Saved note','9.27 %','value="2"'):
            self.assertIn(value,text)

    def test_save_route_redirects_and_validation_keeps_input(self):
        conn=MagicMock()
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[LOT]),patch('app.main.read_plans',return_value=[PLAN]),patch('app.main.save_production_data') as save:
            response=save_production(request(),7,'2','08:10','14:25','3648','3310','note',DAY)
            self.assertEqual(response.status_code,303)
            self.assertIn('production_id=7',response.headers['location'])
            self.assertEqual(save.call_args.args[2]['Shift'],'2')
            save.side_effect=ValueError('Curing Qty cannot exceed Counter.')
            response=production_page(request(),production_id=7,production_input=RAW)
            self.assertEqual(response.status_code,400)
            self.assertEqual(response.context['production_data'],RAW)

    def test_schema_enforces_one_to_one_and_constraints(self):
        from pathlib import Path
        sql=Path('sql/002_production_data.sql').read_text()
        for expected in ('ProductionID bigint NOT NULL','PRIMARY KEY','FOREIGN KEY (ProductionID)',
                         'CounterQty>=0','CuringQty>=0 AND CuringQty<=CounterQty'):
            self.assertIn(expected,sql)
