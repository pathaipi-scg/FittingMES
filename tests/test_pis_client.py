import asyncio
import base64
import copy
import json
import os
import secrets
import unittest
from unittest.mock import Mock, patch
from fastapi.encoders import jsonable_encoder
from app.pis_config import PISConfig
from app.pis_client import PISClient, PISClientError
from app.prod_api import build_pis_date_preview, resolve_plan
from test_prod_api import RECORD, PLAN_SOURCE, DAY, ReadOnlyConnection, get_page


class PISClientTests(unittest.TestCase):
    def setUp(self):
        # Random test-only values, never real or hard-coded credentials.
        self.username = secrets.token_hex(12)
        self.password = secrets.token_hex(24)
        self.environment = {'PIS_BASE_URL':'https://pis-api.scg.com',
                            'PIS_USERNAME':self.username,'PIS_PASSWORD':self.password}
        self.config = PISConfig(**dict(base_url=self.environment['PIS_BASE_URL'],
                                     username=self.username,password=self.password))
        self.payload = build_pis_date_preview([dict(RECORD,**resolve_plan(RECORD,[PLAN_SOURCE]))],DAY)[0]

    def test_environment_is_only_credential_source_and_repr_is_safe(self):
        with patch.dict(os.environ,self.environment,clear=True):
            config=PISConfig.from_environment()
        self.assertEqual(config.username,self.username)
        self.assertEqual(config.password,self.password)
        self.assertNotIn(self.username,repr(config))
        self.assertNotIn(self.password,repr(config))
        self.assertEqual(config.diagnostics(),{'endpoint_configured':True,'authentication_configured':True})
        with patch.dict(os.environ,{},clear=True):
            missing=PISConfig.from_environment()
        self.assertFalse(missing.authentication_configured)
        self.assertFalse(missing.endpoint_configured)

    def test_prepared_post_basic_auth_exact_generated_body_without_network(self):
        connection=Mock()
        connection.getresponse.return_value.status=200
        connection.getresponse.return_value.read.return_value=b'{"message":"success"}'
        factory=Mock(return_value=connection)
        before=copy.deepcopy(self.payload)
        with patch('socket.create_connection',side_effect=AssertionError('Network forbidden')):
            result=PISClient(self.config,connection_factory=factory).post_prodorders(self.payload)
        factory.assert_called_once_with('pis-api.scg.com',port=None,timeout=30)
        args,kwargs=connection.request.call_args
        self.assertEqual(args,('POST','/api/v1/ProdOrders'))
        self.assertEqual(kwargs['headers']['Content-Type'],'application/json')
        encoded=base64.b64encode((self.username+':'+self.password).encode()).decode()
        self.assertEqual(kwargs['headers']['Authorization'],'Basic '+encoded)
        self.assertEqual(json.loads(kwargs['body']),jsonable_encoder(self.payload))
        self.assertEqual(self.payload,before)
        self.assertEqual(result,{'status_code':200,'body':'{"message":"success"}'})
        connection.close.assert_called_once()

    def test_missing_authentication_stops_before_transport(self):
        for username,password in [('',self.password),(self.username,''),(' ',' ' )]:
            factory=Mock()
            with self.assertRaisesRegex(PISClientError,'authentication is not configured'):
                PISClient(PISConfig('https://pis-api.scg.com',username,password),
                          connection_factory=factory).post_prodorders(self.payload)
            factory.assert_not_called()

    def test_invalid_endpoints_are_not_requested_or_echoed(self):
        for url in ('','http://pis-api.scg.com','https://'+self.username+':'+self.password+'@pis-api.scg.com',
                    'https://pis-api.scg.com/path','https://pis-api.scg.com?secret='+self.password):
            factory=Mock()
            config=PISConfig(url,self.username,self.password)
            self.assertFalse(config.endpoint_configured)
            with self.assertRaises(PISClientError) as caught:
                PISClient(config,connection_factory=factory).post_prodorders(self.payload)
            self.assertNotIn(self.password,str(caught.exception))
            factory.assert_not_called()

    def test_transport_errors_are_sanitized_and_not_retried(self):
        connection=Mock()
        connection.request.side_effect=RuntimeError(self.password)
        factory=Mock(return_value=connection)
        with self.assertRaises(PISClientError) as caught:
            PISClient(self.config,connection_factory=factory).post_prodorders(self.payload)
        self.assertEqual(str(caught.exception),'PIS request failed.')
        self.assertNotIn(self.password,str(caught.exception))
        connection.request.assert_called_once()
        connection.close.assert_called_once()

    def test_redirects_and_http_errors_are_not_followed_or_echoed(self):
        for status in (302,401,500):
            connection=Mock()
            connection.getresponse.return_value.status=status
            factory=Mock(return_value=connection)
            with self.assertRaises(PISClientError):
                PISClient(self.config,connection_factory=factory).post_prodorders(self.payload)
            connection.request.assert_called_once()
            connection.getresponse.return_value.read.assert_not_called()
            connection.close.assert_called_once()

    def test_both_previews_never_call_client_or_expose_authentication(self):
        encoded=base64.b64encode((self.username+':'+self.password).encode()).decode()
        for query in ('preview_one=true&production_id=2','preview_all=true'):
            for environment in (self.environment,dict(self.environment,PIS_USERNAME='',PIS_PASSWORD='')):
                with patch.dict(os.environ,environment,clear=True), \
                     patch('app.main.get_connection',return_value=ReadOnlyConnection()), \
                     patch.object(PISClient,'post_prodorders',side_effect=AssertionError('Preview must not send')) as post:
                    status,body=asyncio.run(get_page('/prod-api','production_date=2026-09-22&'+query))
                self.assertEqual(status,200)
                post.assert_not_called()
                for secret in (self.username,self.password,encoded,'Authorization','Basic '):
                    self.assertNotIn(secret,body)
                self.assertIn('DRY RUN / NO PIS SEND',body)
                self.assertIn('PIS endpoint: configured',body)
                self.assertIn('PIS authentication: '+('configured' if environment['PIS_USERNAME'] else 'NOT CONFIGURED'),body)

    def test_client_construction_does_not_connect(self):
        factory=Mock()
        PISClient(self.config,connection_factory=factory)
        factory.assert_not_called()
