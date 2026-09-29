"""Prepared ProdOrders transport. Deliberately not connected to any route.

A future date-level SEND ALL action must supply every generated group.
Calling this client is an explicit network operation, never part of preview.
"""
import base64
import http.client
import json
from urllib.parse import urlencode, urlsplit
from fastapi.encoders import jsonable_encoder
from app.pis_config import PISConfig

PRODORDERS_PATH = '/api/v1/ProdOrders'
OUTPUT_DETAILS_PATH = '/api/v2/OutputDetails'
CHANGE_STATUS_PATH = '/api/v1/OutputDetails/ChangeStatus'


class PISClientError(RuntimeError):
    pass


class PISClient:
    def __init__(self, config=None, *, connection_factory=None, timeout=30):
        self._config = config if config is not None else PISConfig.from_environment()
        self._connection_factory = connection_factory or http.client.HTTPSConnection
        self._timeout = timeout

    def post_prodorders(self, group_payload):
        """POST one already-built group unchanged; no retries or redirects.

        Returns status/body for future business-response handling. This does not
        infer PIS business success or write send status to the database.
        """
        if not self._config.endpoint_configured:
            raise PISClientError('PIS endpoint is not configured correctly.')
        if not self._config.authentication_configured:
            raise PISClientError('PIS authentication is not configured.')
        if not isinstance(group_payload, dict) or not group_payload.get('productionItems'):
            raise PISClientError('A generated ProdOrders group payload is required.')
        try:
            body = json.dumps(jsonable_encoder(group_payload), ensure_ascii=False,
                              allow_nan=False).encode('utf-8')
        except (TypeError, ValueError):
            raise PISClientError('ProdOrders payload could not be serialized.') from None
        url = urlsplit(self._config.base_url)
        credentials = (self._config.username + ':' + self._config.password).encode('utf-8')
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
                   'Authorization': 'Basic ' + base64.b64encode(credentials).decode('ascii')}
        connection = None
        try:
            connection = self._connection_factory(url.hostname, port=url.port, timeout=self._timeout)
            connection.request('POST', PRODORDERS_PATH, body=body, headers=headers)
            response = connection.getresponse()
            status = response.status
            if not 200 <= status < 300:
                raise PISClientError('PIS returned an unsuccessful HTTP status.')
            result = response.read().decode('utf-8')
            return dict(status_code=status, body=result)
        except PISClientError:
            raise
        except Exception:
            # Transport exceptions can include sensitive request details.
            raise PISClientError('PIS request failed.') from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def get_output_details(self, query):
        """GET the CB OutputDetails state for one lot; never retries."""
        if not isinstance(query, dict):
            raise PISClientError('An OutputDetails query is required.')
        return self._request('GET', OUTPUT_DETAILS_PATH, query=query)

    def post_change_status(self, payload):
        """POST one already-built CB ChangeStatus body; never retries."""
        if not isinstance(payload, dict) or not payload.get('changeTo'):
            raise PISClientError('A ChangeStatus payload is required.')
        return self._request('POST', CHANGE_STATUS_PATH, body=payload)

    def _request(self, method, path, *, query=None, body=None):
        if not self._config.endpoint_configured:
            raise PISClientError('PIS endpoint is not configured correctly.')
        if not self._config.authentication_configured:
            raise PISClientError('PIS authentication is not configured.')
        try:
            encoded_body = (json.dumps(jsonable_encoder(body), ensure_ascii=False,
                                       allow_nan=False).encode('utf-8') if body is not None else None)
        except (TypeError, ValueError):
            raise PISClientError('PIS payload could not be serialized.') from None
        url = urlsplit(self._config.base_url)
        if query:
            path = path + '?' + urlencode(query)
        credentials = (self._config.username + ':' + self._config.password).encode('utf-8')
        headers = {'Accept': 'application/json',
                   'Authorization': 'Basic ' + base64.b64encode(credentials).decode('ascii')}
        if encoded_body is not None:
            headers['Content-Type'] = 'application/json'
        connection = None
        try:
            connection = self._connection_factory(url.hostname, port=url.port, timeout=self._timeout)
            connection.request(method, path, body=encoded_body, headers=headers)
            response = connection.getresponse()
            status = response.status
            if not 200 <= status < 300:
                raise PISClientError('PIS returned an unsuccessful HTTP status.')
            result = response.read().decode('utf-8')
            return dict(status_code=status, body=result)
        except PISClientError:
            raise
        except Exception:
            raise PISClientError('PIS request failed.') from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
