"""Full HTTP -> real engine with stub transport -> rootless GIS -> retrieval.

Run standalone in a disposable coordinator with the rootless socket mounted.
All accounts/files are temporary; no real model or API key is used.
"""
import base64
import http.client
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch


class AnalysisRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flags = patch.dict(os.environ, {'GISCLAW_TEXT_CHAT_ENABLED': '1'})
        flags.start()
        cls.addClassCleanup(flags.stop)
        cls.workspace = tempfile.TemporaryDirectory()
        os.environ['GISCLAW_WORKSPACE'] = cls.workspace.name
        from app import server, isolated_analysis
        import uvicorn
        cls.server, cls.isolated = server, isolated_analysis
        assert isolated_analysis.available(), 'Real rootless runtime required'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.srv = uvicorn.Server(uvicorn.Config(server.app, host='127.0.0.1', port=cls.port, log_level='error'))
        cls.thread = threading.Thread(target=cls.srv.run)
        cls.thread.start()
        for _ in range(100):
            if cls.srv.started:
                break
            time.sleep(.05)
        assert cls.srv.started

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(20)
        cls.workspace.cleanup()

    def call(self, method, path, body=None, cookie=None, raw=False):
        headers = {'X-GISclaw': '1'}
        if cookie:
            headers['Cookie'] = cookie
        if not raw and body is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(body).encode()
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=120)
        try:
            conn.request(method, path, body, headers)
            response = conn.getresponse()
            data = response.read()
            return response.status, json.loads(data), response.getheader('set-cookie')
        finally:
            conn.close()

    def make_user(self, name):
        user = self.server.ACCOUNTS.create(name, 'test-password')
        status, body, cookie = self.call('POST', '/api/auth/login', {'username': name, 'password': 'test-password'})
        self.assertEqual(status, 200, body)
        self.assertTrue(body['isolated_analysis_enabled'])
        cookie = cookie.split(';')[0]
        self.assertEqual(self.call('POST', '/api/projects', {'name': 'project'}, cookie)[0], 200)
        return user, cookie

    def test_http_selected_features_and_account_isolation(self):
        from app.feature_selection import source_version
        alice, a = self.make_user('analysis_alice')
        bob, b = self.make_user('analysis_bob')
        layer = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'properties': {'id': n}, 'geometry': {'type': 'Point', 'coordinates': [51 + n * .01, 35]}}
            for n in (1, 2)]}
        self.assertEqual(self.call('POST', '/api/projects/project/upload?name=points.geojson', json.dumps(layer).encode(), a, True)[0], 200)
        path = Path(self.server.ACCOUNTS.root(alice)) / 'project/data/points.geojson'
        # A generated result larger than the input cap must not block unrelated
        # analyses. Keep sufficient account storage; this tests a different cap.
        self.server.ACCOUNTS.update(alice['id'], quota=128 * 1024 * 1024)
        previous = path.parent.parent / 'outputs/large_previous.geojson'
        with previous.open('wb') as stream:
            stream.truncate(55 * 1024 * 1024)
        selected = [{'where': 'data', 'path': 'points.geojson', 'ids': [1], 'version': source_version(str(path))}]
        calls = []
        plan = [
            ('operation_help', {'op': 'buffer'}),
            ('load_vector', {'path': 'selection/layer_1.geojson', 'var_name': 'pts'}),
            ('geoprocess', {'op': 'buffer', 'inputs': {'layer': 'pts'}, 'params': {'distance': 100}, 'output': 'buffered', 'save_as': 'pred_results/buffer.geojson'}),
            ('finish', {'summary': 'Selected feature buffer verified'}),
        ]
        from src.agent.llm_engine import OpenAIEngine
        def completion(**kwargs):
            calls.append(kwargs)
            if not plan:
                raise AssertionError('Unexpected extra provider call')
            action, args = plan.pop(0)
            text = 'Thought: verify\nAction: ' + action + '\nArgs: ' + json.dumps(args)
            return NS(choices=[NS(message=NS(content=text))], usage=NS(prompt_tokens=30, completion_tokens=20))
        def engine(cfg):
            # Preserve the REAL generate signature and implementation. Only the
            # provider transport is stubbed; accepting **kwargs here hid a bug.
            model = OpenAIEngine(model='test', api_key='not-real')
            model.client = NS(chat=NS(completions=NS(create=completion)))
            return model
        with patch.object(self.server.STORE, 'models_public', return_value=[{'id': 'test', 'enabled': True, 'ready': True}]), \
             patch.object(self.server.STORE, 'model_config', return_value={'max_tokens': 2048}), \
             patch.object(self.server.runner, 'init_llm', side_effect=engine):
            status, result, _ = self.call('POST', '/api/projects/project/analysis', {'model': 'test', 'instruction': 'Buffer only selected points by 100 metres', 'selection': selected, 'account_id': bob['id']}, a)
            self.assertEqual(status, 200, result)
            self.assertTrue(result['success'], result)
            self.assertEqual(result['answer'], 'Selected feature buffer verified')
            self.assertTrue(result['code'])
            self.assertTrue(result['steps'])
            self.assertTrue(all('thought' not in step for step in result['steps']))
            self.assertEqual(len(calls), 4)
            self.assertEqual(previous.stat().st_size, 55 * 1024 * 1024)
            self.assertEqual(result['usage']['tokens_used'], 200)
            self.assertEqual(self.server.ACCOUNTS.tokens.status(bob['id'])['tokens_used'], 0)
            filename = result['outputs'][0]
            status, output, _ = self.call('GET', '/api/projects/project/file?where=outputs&path=' + filename, cookie=a)
            self.assertEqual(status, 200, output)
            self.assertEqual(len(output['features']), 1)
            self.assertEqual(output['features'][0]['properties']['id'], 2)
            import geopandas as gpd
            result_frame = gpd.GeoDataFrame.from_features(output['features'], crs=4326).to_crs(32639)
            self.assertTrue(31000 < result_frame.area.iloc[0] < 32000)
            self.assertEqual(self.call('GET', '/api/projects/project/file?where=outputs&path=' + filename, cookie=b)[0], 404)
            self.assertEqual(self.call('GET', '/api/account')[0], 401)
            selected[0]['version'] = 'stale'
            status, result, _ = self.call('POST', '/api/projects/project/analysis', {'model': 'test', 'instruction': 'buffer', 'selection': selected}, a)
            self.assertEqual(status, 409, result)
            self.assertEqual(result['code'], 'selection_changed')
            self.assertEqual(len(calls), 4)

    def test_chat_real_engine_contracts(self):
        from src.agent.llm_engine import OpenAIEngine, ClaudeEngine
        for kind in ('openai', 'claude'):
            with self.subTest(kind=kind):
                user, cookie = self.make_user('chat_contract_' + kind)
                calls = []
                def completion(**kwargs):
                    calls.append(kwargs)
                    if kind == 'openai':
                        return NS(choices=[NS(message=NS(content='پاسخ تست'))], usage=NS(prompt_tokens=30, completion_tokens=12))
                    return NS(content=[NS(type='text', text='پاسخ تست')], usage=NS(input_tokens=30, output_tokens=12))
                model = OpenAIEngine(model='test', api_key='not-real') if kind == 'openai' else ClaudeEngine(model='test', api_key='not-real')
                model.client = NS(chat=NS(completions=NS(create=completion))) if kind == 'openai' else NS(messages=NS(create=completion))
                with patch.object(self.server.STORE, 'models_public', return_value=[{'id': 'test', 'enabled': True, 'ready': True}]), \
                     patch.object(self.server.STORE, 'model_config', return_value={'max_tokens': 100}), \
                     patch.object(self.server.runner, 'init_llm', return_value=model):
                    status, body, _ = self.call('POST', '/api/chat', {'instruction': 'سلام', 'model': 'test'}, cookie)
                    self.assertEqual(status, 200, body)
                    self.assertEqual(body['answer'], 'پاسخ تست')
                    self.assertEqual(body['usage']['tokens_used'], 42)
                    self.assertEqual(body['usage']['tokens_reserved'], 0)
                    self.assertEqual(len(calls), 1)

    def test_missing_required_prompt_never_reserves_tokens(self):
        from app.token_budget import TOKEN_LIMIT, meter_engine
        from src.agent.llm_engine import OpenAIEngine, ClaudeEngine
        for kind in (OpenAIEngine, ClaudeEngine):
            with self.subTest(engine=kind.__name__):
                user, _ = self.make_user('missing_arg_' + kind.__name__)
                engine = meter_engine(kind(model='test', api_key='not-real'), self.server.ACCOUNTS.tokens, user['id'])
                with self.assertRaises(TypeError):
                    engine.generate(user_message='hello', max_tokens=10)
                usage = self.server.ACCOUNTS.tokens.status(user['id'])
                self.assertEqual(usage['tokens_reserved'], 0)
                self.assertEqual(usage['tokens_remaining'], TOKEN_LIMIT)

    def test_gis_only_without_accounting(self):
        from src.agent.llm_engine import OpenAIEngine
        user, cookie = self.make_user('unmetered_test')
        with self.server.ACCOUNTS.db() as db:
            db.execute('INSERT INTO token_budgets VALUES(?,0)', (user['id'],))
            before = [tuple(r) for r in db.execute('SELECT * FROM token_requests ORDER BY id')]
        calls = []
        replies = [
            'Thought: create test geometry\nAction: execute\nArgs: ' + json.dumps({'code': "g = gpd.GeoDataFrame({'name':['test']}, geometry=[Point(0,0)], crs='EPSG:3857')\ng['geometry'] = g.buffer(100)\ng.to_file('pred_results/buffer.geojson', driver='GeoJSON')"}),
            'Thought: done\nAction: finish\nArgs: {"summary":"test mode verified"}',
        ]
        def completion(**kwargs):
            calls.append(kwargs)
            return NS(choices=[NS(message=NS(content=replies.pop(0)))], usage=NS(prompt_tokens=30, completion_tokens=12))
        def engine(cfg):
            model = OpenAIEngine(model='test', api_key='not-real')
            model.client = NS(chat=NS(completions=NS(create=completion)))
            return model
        with patch.dict(os.environ, {'GISCLAW_TEXT_CHAT_ENABLED': '0'}), \
             patch.object(self.server.ACCOUNTS.tokens, 'enabled', False), \
             patch.object(self.server.STORE, 'models_public', return_value=[{'id': 'test', 'enabled': True, 'ready': True}]), \
             patch.object(self.server.STORE, 'model_config', return_value={'max_tokens': 100}), \
             patch.object(self.server.runner, 'init_llm', side_effect=engine) as init:
            self.server.ACCOUNTS.create('gis_only_admin', 'test-password', 'admin')
            token, _ = self.server.ACCOUNTS.login('gis_only_admin', 'test-password', 'gis_only_test')
            for session in (cookie, 'gisclaw_session=' + token):
                status, body, _ = self.call('POST', '/api/chat', {'instruction': 'test', 'model': 'test'}, session)
                self.assertEqual(status, 403, body)
                self.assertEqual(body['code'], 'text_chat_disabled')
                status, profile, _ = self.call('GET', '/api/auth/me', cookie=session)
                self.assertEqual(status, 200)
                self.assertFalse(profile['chat_enabled'])
                self.assertTrue(profile['analysis_enabled'])
            init.assert_not_called()
            self.assertEqual(self.call('POST', '/api/chat', {'instruction': 'test', 'model': 'test'})[0], 401)
            status, body, _ = self.call('POST', '/api/projects/project/analysis', {'instruction': 'Make a test buffer', 'model': 'test'}, cookie)
            self.assertEqual(status, 200, body)
            self.assertFalse(body['usage']['token_budget_enabled'])
            self.assertIsNone(body['usage']['tokens_used'])
            self.assertTrue(body['success'], body)
            self.assertTrue(body['outputs'], body)
            status, account, _ = self.call('GET', '/api/account', cookie=cookie)
            self.assertEqual(status, 200)
            self.assertFalse(account['token_budget_enabled'])
            self.assertFalse(account['chat_enabled'])
        self.assertEqual(len(calls), 2)
        with self.server.ACCOUNTS.db() as db:
            self.assertEqual(before, [tuple(r) for r in db.execute('SELECT * FROM token_requests ORDER BY id')])

    def test_gis_greeting_returns_text_without_creating_an_output(self):
        _, cookie = self.make_user('gis_greeting')
        from src.agent.llm_engine import OpenAIEngine
        calls = []
        answer = 'سلام! برای تحلیل لایه‌های نقشه چه کمکی می‌خواهید؟'
        def completion(**kwargs):
            calls.append(kwargs)
            self.assertEqual(len(calls), 1, 'Greeting must not enter the output guard loop')
            text = 'Thought: greeting\nAction: respond\nArgs: ' + json.dumps({'summary': answer})
            return NS(choices=[NS(message=NS(content=text))], usage=NS(prompt_tokens=30, completion_tokens=20))
        model = OpenAIEngine(model='test', api_key='not-real')
        model.client = NS(chat=NS(completions=NS(create=completion)))
        with patch.object(self.server.STORE, 'models_public', return_value=[{'id': 'test', 'enabled': True, 'ready': True}]), \
             patch.object(self.server.STORE, 'model_config', return_value={}), \
             patch.object(self.server.runner, 'init_llm', return_value=model):
            status, body, _ = self.call('POST', '/api/projects/project/analysis', {'model': 'test', 'instruction': 'سلام'}, cookie)
        self.assertEqual(status, 200, body)
        self.assertTrue(body['success'], body)
        self.assertEqual(body['answer'], answer)
        self.assertEqual(body['outputs'], [])
        self.assertEqual(len(calls), 1)

    def test_failures_have_safe_diagnostic_ids(self):
        _, cookie = self.make_user('diagnostic_user')
        with patch.object(self.server.STORE, 'models_public', return_value=[{'id': 'test', 'enabled': True, 'ready': True}]), \
             patch.object(self.server.STORE, 'model_config', return_value={}), \
             patch.object(self.server.runner, 'init_llm'):
            for failure, code, expected in ((TypeError('secret-prompt'), 'analysis_internal_error', 500),
                                            (ValueError('secret-payload'), 'analysis_invalid_data', 400),
                                            (self.server.runner.ModelTimeout('Model did not respond in time'), 'model_timeout', 504),
                                            (self.server.runner.ApiCallFailed('secret-key'), 'model_call_failed', 502),
                                            (self.server.runner.ApiCallFailed('secret-upstream', provider_status=429), 'model_call_failed', 502)):
                with patch.object(self.isolated, 'execute', side_effect=failure), self.assertLogs('app.isolated_analysis', level='ERROR') as logs:
                    status, body, _ = self.call('POST', '/api/projects/project/analysis', {'model': 'test', 'instruction': 'buffer'}, cookie)
                self.assertEqual(status, expected)
                self.assertEqual(body['code'], code)
                self.assertEqual(len(body['error_id']), 12)
                self.assertIn(body['error_id'], '\n'.join(logs.output))
                self.assertNotIn('secret-', json.dumps(body) + '\n'.join(logs.output))
        with patch.object(self.server.STORE, 'models_public', return_value=[{'id': 'test', 'enabled': True, 'ready': True}]), \
             patch.object(self.server.STORE, 'model_config', return_value={}), \
             patch.object(self.server.runner, 'init_llm', side_effect=self.server.runner.ModelTimeout('Model did not respond in time')):
            status, body, _ = self.call('POST', '/api/chat', {'instruction': 'test', 'model': 'test'}, cookie)
            self.assertEqual(status, 504, body)
            self.assertEqual(body['code'], 'model_timeout')

    def test_validation_busy_tokens_and_untrusted_outputs(self):
        user, cookie = self.make_user('analysis_validation')
        payload = {'model': 'test', 'instruction': 'buffer'}
        endpoint = '/api/projects/project/analysis'
        with patch.object(self.server.STORE, 'models_public', return_value=[{'id': 'test', 'enabled': True, 'ready': True}]), \
             patch.object(self.server.STORE, 'model_config', return_value={}), \
             patch.object(self.server.runner, 'init_llm') as init:
            self.assertEqual(self.call('POST', endpoint, b'{broken', cookie, True)[0], 400)
            self.assertEqual(self.call('POST', endpoint, {**payload, 'selection': [{'where': 'data', 'path': 'a', 'ids': [True]}]}, cookie)[0], 400)
            with self.isolated.JOB_SLOT:
                status, body, _ = self.call('POST', endpoint, payload, cookie)
                self.assertEqual(status, 409)
                self.assertEqual(body['code'], 'analysis_busy')
            init.assert_not_called()
            with patch.object(self.isolated, 'execute', return_value={'outputs': {'../escape': 'YQ=='}}):
                self.assertEqual(self.call('POST', endpoint, payload, cookie)[0], 400)
            for outputs, code in (([], 'worker_invalid_outputs'), ({'bad.csv': 'invalid base64!'}, 'worker_invalid_file')):
                with patch.object(self.isolated, 'execute', return_value={'outputs': outputs}):
                    status, body, _ = self.call('POST', endpoint, payload, cookie)
                    self.assertEqual(status, 502)
                    self.assertEqual(body['code'], code)
                    self.assertEqual(len(body['error_id']), 12)
            self.server.ACCOUNTS.update(user['id'], quota=self.server.ACCOUNTS.usage(user) + 65536 + 1000)
            with patch.object(self.isolated, 'execute', return_value={'outputs': {'large.txt': base64.b64encode(b'x' * 2000).decode()}}):
                status, body, _ = self.call('POST', endpoint, payload, cookie)
                self.assertEqual(status, 413)
                self.assertEqual(body['code'], 'storage_quota_exceeded')
            root = Path(self.server.ACCOUNTS.root(user))
            self.assertFalse((root / 'escape').exists())
            self.assertEqual(list((root / 'project/outputs').iterdir()), [])
            with self.server.ACCOUNTS.db() as db:
                db.execute('INSERT INTO token_budgets VALUES(?,0)', (user['id'],))
            self.assertEqual(self.call('POST', endpoint, payload, cookie)[0], 429)
            with patch.object(self.isolated, 'available', return_value=False):
                self.assertEqual(self.call('POST', endpoint, payload, cookie)[0], 503)

    def test_readiness_recovers_after_temporary_failure(self):
        import subprocess
        info = {'SecurityOptions': ['name=rootless', 'name=seccomp,profile=builtin'], 'CgroupVersion': '2', 'MemoryLimit': True, 'PidsLimit': True}
        with patch.object(self.isolated, '_readiness', (0, False)), \
             patch.object(self.isolated.time, 'monotonic', side_effect=[10, 11, 16]), \
             patch.object(self.isolated.subprocess, 'run', side_effect=[OSError('temporarily down'), subprocess.CompletedProcess([], 0, json.dumps(info))]) as probe:
            self.assertFalse(self.isolated.available())
            self.assertFalse(self.isolated.available())
            self.assertTrue(self.isolated.available())
            self.assertEqual(probe.call_count, 2)

    def test_timeout_removes_worker(self):
        import subprocess
        calls = []
        class Engine:
            def generate(self, **kwargs):
                calls.append(kwargs)
                return {'text': 'Thought: wait\nAction: execute\nArgs: {"code":"import time; time.sleep(20)"}'}
        with patch.object(self.isolated, 'command', wraps=self.isolated.command) as command, self.assertRaises(self.isolated.AnalysisError) as error:
            self.isolated.execute({'files': {}, 'instruction': 'wait', 'selection': [], 'output_limit': 1000}, Engine(), timeout=3)
        self.assertEqual(error.exception.code, 'analysis_timeout')
        self.assertTrue(calls)
        containers = subprocess.run(['docker', 'ps', '-a', '--filter', 'name=' + command.call_args.args[0], '--format', '{{.Names}}'], capture_output=True, text=True, check=True)
        self.assertEqual(containers.stdout.strip(), '')


if __name__ == '__main__':
    unittest.main()
