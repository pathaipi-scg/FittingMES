import unittest
from datetime import date
from unittest.mock import MagicMock, patch
from starlette.requests import Request
from app.main import lot_prefix, production_page, read_plans, mark_used, choose_plan
from app.lots import insert_lot, update_lot, next_running_no, read_lots

DAY = date(2026, 9, 21)
PLAN = dict(selection_id='p1', StartTime=DAY, Shift='D', PlanName='Plan 1',
            MaterialCode='12345678XX', MaterialName='Product brown', PlanCount=3600)
LOT = dict(ProductionID=7, ProdDate=DAY, Shift='D', PlanName='Plan 1',
           MaterialCode='12345678XX', MaterialName='Product brown', PlanQty=3600,
           ProductCode='06', LotPrefix='B0066909', RunningNo=1, LotNo='B006690901', CanVoid=1)

def request():
    return Request({'type':'http', 'method':'GET', 'path':'/', 'headers':[]})

class ProductionTests(unittest.TestCase):
    def test_prefix(self):
        self.assertEqual(lot_prefix('NeuFit / NeuStile', '06', DAY), 'B066909')

    def test_date_filtered_source(self):
        cursor = MagicMock()
        cursor.description = [(k,) for k in PLAN if k != 'selection_id']
        cursor.fetchall.return_value = [tuple(v for k,v in PLAN.items() if k != 'selection_id')]
        result = read_plans(cursor, DAY)
        self.assertIn('dbo.P_ActivePlan', cursor.execute.call_args.args[0])
        self.assertEqual(cursor.execute.call_args.args[1:], ('CRTC','30A1','SB2-3',DAY))
        self.assertEqual(len(result[0]['selection_id']),64)

    def test_used_and_current_plan(self):
        plans = mark_used([dict(PLAN)], [LOT])
        self.assertEqual(plans[0]['used_by'], LOT['LotNo'])
        with self.assertRaises(ValueError): choose_plan(plans,'p1')
        self.assertIsNone(mark_used(plans,[LOT],7)[0]['used_by'])

    def render(self, **kwargs):
        conn=MagicMock()
        conn.cursor.return_value.fetchone.return_value=('06',)
        with patch('app.main.get_connection',return_value=conn), patch('app.main.read_lots',return_value=[dict(LOT)]), patch('app.main.read_plans',return_value=[dict(PLAN)]):
            response=production_page(request(), **kwargs)
        return response,conn

    def test_browse_information_and_disabled_plan(self):
        response,_=self.render(production_id=7)
        self.assertEqual(response.status_code,200)
        text=response.body.decode()
        for value in ['B006690901','Product brown','3,600','USED: B006690901','disabled','PRODUCTION INPUT','Locked','VOID LOT','aria-current="true"']:
            self.assertIn(value,text)
        self.assertNotIn('name="MaterialName"',text)
        self.assertNotIn('replacement_plan',text)

    def test_edit_original_date_and_current_selectable(self):
        response,_=self.render(production_id=7,edit=True,production_date=DAY)
        self.assertEqual(response.status_code,200)
        self.assertIsNone(response.context['edit_plans'][0]['used_by'])
        self.assertIn('SAVE',response.body.decode())
        self.assertIn('CANCEL',response.body.decode())

    def test_stale_lot(self):
        response,conn=self.render(production_id=99)
        self.assertEqual(response.status_code,400)
        conn.commit.assert_not_called()

    def test_list_order(self):
        cursor=MagicMock(); cursor.fetchall.return_value=[]
        read_lots(cursor)
        sql=cursor.execute.call_args.args[0]
        self.assertIn('ORDER BY p.UpdatedAt DESC, p.ProductionID DESC',sql)
        self.assertIn('WHERE p.IsActive=1',sql)

    def test_mapping_and_create_redirect(self):
        conn=MagicMock(); conn.cursor.return_value.fetchone.side_effect=[('NeuFit / NeuStile','06'),(1,)]
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[]),patch('app.main.read_plans',return_value=[dict(PLAN)]),patch('app.main.insert_lot',return_value=8) as insert:
            response=production_page(request(),'p1',create=True,running_no=1,production_date=DAY)
        self.assertEqual(response.status_code,303)
        self.assertIn('production_id=8',response.headers['location'])
        self.assertEqual(insert.call_args.args[2:5],('06','B066909',1))

    def test_mapping_confirmation(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),('06',),None,('NeuFit / NeuStile','06'),(1,)]
        cursor.fetchall.return_value=[('06','Product')]
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[]),patch('app.main.read_plans',return_value=[dict(PLAN)]):
            response=production_page(request(),'p1','06',confirm=True,production_date=DAY,product_family='NeuFit / NeuStile')
        self.assertEqual(response.status_code,200)
        self.assertTrue(any('INSERT INTO dbo.MaterialProductMap' in c.args[0] for c in cursor.execute.call_args_list))
        conn.commit.assert_called_once()

class TransactionTests(unittest.TestCase):
    def test_create_history_and_lock(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),('06',),('NeuFit / NeuStile','06'),None,(1,),(7,)]
        self.assertEqual(insert_lot(conn,PLAN,'06','B066909',1,product_family='NeuFit / NeuStile'),7)
        sqls=[c.args[0] for c in cursor.execute.call_args_list]
        self.assertIn('sp_getapplock',sqls[0])
        self.assertTrue(any('UPDLOCK,HOLDLOCK' in sql for sql in sqls))
        self.assertTrue(any('ProductionLotHistory' in s for s in sqls))
        conn.commit.assert_called_once()

    def test_duplicate_plan_rollback(self):
        conn=MagicMock(); conn.cursor.return_value.fetchone.side_effect=[(0,),('06',),('NeuFit / NeuStile','06'),('used',)]
        with self.assertRaisesRegex(ValueError,'already assigned'): insert_lot(conn,PLAN,'06','B066909',1,product_family='NeuFit / NeuStile')
        conn.rollback.assert_called_once(); conn.commit.assert_not_called()

    def test_stale_or_gap_number_rejected(self):
        for number in (1,3):
            conn=MagicMock(); conn.cursor.return_value.fetchone.side_effect=[(0,),('06',),('NeuFit / NeuStile','06'),None,(2,)]
            with self.assertRaisesRegex(ValueError,'Running number'): insert_lot(conn,PLAN,'06','B066909',number,product_family='NeuFit / NeuStile')
            conn.commit.assert_not_called()

    def setup_update(self, next_no=2):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.description=[(k,) for k in LOT]
        cursor.fetchall.return_value=[tuple(LOT.values())]
        cursor.fetchone.side_effect=[(0,),(next_no,)]
        return conn,cursor

    def test_latest_void_history_no_delete(self):
        conn,cursor=self.setup_update()
        update_lot(conn,7,void=True)
        sqls=[c.args[0] for c in cursor.execute.call_args_list]
        self.assertTrue(any('SET IsActive=0' in s for s in sqls))
        self.assertFalse(any('DELETE' in s for s in sqls))
        self.assertEqual(cursor.execute.call_args.args[-1],'VOID')
        conn.commit.assert_called_once()

    def test_middle_void_rejected(self):
        conn,_=self.setup_update(3)
        with self.assertRaisesRegex(ValueError,'latest'): update_lot(conn,7,void=True)
        conn.rollback.assert_called_once(); conn.commit.assert_not_called()

    def test_plan_date_locked(self):
        conn,_=self.setup_update()
        with self.assertRaisesRegex(ValueError,'original Plan Date'):
            update_lot(conn,7,dict(PLAN,StartTime=date(2026,9,22)))
        conn.commit.assert_not_called()

    def test_other_lot_plan_rejected(self):
        conn,cursor=self.setup_update(); cursor.fetchone.side_effect=[(0,),('another',)]
        with self.assertRaisesRegex(ValueError,'already assigned'): update_lot(conn,7,PLAN)
        conn.commit.assert_not_called()

    def test_plan_update_keeps_lot_and_date(self):
        conn,cursor=self.setup_update(); cursor.fetchone.side_effect=[(0,),None]
        update_lot(conn,7,dict(PLAN,PlanName='Replacement',MaterialName='New product',PlanCount=50))
        args=next(c.args for c in cursor.execute.call_args_list if 'UPDATE dbo.ProductionLot' in c.args[0])
        self.assertEqual(args[1:],('Replacement','12345678XX','New product',50,7))
        self.assertNotIn('LotNo=',args[0]); self.assertNotIn('ProdDate=',args[0])
        self.assertEqual(cursor.execute.call_args.args[-1],'PLAN_CHANGE')

    def test_void_releases_plan_and_reuses_number(self):
        conn,cursor=self.setup_update()
        update_lot(conn,7,void=True)
        cursor.fetchone.side_effect=[(0,),('06',),('NeuFit / NeuStile','06'),None,(1,),(8,)]
        self.assertEqual(insert_lot(conn,PLAN,'06','B066909',1,product_family='NeuFit / NeuStile'),8)
        checks=[c.args[0] for c in cursor.execute.call_args_list if 'MAX(RunningNo)' in c.args[0] or 'SELECT LotNo' in c.args[0]]
        self.assertTrue(all('IsActive=1' in sql for sql in checks))

    def test_history_failure_rolls_back(self):
        conn,cursor=self.setup_update()
        def execute(sql,*args):
            if 'INSERT INTO dbo.ProductionLotHistory' in sql: raise RuntimeError('history failure')
        cursor.execute.side_effect=execute
        with self.assertRaises(RuntimeError): update_lot(conn,7,void=True)
        conn.rollback.assert_called_once(); conn.commit.assert_not_called()

    def test_lock_timeout(self):
        conn=MagicMock(); conn.cursor.return_value.fetchone.return_value=(-1,)
        with self.assertRaisesRegex(ValueError,'retry'): insert_lot(conn,PLAN,'06','B066909',1,product_family='NeuFit / NeuStile')
        conn.commit.assert_not_called()

if __name__=='__main__':
    unittest.main()

