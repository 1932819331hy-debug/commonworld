import gc
import json
import socket
import sys
import threading
import unittest
import weakref
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'atlas'))
import refresh


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append(self.path)
        if self.path == '/redirect-private':
            self.send_response(302)
            self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/private')
            self.end_headers()
            return
        if self.path == '/redirect-public':
            self.send_response(302)
            self.send_header('Location', '/json')
            self.end_headers()
            return
        if self.path == '/loop':
            self.send_response(302)
            self.send_header('Location', '/loop')
            self.end_headers()
            return
        body = b'{"ok":true}' if self.path == '/json' else b'x' * 64
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class _WeakRow(dict):
    __slots__ = ('__weakref__',)


class RefreshSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        cls.server.requests = []
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://public.example.test:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.server.requests.clear()

    def _network(self, rebinding=False):
        original_getaddrinfo = socket.getaddrinfo
        original_connect = socket.socket.connect
        lookups = {'count': 0}

        def fake_getaddrinfo(host, port, *args, **kwargs):
            if str(host).lower().rstrip('.') == 'public.example.test':
                lookups['count'] += 1
                address = '127.0.0.1' if rebinding and lookups['count'] > 1 else '93.184.216.34'
                return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, int(port)))]
            return original_getaddrinfo(host, port, *args, **kwargs)

        def fake_connect(sock, address):
            if isinstance(address, tuple) and address[0] == '93.184.216.34':
                address = ('127.0.0.1', address[1])
            return original_connect(sock, address)

        return mock.patch('socket.getaddrinfo', side_effect=fake_getaddrinfo), \
            mock.patch.object(socket.socket, 'connect', new=fake_connect), lookups

    def test_public_relative_redirect_works_without_environment_proxy(self):
        getaddrinfo_patch, connect_patch, _ = self._network()
        with mock.patch.dict('os.environ', {'http_proxy': 'http://127.0.0.1:1', 'HTTP_PROXY': 'http://127.0.0.1:1'}):
            with getaddrinfo_patch, connect_patch:
                result = refresh.fetch(self.base + '/redirect-public', want_body=True)
        self.assertEqual(result['status'], 200)
        self.assertEqual(json.loads(result['body']), {'ok': True})
        self.assertEqual(self.server.requests, ['/redirect-public', '/json'])
        proxy_handlers = [h for h in refresh._OPENER.handlers if isinstance(h, refresh.urllib.request.ProxyHandler)]
        self.assertEqual(proxy_handlers, [])

    def test_redirect_to_loopback_is_refused_before_second_request(self):
        getaddrinfo_patch, connect_patch, _ = self._network()
        with getaddrinfo_patch, connect_patch:
            result = refresh.fetch(self.base + '/redirect-private')
        self.assertIsNone(result['status'])
        self.assertIn('refused', result['error'].lower())
        self.assertEqual(self.server.requests, ['/redirect-private'])

    def test_rebinding_to_loopback_between_preflight_and_connect_is_refused(self):
        getaddrinfo_patch, connect_patch, lookups = self._network(rebinding=True)
        with getaddrinfo_patch, connect_patch:
            result = refresh.fetch(self.base + '/json')
        self.assertIsNone(result['status'])
        self.assertGreaterEqual(lookups['count'], 2)
        self.assertEqual(self.server.requests, [])

    def test_redirect_chain_is_bounded(self):
        getaddrinfo_patch, connect_patch, _ = self._network()
        with getaddrinfo_patch, connect_patch:
            result = refresh.fetch(self.base + '/loop')
        self.assertIsNone(result['status'])
        self.assertIn('too many redirects', result['error'])
        self.assertEqual(len(self.server.requests), refresh.MAX_REDIRECTS + 1)

    def test_special_and_private_embedded_addresses_are_not_public(self):
        self.assertFalse(refresh._is_public_ip('168.63.129.16'))
        self.assertFalse(refresh._is_public_ip('169.254.169.254'))
        self.assertFalse(refresh._is_public_ip('64:ff9b::7f00:1'))
        self.assertTrue(refresh._is_public_ip('64:ff9b::0808:0808'))

    def test_azure_wireserver_is_rejected_in_ipv4_embedded_ipv6_forms(self):
        embedded = (
            '::ffff:a83f:8110',
            '64:ff9b::a83f:8110',
            '2002:a83f:8110::1',
            '2001:0000:0101:0101:0000:ffff:57c0:7eef',
            '::a83f:8110',
        )
        for address in embedded:
            with self.subTest(address=address):
                self.assertFalse(refresh._is_public_ip(address))

    def test_mixed_public_and_private_dns_answers_are_refused(self):
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', 80)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', 80)),
        ]
        with mock.patch('socket.getaddrinfo', return_value=answers):
            self.assertFalse(refresh.public_url('http://mixed.example.test/'))

    def test_aggregate_releases_previous_page_and_preserves_count_and_sum(self):
        first = _WeakRow(status='paid', paidTxid='tx1', rewardSats=5)
        first_ref = weakref.ref(first)
        pages = [
            ({'bounties': [first], 'hasMore': True, 'nextOffset': 100}, 10),
            ({'bounties': [{'status': 'open', 'rewardSats': 99},
                           {'status': 'paid', 'paidTxid': 'tx2', 'rewardSats': 7}], 'hasMore': False}, 20),
        ]
        del first

        def fake_get_json(_url, with_size=False, max_bytes=None):
            if len(pages) == 1:
                gc.collect()
                self.assertIsNone(first_ref(), 'previous page row remained live while fetching the next page')
            doc, size = pages.pop(0)
            return doc, None, size

        mapping = {
            'url': 'https://aibtc.com/api/bounties?status=paid&limit=100',
            'paginate': 'offset',
            'agg': {'list': 'bounties', 'op': 'sum', 'field': 'rewardSats',
                    'where': {'status': 'paid', 'paidTxid': '*'}},
        }
        with mock.patch.object(refresh, 'get_json', side_effect=fake_get_json):
            value, quote, _methods, error = refresh.read_mapping(mapping)
        self.assertIsNone(error)
        self.assertEqual(value, 12)
        self.assertTrue(quote.startswith('3 items read; 2 with '))
        self.assertIn('sum rewardSats = 12', quote)

    def test_aggregate_item_limit_rejects_over_limit(self):
        mapping = {'url': 'https://aibtc.com/api/bounties?limit=100',
                   'agg': {'list': 'bounties', 'op': 'count'}}
        with mock.patch.object(refresh, 'MAX_AGG_ITEMS', 2), \
                mock.patch.object(refresh, 'get_json', return_value=({'bounties': [{}, {}, {}]}, None, 20)):
            value, quote, _methods, error = refresh.read_mapping(mapping)
        self.assertIsNone(value)
        self.assertIsNone(quote)
        self.assertIn('more than 2 items', error)

    def test_aggregate_passes_only_remaining_byte_budget(self):
        mapping = {'url': 'https://aibtc.com/api/bounties?limit=100',
                   'paginate': 'offset', 'agg': {'list': 'bounties', 'op': 'count'}}
        calls = []

        def fake_get_json(url, with_size=False, max_bytes=None):
            calls.append((url, max_bytes))
            if len(calls) == 1:
                return {'bounties': [], 'hasMore': True, 'nextOffset': 100}, None, 6
            return None, f'response larger than {max_bytes} bytes', 0

        with mock.patch.object(refresh, 'MAX_AGG_BYTES', 10), \
                mock.patch.object(refresh, 'get_json', side_effect=fake_get_json):
            value, quote, _methods, error = refresh.read_mapping(mapping)
        self.assertIsNone(value)
        self.assertIsNone(quote)
        self.assertIn('larger than 4 bytes', error)
        self.assertEqual(calls[1][1], 4)
        self.assertTrue(calls[1][0].endswith('offset=100'))

    def test_oversized_pagination_offset_is_refused(self):
        mapping = {'url': 'https://aibtc.com/api/bounties?limit=100',
                   'paginate': 'offset', 'agg': {'list': 'bounties', 'op': 'count'}}
        page = {'bounties': [], 'hasMore': True, 'nextOffset': '/' * 500_000}
        with mock.patch.object(refresh, 'get_json', return_value=(page, None, 100)):
            value, quote, methods, error = refresh.read_mapping(mapping)
        self.assertIsNone(value)
        self.assertIsNone(quote)
        self.assertIn('oversized pagination offset', error)
        self.assertEqual(methods, ['GET ' + mapping['url']])

    def test_paginated_read_fails_instead_of_silently_truncating(self):
        mapping = {'url': 'https://aibtc.com/api/bounties?limit=100',
                   'paginate': 'offset', 'agg': {'list': 'bounties', 'op': 'count'}}
        page = {'bounties': [], 'hasMore': True, 'nextOffset': 100}
        with mock.patch.object(refresh, 'MAX_AGG_PAGES', 1), \
                mock.patch.object(refresh, 'get_json', return_value=(page, None, 100)):
            value, quote, _methods, error = refresh.read_mapping(mapping)
        self.assertIsNone(value)
        self.assertIsNone(quote)
        self.assertIn('exceeds 1 pages', error)

    def test_oversized_json_is_rejected_before_parsing(self):
        getaddrinfo_patch, connect_patch, _ = self._network()
        with mock.patch.object(refresh, 'MAX_JSON_BYTES', 16), \
                mock.patch.object(refresh.json, 'loads') as loads, \
                getaddrinfo_patch, connect_patch:
            doc, error = refresh.get_json(self.base + '/large')
        self.assertIsNone(doc)
        self.assertIn('larger than 16 bytes', error)
        loads.assert_not_called()


if __name__ == '__main__':
    unittest.main()
