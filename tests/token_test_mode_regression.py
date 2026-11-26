"""Offline checks for reversible test-mode accounting bypass."""
import os
import tempfile
import unittest
from unittest.mock import patch

from app.auth import Accounts
from app.token_budget import TokenBudgetExceeded, meter_engine


class TokenTestModeTests(unittest.TestCase):
    def test_disabled_budget_skips_queries_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {'GISCLAW_TOKEN_BUDGET_ENABLED': '1'}):
                original = Accounts(root)
            uid = original.create('test_account', 'test')['id']
            with original.db() as db:
                db.execute('INSERT INTO token_budgets VALUES(?,100)', (uid,))
            rid, _ = original.tokens.reserve(uid, 10, 90)
            original.tokens.settle(rid, 100)
            with original.db() as db:
                before = [tuple(r) for r in db.execute('SELECT * FROM token_requests')]
            with patch.dict(os.environ, {'GISCLAW_TOKEN_BUDGET_ENABLED': '0'}):
                disabled = Accounts(root)
            class Engine:
                def generate(self, prompt, max_tokens=2048):
                    return {'text': 'ok', 'usage_total': 50, 'cap': max_tokens}
            engine = Engine()
            # Fail on any accounting query, not just on DB writes.
            with patch.object(disabled, 'db', side_effect=AssertionError('Accounting DB accessed')):
                self.assertIs(meter_engine(engine, disabled.tokens, uid), engine)
                disabled.tokens.require_available(uid)
                self.assertIsNone(disabled.tokens.status(uid)['tokens_remaining'])
                self.assertEqual(disabled.tokens.reserve(uid, 500000, 2048), (None, 2048))
                disabled.tokens.settle(rid, 50)
                self.assertEqual(engine.generate('hi')['cap'], 2048)
            with original.db() as db:
                self.assertEqual(before, [tuple(r) for r in db.execute('SELECT * FROM token_requests')])
            with patch.dict(os.environ, {'GISCLAW_TOKEN_BUDGET_ENABLED': '1'}):
                restored = Accounts(root)
            with self.assertRaises(TokenBudgetExceeded):
                restored.tokens.require_available(uid)
            self.assertEqual(restored.tokens.status(uid)['tokens_used'], 100)

    def test_enabled_is_safe_default(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ):
            os.environ.pop('GISCLAW_TOKEN_BUDGET_ENABLED', None)
            self.assertTrue(Accounts(root).tokens.enabled)


if __name__ == '__main__':
    unittest.main()
