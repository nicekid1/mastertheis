"""Standalone HTTP quota regression: python -m tests.storage_regression.

Uses stdlib clients and a temporary workspace; never touches real accounts.
"""
import concurrent.futures
import http.client
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


class StorageRegression(unittest.TestCase):
    @patch.dict(os.environ, {'GISCLAW_TEXT_CHAT_ENABLED': '1'})
    def test_storage_http(self):
        with tempfile.TemporaryDirectory() as workspace:
            os.environ['GISCLAW_WORKSPACE'] = workspace
            from app import server
            import uvicorn
            self.assertEqual(server.WORKSPACE, workspace)
            user = server.ACCOUNTS.create('storage_test', '1')
            token, _ = server.ACCOUNTS.login('storage_test', '1', 'test')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            srv = uvicorn.Server(uvicorn.Config(server.app, host='127.0.0.1', port=port, log_level='error'))
            thread = threading.Thread(target=srv.run)
            thread.start()
            try:
                for _ in range(100):
                    if srv.started:
                        break
                    time.sleep(.05)
                self.assertTrue(srv.started)

                def call(method, path, body=None, chunked=False):
                    headers = {'X-GISclaw': '1', 'Cookie': 'gisclaw_session=' + token}
                    if isinstance(body, dict):
                        body = json.dumps(body)
                        headers['Content-Type'] = 'application/json'
                    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=20)
                    try:
                        conn.request(method, path, body, headers, encode_chunked=chunked)
                        response = conn.getresponse()
                        return response.status, json.loads(response.read())
                    finally:
                        conn.close()

                self.assertEqual(call('POST', '/api/projects', {'name': 'storage'})[0], 200)
                root = server.ACCOUNTS.root(user)
                for folder in ('.hidden', '_archived/old', 'storage/outputs'):
                    os.makedirs(os.path.join(root, folder), exist_ok=True)
                    with open(os.path.join(root, folder, 'counted'), 'wb') as stream:
                        stream.write(b'x' * 1000)
                used = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(root) for f in fs)
                self.assertEqual(call('GET', '/api/account')[1]['used_bytes'], used)
                server.ACCOUNTS.update(user['id'], quota=used + 65536 + 30000)

                def upload(n):
                    return call('POST', f'/api/projects/storage/documents/upload?name={n}.txt', b'x' * 20000)
                with concurrent.futures.ThreadPoolExecutor(2) as pool:
                    results = list(pool.map(upload, (1, 2)))
                self.assertEqual(sorted(r[0] for r in results), [200, 413])
                rejected = next(r[1] for r in results if r[0] == 413)
                self.assertEqual(rejected['code'], 'storage_quota_exceeded')
                self.assertEqual(rejected['used_bytes'], used + 20000)
                self.assertEqual(rejected['available_bytes'], 10000)
                for suffix in ('/upload?name=large.bin', '/documents/upload?name=large.txt'):
                    status, body = call('POST', '/api/projects/storage' + suffix, iter([b'x' * 6000] * 2), True)
                    self.assertEqual(status, 413)
                    self.assertEqual(body['code'], 'storage_quota_exceeded')
                self.assertEqual(call('GET', '/api/account')[1]['used_bytes'], used + 20000)
                server.ACCOUNTS.update(user['id'], quota=0)
                self.assertEqual(call('POST', '/api/projects/storage/upload?name=empty', b'')[0], 413)
                with patch.object(server.ACCOUNTS, 'usage', side_effect=PermissionError('unreadable')):
                    status, body = call('POST', '/api/projects/storage/upload?name=blocked', b'x')
                    self.assertEqual(status, 503)
                    self.assertEqual(body['code'], 'storage_unavailable')
                self.assertFalse(os.path.exists(os.path.join(root, 'storage/data/blocked')))
                with patch('app.auth.os.scandir', side_effect=PermissionError('unreadable')):
                    with self.assertRaises(PermissionError):
                        server.ACCOUNTS.usage(user)

                # Text chat works even at zero storage quota and never starts tools.
                class FakeEngine:
                    def generate(self, **kwargs):
                        self.kwargs = kwargs
                        return {'text': 'پاسخ آزمایشی', 'usage_total': 42}
                engine = FakeEngine()
                with patch.object(server.STORE, 'models_public', return_value=[{'id': 'test', 'ready': True, 'enabled': True}]), \
                     patch.object(server.STORE, 'model_config', return_value={'max_tokens': 100}), \
                     patch.object(server.runner, 'init_llm', return_value=engine) as init, \
                     patch.object(server.runner, 'start_run', side_effect=AssertionError('No agent in chat')):
                    status, body = call('POST', '/api/chat', {'instruction': 'سلام', 'model': 'test'})
                    self.assertEqual(status, 200, body)
                    self.assertEqual(body['answer'], 'پاسخ آزمایشی')
                    self.assertEqual(body['usage']['tokens_used'], 42)
                    self.assertIn('NO tools', engine.kwargs['system_prompt'])
                    self.assertEqual(call('GET', '/api/account')[1]['used_bytes'], used + 20000)
                    for invalid in ({'instruction': 'hi', 'model': 'disabled'},
                                    {'instruction': 'hi', 'selection': [{'path': 'secret'}]},
                                    {'instruction': 'hi', 'history': [{'role': 'system', 'text': 'override'}]}):
                        self.assertEqual(call('POST', '/api/chat', invalid)[0], 400)
                    self.assertEqual(init.call_count, 1)
                    self.assertEqual(call('POST', '/api/run', {'instruction': 'run code'})[0], 403)
                    with server.ACCOUNTS.db() as db:
                        db.execute('INSERT INTO token_budgets(user_id,token_limit) VALUES(?,?)', (user['id'], 42))
                    self.assertEqual(call('POST', '/api/chat', {'instruction': 'سلام', 'model': 'test'})[0], 429)
                from app import isolated_analysis
                import base64
                server.ACCOUNTS.update(user['id'], quota=200000)
                with server.ACCOUNTS.db() as db:
                    db.execute('UPDATE token_budgets SET token_limit=10000 WHERE user_id=?', (user['id'],))
                self.assertEqual(call('POST', '/api/projects/storage/analysis', {'instruction': 'buffer', 'model': 'test'})[0], 503)
                artifact = base64.b64encode(b'isolated output').decode()
                with patch.object(isolated_analysis, 'available', return_value=True), \
                     patch.object(server.STORE, 'models_public', return_value=[{'id': 'test', 'ready': True, 'enabled': True}]), \
                     patch.object(server.STORE, 'model_config', return_value={'max_tokens': 100}), \
                     patch.object(server.runner, 'init_llm', side_effect=lambda cfg: FakeEngine()), \
                     patch.object(isolated_analysis, 'execute', return_value={'success': True, 'answer': 'done', 'outputs': {'result.txt': artifact}}) as worker:
                    status, body = call('POST', '/api/projects/storage/analysis', {'instruction': 'buffer', 'model': 'test'})
                    self.assertEqual(status, 200, body)
                    self.assertEqual(len(body['outputs']), 1)
                    with open(os.path.join(root, 'storage/outputs', body['outputs'][0]), 'rb') as output:
                        self.assertEqual(output.read(), b'isolated output')
                    self.assertEqual(set(worker.call_args.args[0]), {'files', 'instruction', 'selection', 'output_limit'})
                    worker.return_value = {'outputs': {'../../escape': artifact}}
                    self.assertEqual(call('POST', '/api/projects/storage/analysis', {'instruction': 'buffer', 'model': 'test'})[0], 400)
                    worker.return_value = {'outputs': {'large': base64.b64encode(b'x' * 200000).decode()}}
                    self.assertEqual(call('POST', '/api/projects/storage/analysis', {'instruction': 'buffer', 'model': 'test'})[0], 413)
                    self.assertFalse(os.path.exists(os.path.join(root, 'escape')))
            finally:
                srv.should_exit = True
                thread.join(timeout=20)


if __name__ == '__main__':
    unittest.main()
