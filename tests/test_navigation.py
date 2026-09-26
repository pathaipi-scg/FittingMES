import asyncio
import html
import re
import unittest
from datetime import date, time
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode, urlsplit
from test_prod_api import get_page
from test_production import LOT, PLAN


class NavigationTests(unittest.TestCase):
    def page(self, path, query=''):
        with patch('app.main.get_connection',return_value=MagicMock()), \
             patch('app.main.read_lots',return_value=[dict(LOT)]), \
             patch('app.main.read_plans',return_value=[dict(PLAN)]), \
             patch('app.main.read_production_data',return_value={}), \
             patch('app.main.read_depallet_context',return_value={}), \
             patch('app.main.read_curing_lots',return_value=[]), \
             patch('app.main.read_products',return_value=[]), \
             patch('app.main.read_daily_work',return_value=({},[],[],{},time(8))), \
             patch('app.main.read_prod_records',return_value=[]), \
             patch('app.main.read_usage_context',return_value=dict(lots=[],shifts=[],daily=[])):
            status,body=asyncio.run(get_page(path,query))
        self.assertEqual(status,200)
        return body

    def shared_form(self, body):
        match=re.search(r'<form[^>]*id="shared-production-date"[^>]*>(.*?)</form>',body,re.S)
        self.assertIsNotNone(match)
        return match[0]

    def test_date_survives_complete_tab_cycle(self):
        body=self.page('/','production_date=2026-09-14')
        for path in ('/usage','/depallet','/prod-api','/reject-api','/'):
            nav=re.search(r'<nav class="page-tabs".*?</nav>',body,re.S)[0]
            target=next(html.unescape(url) for url in re.findall(r'href="([^"]+)"',nav)
                        if urlsplit(html.unescape(url)).path==path)
            self.assertEqual(target,path+'?production_date=2026-09-14')
            split=urlsplit(target)
            body=self.page(split.path,split.query)
            self.assertIn('value="2026-09-14"',self.shared_form(body))

    def test_refresh_uses_current_tab_and_one_shared_date_input(self):
        for path in ('/','/usage','/depallet','/prod-api','/reject-api'):
            with self.subTest(path=path):
                body=self.page(path,'production_date=2026-09-14')
                form=self.shared_form(body)
                self.assertIn('action="'+path+'"',form)
                self.assertIn('method="get"',form)
                self.assertIn('>REFRESH<',form)
                inputs=re.findall(r'<input[^>]*>',body)
                self.assertEqual(sum('name="production_date"' in tag and 'type="date"' in tag for tag in inputs),1)
                self.assertLess(body.index('id="shared-production-date"'),body.index('<nav class="page-tabs"'))
                refreshed=self.page(path,urlencode({'production_date':'2026-09-22'}))
                self.assertIn('value="2026-09-22"',self.shared_form(refreshed))
                self.assertNotIn('production_date=2026-09-14',refreshed)

    def test_deep_links_and_default_date(self):
        for path in ('/','/usage','/depallet','/prod-api','/reject-api'):
            body=self.page(path,'production_date=2020-01-02')
            self.assertIn('value="2020-01-02"',self.shared_form(body))
            body=self.page(path)
            self.assertIn('value="'+date.today().isoformat()+'"',self.shared_form(body))

    def test_production_refresh_retains_only_same_date_lot(self):
        body=self.page('/','production_date=2026-09-21&production_id=7')
        self.assertIn('name="production_id" value="7"',self.shared_form(body))
        self.assertIn('SAVE PRODUCTION',body)
        self.assertIn('production_date=2026-09-21&amp;production_id=7',body)
        changed=self.page('/','production_date=2026-09-22&production_id=7&edit=true')
        self.assertNotIn('name="production_id"',self.shared_form(changed))
        self.assertNotIn('SAVE PRODUCTION',changed)
        self.assertIn('value="2026-09-22"',self.shared_form(changed))
        self.assertNotIn('aria-current="true"',changed)
        self.assertIn('href="/?production_id=7&production_date=2026-09-21"',changed)

    def test_lot_only_deep_link_uses_lot_date_and_plan_form_keeps_date(self):
        body=self.page('/','production_id=7')
        self.assertIn('value="2026-09-21"',self.shared_form(body))
        form=re.search(r'<form class="top-controls".*?</form>',body,re.S)[0]
        self.assertIn('type="hidden" name="production_date" value="2026-09-21"',form)
        self.assertIn('Production Plan',form)
        self.assertIn('PLAN REFRESH',form)
        self.assertNotIn('type="date"',form)

    def test_shared_header_groups_date_refresh_and_tabs_in_one_wrapping_row(self):
        for path in ('/','/usage','/depallet','/prod-api','/reject-api'):
            body=self.page(path,'production_date=2026-09-14')
            row=re.search(r'<div class="shared-header-row">(.*?)</nav>\s*</div>',body,re.S)
            self.assertIsNotNone(row)
            self.assertIn('id="shared-production-date"',row[1])
            self.assertLess(row[1].index('>REFRESH<'),row[1].index('<nav class="page-tabs"'))
            self.assertEqual(re.findall(r'>(PRODUCTION|DEPALLET|USAGE|PROD API|REJECT API)</a>',row[1]),
                             ['PRODUCTION','USAGE','DEPALLET','PROD API','REJECT API'])
            self.assertRegex(body,r'\.shared-header-row\{[^}]*display:flex;[^}]*flex-wrap:wrap;')

    def test_shared_date_change_navigation_is_present_on_every_page(self):
        for path in ('/','/usage','/depallet','/prod-api','/reject-api'):
            with self.subTest(path=path):
                body=self.page(path,'production_date=2026-09-14')
                self.assertEqual(body.count("dateInput.addEventListener('change'"),1)
                self.assertIn('window.location.assign(url.toString())',body)
                self.assertIn('>REFRESH<',self.shared_form(body))
