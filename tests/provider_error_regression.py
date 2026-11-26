import unittest
from types import SimpleNamespace as NS
from src.agent.llm_engine import OpenAIEngine
from app.runner import guard_engine, ApiCallFailed


class ProviderErrors(unittest.TestCase):
    def test_status_survives_engine_and_guard_without_parsing_error_text(self):
        for status in (400, 401, 402, 403, 404, 429, 500, 502, 503, 504, None, 'secret', True):
            with self.subTest(status=status):
                class Failure(Exception):
                    status_code = status
                def fail(**kwargs):
                    raise Failure('secret-key-and-provider-payload')
                engine = OpenAIEngine(model='test', api_key='not-real')
                engine._send_temperature = False
                engine.client = NS(chat=NS(completions=NS(create=fail)))
                with self.assertRaises(ApiCallFailed) as caught:
                    guard_engine(engine).generate(prompt='test')
                self.assertEqual(caught.exception.provider_status, status if type(status) is int else None)


if __name__ == '__main__':
    unittest.main()
