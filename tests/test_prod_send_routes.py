import unittest
from datetime import date
from unittest.mock import Mock, patch

from app.main import send_all_prod, send_prod, retry_unknown_prod
from app.pis_config import PISConfig
from test_prod_api import DAY, ReadOnlyConnection, RECORD


class ProductionSendRouteTests(unittest.TestCase):
    def enabled_config(self):
        return PISConfig('https://pis-api.scg.com', 'user', 'password', True)

    def test_disabled_by_default_refuses_without_database_or_client(self):
        with patch('app.main.get_connection') as connection, patch('app.main.PISClient') as client:
            response = send_prod(None, DAY, 2)
        self.assertEqual(response.status_code, 303)
        self.assertIn('Production+sending+is+disabled', response.headers['location'])
        connection.assert_not_called()
        client.assert_not_called()

    def test_missing_endpoint_or_authentication_refuses(self):
        for config in (PISConfig('', 'user', 'password', True),
                       PISConfig('https://pis-api.scg.com', '', '', True)):
            with self.subTest(config=config), patch('app.main.PISConfig.from_environment', return_value=config), \
                 patch('app.main.get_connection') as connection:
                response = send_prod(None, DAY, 2)
            self.assertEqual(response.status_code, 303)
            connection.assert_not_called()

    def test_ready_not_sent_route_uses_service_and_redirects(self):
        conn = ReadOnlyConnection([RECORD])
        result = dict(outcome='SUCCESS', production_ids=[2], request_group_id='group', group_key=('x',), http_status=200)
        with patch('app.main.PISConfig.from_environment', return_value=self.enabled_config()), \
             patch('app.main.get_connection', return_value=conn), \
             patch('app.main.send_ready_groups', return_value=[result]) as send, \
             patch('app.main.PISClient') as client:
            response = send_prod(None, DAY, 2)
        self.assertEqual(response.status_code, 303)
        self.assertIn('send_success=1', response.headers['location'])
        send.assert_called_once()
        self.assertFalse(send.call_args.kwargs.get('include_unknown', False))
        client.assert_called_once()

    def test_unknown_retry_uses_dedicated_flag(self):
        conn = ReadOnlyConnection([RECORD])
        result = dict(outcome='UNKNOWN', production_ids=[2], request_group_id='group', group_key=('x',), http_status=None)
        with patch('app.main.PISConfig.from_environment', return_value=self.enabled_config()), \
             patch('app.main.get_connection', return_value=conn), \
             patch('app.main.send_ready_groups', return_value=[result]) as send, \
             patch('app.main.PISClient'):
            response = retry_unknown_prod(None, DAY, 2)
        self.assertEqual(response.status_code, 303)
        self.assertIn('send_unknown=1', response.headers['location'])
        self.assertTrue(send.call_args.kwargs['include_unknown'])

    def test_send_all_is_post_route_and_continues_service_groups(self):
        conn = ReadOnlyConnection([RECORD])
        results = [dict(outcome='FAILED', production_ids=[2], request_group_id='a', group_key=('a',), http_status=500),
                   dict(outcome='SUCCESS', production_ids=[3], request_group_id='b', group_key=('b',), http_status=200)]
        with patch('app.main.PISConfig.from_environment', return_value=self.enabled_config()), \
             patch('app.main.get_connection', return_value=conn), \
             patch('app.main.send_ready_groups', return_value=results) as send, \
             patch('app.main.PISClient'):
            response = send_all_prod(None, DAY)
        self.assertEqual(response.status_code, 303)
        self.assertIn('send_groups=2', response.headers['location'])
        self.assertIn('send_failed=1', response.headers['location'])
        self.assertIn('send_success=1', response.headers['location'])
        send.assert_called_once()
        self.assertFalse(send.call_args.kwargs.get('include_unknown', False))


if __name__ == '__main__':
    unittest.main()
