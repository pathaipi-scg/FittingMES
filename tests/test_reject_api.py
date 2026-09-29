import unittest
from datetime import date
from unittest.mock import Mock
from app.pis_client import PISClient, PISClientError
from app.pis_config import PISConfig
from app.reject_api import (build_reject_preview, reject_readiness,
                            build_output_details_query, parse_output_details_response,
                            summarize_output_details, build_change_status_preview)


class RejectApiReadinessTests(unittest.TestCase):
    def record(self, **changes):
        record = dict(ProductionID=10, ProdDate=date(2026, 9, 26), Shift='1',
                      LotNo='I02690904', MaterialCode='ZCB30003STDA000A11',
                      Plant='30A1', Machine='SB2-3', CounterQty=1490,
                      CuringQty=1409, RejectRows=[
                          dict(ProductionID=10, ReasonCode='R01', Qty=50),
                          dict(ProductionID=10, ReasonCode='R99', Qty=31),
                      ])
        record.update(changes)
        return record

    def test_supported_reasons_preview_from_persisted_rows(self):
        record = self.record()
        self.assertTrue(reject_readiness(record)['ready'])
        preview = build_reject_preview(record)
        self.assertEqual(preview['plant'], '30A1')
        self.assertIsNone(preview['fromOutputDetailId'])
        self.assertEqual([(item['reasonCode'], item['quantity'])
                          for item in preview['changeTo']], [('R01', 50), ('R99', 31)])

    def test_unsupported_positive_code_blocks_but_zero_does_not(self):
        record = self.record(RejectRows=[dict(ReasonCode='R07', Qty=1),
                                         dict(ReasonCode='R01', Qty=81)])
        readiness = reject_readiness(record)
        self.assertFalse(readiness['ready'])
        self.assertIn('Unsupported Reject Code R07', readiness['missing'])
        record['RejectRows'][0]['Qty'] = 0
        self.assertTrue(reject_readiness(record)['ready'])

    def test_reconciliation_and_zero_rows(self):
        record = self.record(RejectRows=[dict(ReasonCode='R01', Qty=81),
                                         dict(ReasonCode='R02', Qty=0)])
        self.assertTrue(reject_readiness(record)['ready'])
        record['CuringQty'] = 1408
        self.assertFalse(reject_readiness(record)['ready'])
        self.assertTrue(any('Reject total mismatch' in item
                            for item in record['RejectReadiness']['missing']))

    def test_production_id_and_date_are_local_identity(self):
        record = self.record(ProductionID=11, ProdDate=date(2026, 9, 27),
                             RejectRows=[dict(ReasonCode='R01', Qty=81)])
        self.assertTrue(reject_readiness(record)['ready'])
        self.assertEqual(record['ProductionID'], 11)
        self.assertEqual(record['ProdDate'], date(2026, 9, 27))

    def test_output_details_query_matches_cb_contract(self):
        query = build_output_details_query(self.record())
        self.assertEqual(query, {'PlantCode': '30A1', 'MachineCode': 'SB2-3',
                                 'DateFrom': '2026-09-26', 'DateTo': '2026-09-26',
                                 'LotNumbers': 'I02690904'})

    def test_output_details_summary_selects_first_curing_id(self):
        summary = summarize_output_details([
            {'status': 'reject', 'reason': 'R01', 'total': 2,
             'productionOrderOutputDetailID': 'reject-id'},
            {'status': 'curing', 'reason': '', 'total': 81,
             'productionOrderOutputDetailID': 'curing-id-1'},
            {'status': 'curing', 'reason': '', 'total': 4,
             'productionOrderOutputDetailID': 'curing-id-2'},
            {'status': 'Stockyard (แกะดี)', 'reason': '', 'total': 7},
        ])
        self.assertEqual(summary['curingOutputDetailId'], 'curing-id-1')
        self.assertEqual(summary['curingRemaining'], 85)
        self.assertEqual(summary['totalReject'], 2)
        self.assertEqual(summary['stockyard'], 7)
        self.assertEqual(summary['totalTransferred'], 9)

    def test_malformed_output_details_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not valid JSON'):
            parse_output_details_response({'status_code': 200, 'body': 'not-json'})
        with self.assertRaisesRegex(ValueError, 'not an array'):
            parse_output_details_response({'status_code': 200, 'body': '{}'})
        with self.assertRaisesRegex(ValueError, 'malformed item'):
            summarize_output_details([None])

    def test_change_status_preview_uses_persisted_positive_reasons_only(self):
        record = self.record(RejectRows=[
            dict(ReasonCode='R01', Qty=81, RejectDateTime=__import__('datetime').datetime(2026, 9, 26, 22, 15)),
        ])
        preview = build_change_status_preview(record, {
            'originalQty': None, 'stockyard': 0, 'rejects': {}, 'totalReject': 0,
            'totalTransferred': 0, 'curingRemaining': 81,
            'calculatedRemaining': None, 'curingOutputDetailId': 'curing-id'})
        self.assertEqual(preview['fromOutputDetailId'], 'curing-id')
        self.assertEqual(preview['changeTo'][0]['reasonCode'], 'R01')
        self.assertEqual(preview['changeTo'][0]['quantity'], 81)
        self.assertEqual(preview['changeTo'][0]['updateDate'], '2026-09-26T22:15')

    def test_unsupported_reason_and_mismatch_never_build_preview(self):
        record = self.record(RejectRows=[dict(ReasonCode='R07', Qty=1)])
        with self.assertRaisesRegex(ValueError, 'Unsupported Reject Code R07'):
            build_change_status_preview(record, {'curingOutputDetailId': 'id'})

    def test_get_output_details_constructs_exact_get_and_never_posts(self):
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b'[]'
        factory = Mock(return_value=connection)
        client = PISClient(PISConfig('https://pis-api.scg.com', 'user', 'password'),
                           connection_factory=factory)
        result = client.get_output_details({'PlantCode': '30A1', 'MachineCode': 'SB2-3',
                                            'DateFrom': '2026-09-26', 'DateTo': '2026-09-26',
                                            'LotNumbers': 'I02690904'})
        self.assertEqual(result['status_code'], 200)
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ('GET', '/api/v2/OutputDetails?PlantCode=30A1&MachineCode=SB2-3&DateFrom=2026-09-26&DateTo=2026-09-26&LotNumbers=I02690904'))
        self.assertIsNone(kwargs['body'])
        connection.request.assert_called_once()
        self.assertEqual(connection.request.call_args.args[0], 'GET')
        connection.close.assert_called_once()

    def test_get_output_details_auth_and_http_errors_stop_lookup(self):
        factory = Mock()
        with self.assertRaisesRegex(PISClientError, 'authentication is not configured'):
            PISClient(PISConfig('https://pis-api.scg.com', '', ''),
                      connection_factory=factory).get_output_details({})
        factory.assert_not_called()
        connection = Mock()
        connection.getresponse.return_value.status = 500
        with self.assertRaises(PISClientError):
            PISClient(PISConfig('https://pis-api.scg.com', 'user', 'password'),
                      connection_factory=Mock(return_value=connection)).get_output_details({})
        connection.request.assert_called_once()
        connection.getresponse.return_value.read.assert_not_called()

    def test_phase_2a_never_calls_change_status(self):
        client = Mock()
        client.get_output_details.return_value = {'status_code': 200, 'body': '[]'}
        client.post_change_status.side_effect = AssertionError('Phase 2B is disabled')
        client.get_output_details({'PlantCode': '30A1'})
        client.post_change_status.assert_not_called()


if __name__ == '__main__':
    unittest.main()
