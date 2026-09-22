import unittest
import sqlite3
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch
from html.parser import HTMLParser
from app.products import FAMILIES, lot_prefix, selected_product, confirm_mapping, read_mapping, require_product
from app.lots import next_running_no, read_lots, insert_lot, update_lot
from app.main import production_page, confirm_product
from test_production import LOT, PLAN, DAY, request

NEU = 'NeuFit / NeuStile'
SPECIAL = 'Special Ridge'
# Synthetic cross-family fixtures are used only in mocks, never loaded into MSSQL.
PRODUCTS = [
    dict(ProductFamily=NEU,ProductCode='06',ProductName='Verge'),
    dict(ProductFamily='Oriental',ProductCode='16',ProductName='Angle Ridge End'),
    dict(ProductFamily=SPECIAL,ProductCode='06',ProductName='Synthetic special'),
    dict(ProductFamily='Prestige Common',ProductCode='16',ProductName='Synthetic prestige'),
]


class SelectParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.family = None
        self.options = {}
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'select':
            self.family = attrs.get('data-family')
            if self.family:
                self.options[self.family] = []
        elif tag == 'option' and self.family and attrs.get('value'):
            self.options[self.family].append(attrs['value'])
    def handle_endtag(self, tag):
        if tag == 'select': self.family = None


class FamilyTests(unittest.TestCase):
    def test_family_prefixes_format_and_month(self):
        for family, letter in FAMILIES:
            with self.subTest(family=family):
                self.assertEqual(lot_prefix(family,'01',date(2024,1,2)),letter+'016701')
                self.assertEqual(lot_prefix(family,'06',DAY),letter+'066909')
                self.assertEqual(lot_prefix(family,'06',date(2026,10,1)),letter+'066910')
        with self.assertRaises(ValueError): lot_prefix('Unknown','06',DAY)
        with self.assertRaises(ValueError): lot_prefix(NEU,'6',DAY)

    def test_exactly_one_family_selection(self):
        for index,(family,_) in enumerate(FAMILIES):
            choices=['','','','']; choices[index]='06'
            self.assertEqual(selected_product(choices),(family,'06'))
        for choices in (['','','',''], ['06','','06','']):
            with self.assertRaises(ValueError): selected_product(choices)

    def test_confirm_stores_family_and_code(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),('06',),None]
        self.assertEqual(confirm_mapping(conn,'PREFIX',SPECIAL,'06'),(SPECIAL,'06'))
        args=next(c.args for c in cursor.execute.call_args_list if 'INSERT INTO dbo.MaterialProductMap' in c.args[0])
        self.assertEqual(args[1:],('PREFIX',SPECIAL,'06'))
        conn.commit.assert_called_once()

    def test_only_operator_confirmation_resolves_legacy_mapping(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.return_value=(None,'06')
        self.assertIsNone(read_mapping(cursor,'PREFIX'))
        self.assertFalse(any('UPDATE' in c.args[0] for c in cursor.execute.call_args_list))
        cursor.fetchone.side_effect=[(0,),('06',),(None,'06')]
        confirm_mapping(conn,'PREFIX',NEU,'06')
        args=next(c.args for c in cursor.execute.call_args_list if 'UPDATE dbo.MaterialProductMap' in c.args[0])
        self.assertEqual(args[1:],(NEU,'06','PREFIX'))
        self.assertFalse(any('UPDATE dbo.ProductionLot' in c.args[0] for c in cursor.execute.call_args_list))

    def test_concurrent_conflicting_confirmation_is_not_overwritten(self):
        conn=MagicMock(); conn.cursor.return_value.fetchone.side_effect=[(0,),('06',),(NEU,'06')]
        with self.assertRaisesRegex(ValueError,'another session'): confirm_mapping(conn,'PREFIX',SPECIAL,'06')
        conn.rollback.assert_called_once(); conn.commit.assert_not_called()

    def test_product_validation_checks_family_not_code_alone(self):
        cursor=MagicMock(); cursor.fetchone.return_value=None
        with self.assertRaises(ValueError): require_product(cursor,SPECIAL,'06')
        self.assertEqual(cursor.execute.call_args.args[1:],(SPECIAL,'06'))
        self.assertIn('ProductFamily=? AND ProductCode=?',cursor.execute.call_args.args[0])

    def render_unmapped(self, products=PRODUCTS, **kwargs):
        conn=MagicMock(); conn.cursor.return_value.fetchall.return_value=[]
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[]),patch('app.main.read_plans',return_value=[PLAN]),patch('app.main.read_mapping',return_value=None),patch('app.main.read_products',return_value=products):
            response=production_page(request(),'p1',production_date=DAY,**kwargs)
        return response,conn

    def test_four_dropdowns_are_family_scoped_and_preview_separates_same_code(self):
        response,_=self.render_unmapped()
        self.assertEqual(response.status_code,200)
        parser=SelectParser(); parser.feed(response.body.decode())
        self.assertEqual(parser.options,{NEU:['06'],'Oriental':['16'],SPECIAL:['06'],'Prestige Common':['16']})
        previews=response.context['product_previews']
        self.assertEqual(previews[NEU+'|06']['LotNo'],'B06690901')
        self.assertEqual(previews[SPECIAL+'|06']['LotNo'],'I06690901')

    def test_missing_family_masters_do_not_invent_choices(self):
        response,_=self.render_unmapped(PRODUCTS[:2])
        parser=SelectParser(); parser.feed(response.body.decode())
        self.assertEqual(parser.options[SPECIAL],[])
        self.assertEqual(parser.options['Prestige Common'],[])
        self.assertIn('No master rows',response.body.decode())

    def test_confirmed_mapping_auto_resolves_without_selection(self):
        conn=MagicMock(); conn.cursor.return_value.fetchone.return_value=(4,)
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[]),patch('app.main.read_plans',return_value=[PLAN]),patch('app.main.read_mapping',return_value=(SPECIAL,'06')),patch('app.main.read_products') as products:
            response=production_page(request(),'p1',production_date=DAY)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['product_family'],SPECIAL)
        self.assertEqual(response.context['lot'],'I066909')
        self.assertEqual(response.context['running_no'],4)
        products.assert_not_called()

    def test_browse_never_uses_new_material_mapping(self):
        for family in (None,NEU,SPECIAL):
            with self.subTest(family=family):
                lot=dict(LOT,ProductFamily=family)
                conn=MagicMock()
                with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[lot]),patch('app.main.read_plans',return_value=[PLAN]),patch('app.main.read_production_data',return_value={}),patch('app.main.read_mapping') as mapping:
                    response=production_page(request(),production_id=7)
                self.assertEqual(response.status_code,200)
                for key in ('ProductFamily','ProductCode','LotNo','LotPrefix','RunningNo','Shift'):
                    self.assertEqual(response.context['current'][key],lot[key])
                mapping.assert_not_called()

    def test_create_persists_family_and_revalidates_mapping(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),('06',),(SPECIAL,'06'),None,(1,),(9,)]
        insert_lot(conn,PLAN,'06','I066909',1,product_family=SPECIAL)
        args=next(c.args for c in cursor.execute.call_args_list if 'INSERT INTO dbo.ProductionLot\n' in c.args[0])
        self.assertEqual(args[-1],SPECIAL)
        self.assertEqual(args[-3],'I06690901')
        cursor.fetchone.side_effect=[(0,),('06',),(NEU,'06')]
        with self.assertRaisesRegex(ValueError,'mapping changed'):
            insert_lot(conn,PLAN,'06','I066909',1,product_family=SPECIAL)

    def test_create_without_family_is_rejected(self):
        with self.assertRaises(ValueError): insert_lot(MagicMock(),PLAN,'06','B0066909',1)

    def test_confirm_route_rejects_multiple_selections(self):
        conn=MagicMock()
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[]),patch('app.main.read_plans',return_value=[PLAN]),patch('app.main.confirm_mapping') as confirm:
            response=confirm_product(request(),'p1',DAY,'06','','06','')
        self.assertEqual(response.status_code,400)
        confirm.assert_not_called()


class Cursor:
    def __init__(self, cursor): self.cursor=cursor
    def execute(self, sql, *params):
        self.cursor.execute(sql,tuple(p.isoformat() if isinstance(p,date) else p for p in params))
        return self
    def fetchone(self): return self.cursor.fetchone()
    def fetchall(self): return self.cursor.fetchall()
    @property
    def description(self): return self.cursor.description


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); self.addCleanup(self.db.close)
        self.db.execute("ATTACH DATABASE ':memory:' AS dbo")
        self.db.execute('''CREATE TABLE dbo.ProductionLot (
            ProductionID INTEGER,ProductFamily TEXT,ProductCode TEXT,SequenceMonth TEXT,
            LotPrefix TEXT,RunningNo INTEGER,IsActive INTEGER,UpdatedAt TEXT)''')
        self.db.executemany('INSERT INTO dbo.ProductionLot VALUES (?,?,?,?,?,?,?,?)',[
            (1,NEU,'06','2026-09-01','B066909',1,1,'2026-09-21'),
            (2,NEU,'06','2026-09-01','B066909',2,1,'2026-09-22'),
            (3,SPECIAL,'06','2026-09-01','I066909',1,1,'2026-09-22'),
            (4,SPECIAL,'06','2026-09-01','I066909',2,0,'2026-09-22'),
            (5,None,'06','2026-09-01','B0066909',1,1,'2026-09-21'),
            (6,None,'06','2026-09-01','B0066909',2,1,'2026-09-22'),
        ])
        self.cursor=Cursor(self.db.cursor())

    def test_sequences_separate_family_month_and_legacy(self):
        self.assertEqual(next_running_no(self.cursor,product_family=NEU,product_code='06',plan_date=DAY),3)
        self.assertEqual(next_running_no(self.cursor,product_family=SPECIAL,product_code='06',plan_date=DAY),2)
        self.assertEqual(next_running_no(self.cursor,product_family=NEU,product_code='06',plan_date=date(2026,10,1)),1)
        self.assertEqual(next_running_no(self.cursor,'B0066909'),3)

    def test_void_eligibility_uses_family_and_preserves_legacy(self):
        lots={row['ProductionID']:row for row in read_lots(self.cursor)}
        self.assertEqual({key:row['CanVoid'] for key,row in lots.items()},{1:0,2:1,3:1,5:0,6:1})

    def test_backend_void_checks_exact_family_sequence(self):
        for family in (NEU,SPECIAL):
            conn=MagicMock(); cursor=conn.cursor.return_value
            lot=dict(LOT,ProductFamily=family)
            cursor.description=[(k,) for k in lot]; cursor.fetchall.return_value=[tuple(lot.values())]
            cursor.fetchone.side_effect=[(0,),(3,)]
            with self.assertRaisesRegex(ValueError,'latest'): update_lot(conn,7,void=True)
            args=next(c.args for c in cursor.execute.call_args_list if 'MAX(RunningNo)' in c.args[0])
            self.assertEqual(args[1:],(family,'06',date(2026,9,1)))
            conn.commit.assert_not_called()

    def test_master_composite_identity_allows_same_code(self):
        self.db.execute('CREATE TABLE Master(ProductFamily TEXT, ProductCode TEXT, PRIMARY KEY(ProductFamily,ProductCode))')
        self.db.execute('INSERT INTO Master VALUES (?,?)',(NEU,'06'))
        self.db.execute('INSERT INTO Master VALUES (?,?)',(SPECIAL,'06'))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO Master VALUES (?,?)',(NEU,'06'))
        sql=Path('sql/003_product_families.sql').read_text()
        self.assertIn('PRIMARY KEY (ProductFamily,ProductCode)',sql)
        self.assertNotIn('UPDATE dbo.MaterialProductMap',sql)
        self.assertNotIn('UPDATE dbo.ProductionLot',sql)
