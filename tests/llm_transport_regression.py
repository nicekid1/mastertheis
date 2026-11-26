"""Real installed SDKs with in-memory HTTP transports; no live model calls."""
import importlib
import os
import unittest
from unittest.mock import patch

from app.llm_transport import configure_engine
from app.runner import guard_engine, init_llm, ModelTimeout
from src.agent.llm_engine import OpenAIEngine, ClaudeEngine


class TransportTests(unittest.TestCase):
    def test_timeouts_do_not_retry_and_are_classified_for_both_engines(self):
        for sdk_name, cls, client_name in (('openai', OpenAIEngine, 'OpenAI'), ('anthropic', ClaudeEngine, 'Anthropic')):
            with self.subTest(engine=sdk_name):
                sdk = importlib.import_module(sdk_name)
                base_client = importlib.import_module(sdk_name + '._base_client')
                # SDK releases may use httpx2 instead of legacy httpx. Match
                # the installed client so this exercises its real transport.
                http = getattr(base_client, 'httpx2', None) or getattr(base_client, 'httpx')
                calls = []
                def fail(request):
                    calls.append(request)
                    raise http.ReadTimeout('private transport details', request=request)
                with http.Client(transport=http.MockTransport(fail)) as transport:
                    engine = cls(model='test', api_key='not-real')
                    engine.client = getattr(sdk, client_name)(api_key='not-real', base_url='https://example.test/v1', http_client=transport)
                    with patch.dict(os.environ, {'GISCLAW_LLM_TIMEOUT_SECONDS': '60', 'GISCLAW_TOKEN_BUDGET_ENABLED': '0'}):
                        configure_engine(engine)
                    self.assertEqual(engine.client.max_retries, 0)
                    self.assertEqual(engine.client.timeout, 60)
                    with self.assertRaises(ModelTimeout) as result:
                        guard_engine(engine).generate(prompt='test', max_tokens=50)
                    self.assertNotIn('private', str(result.exception))
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0].extensions['timeout']['read'], 60)

    def test_application_initialization_applies_policy(self):
        for kind in ('openai', 'claude'):
            with self.subTest(engine=kind), patch.dict(os.environ, {'GISCLAW_LLM_TIMEOUT_SECONDS': '45'}):
                engine = init_llm({'engine': kind, 'api_key': 'not-real', 'model_name': 'test', 'max_tokens': 100})
                try:
                    self.assertEqual(engine.client.timeout, 45)
                    self.assertEqual(engine.client.max_retries, 0)
                finally:
                    engine.client.close()

    def test_timeout_setting_validation(self):
        for value in ('0', '301', 'nan', 'inf', 'bad'):
            with self.subTest(value=value), patch.dict(os.environ, {'GISCLAW_LLM_TIMEOUT_SECONDS': value}):
                with self.assertRaises(ValueError):
                    configure_engine(object())

    def test_longer_test_timeout_reaches_transport_without_retries(self):
        sdk = importlib.import_module('openai')
        base = importlib.import_module('openai._base_client')
        http = getattr(base, 'httpx2', None) or getattr(base, 'httpx')
        calls = []
        def delayed(request):
            calls.append(request)
            raise http.ReadTimeout('private transport details', request=request)
        with http.Client(transport=http.MockTransport(delayed)) as transport:
            engine = OpenAIEngine(model='test', api_key='not-real')
            engine.client = sdk.OpenAI(api_key='not-real', base_url='https://example.test/v1', http_client=transport)
            with patch.dict(os.environ, {'GISCLAW_LLM_TIMEOUT_SECONDS': '180', 'GISCLAW_TOKEN_BUDGET_ENABLED': '0'}):
                configure_engine(engine)
            self.assertEqual(engine.client.timeout, 180)
            self.assertEqual(engine.client.max_retries, 0)
            with self.assertRaises(ModelTimeout) as caught:
                guard_engine(engine).generate(prompt='test', max_tokens=50)
            self.assertNotIn('private', str(caught.exception))
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].extensions['timeout']['read'], 180)


if __name__ == '__main__':
    unittest.main()
