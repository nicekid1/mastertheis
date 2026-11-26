"""Offline quota repair regression; uses temporary SQLite only."""
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest

from app.auth import Accounts
from app.token_budget import TokenBudgetExceeded, meter_engine


class TokenReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.accounts = Accounts(self.tmp.name)
        self.uid = self.accounts.create('repair_test', 'test')['id']
        self.budget = self.accounts.tokens
        with self.accounts.db() as db:
            db.execute('INSERT INTO token_budgets(user_id,token_limit) VALUES(?,10000)', (self.uid,))

    def test_three_historical_reservations_repaired_without_changing_limit(self):
        ids = [self.budget.reserve(self.uid, 0, n)[0] for n in (3526, 3522, 2952)]
        with self.assertRaisesRegex(TokenBudgetExceeded, 'رزرو'):
            self.budget.require_available(self.uid)
        for rid in ids:
            self.assertTrue(self.budget.reconcile_unbilled(self.uid, rid, 'Verified local pre-provider failure'))
            self.assertFalse(self.budget.reconcile_unbilled(self.uid, rid, 'Retry repair'))
        self.assertEqual(self.budget.status(self.uid), dict(token_budget_enabled=True, token_limit=10000, tokens_used=0, tokens_reserved=0, tokens_remaining=10000))
        self.budget.require_available(self.uid)
        with self.accounts.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*),SUM(released) FROM token_reconciliations').fetchone()[:], (3, 10000))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM token_requests').fetchone()[0], 3)
        self.assertEqual(Accounts(self.tmp.name).tokens.status(self.uid)['tokens_remaining'], 10000)

    def test_settled_usage_and_other_accounts_are_protected(self):
        rid, _ = self.budget.reserve(self.uid, 100, 100)
        self.budget.settle(rid, 140)
        with self.assertRaises(ValueError):
            self.budget.reconcile_unbilled(self.uid, rid, 'Not allowed')
        other = self.accounts.create('other_user', 'test')['id']
        pending, _ = self.budget.reserve(other, 10, 10)
        with self.assertRaises(ValueError):
            self.budget.reconcile_unbilled(self.uid, pending, 'Wrong owner')
        self.assertEqual(self.budget.status(self.uid)['tokens_used'], 140)
        self.assertEqual(self.budget.status(other)['tokens_reserved'], 20)

    def test_concurrent_repair_is_idempotent(self):
        rid, _ = self.budget.reserve(self.uid, 100, 100)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.budget.reconcile_unbilled(self.uid, rid, 'Verified failure'), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.budget.settle(rid, 200)  # a delayed settlement must not undo an audit
        self.assertEqual(self.budget.status(self.uid)['tokens_used'], 0)

    def test_uncertain_failures_still_keep_reservation(self):
        class Engine:
            def generate(self, prompt, max_tokens=100):
                raise TimeoutError('Provider may have processed the request')
        with self.assertRaises(TimeoutError):
            meter_engine(Engine(), self.budget, self.uid).generate('hello')
        self.assertGreater(self.budget.status(self.uid)['tokens_reserved'], 0)
        with self.accounts.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM token_reconciliations').fetchone()[0], 0)

    def test_actual_exhaustion_and_reserved_exhaustion_have_distinct_messages(self):
        rid, _ = self.budget.reserve(self.uid, 0, 10000)
        with self.assertRaisesRegex(TokenBudgetExceeded, 'رزرو'):
            self.budget.reserve(self.uid, 0, 1)
        self.budget.settle(rid, 10000)
        with self.assertRaisesRegex(TokenBudgetExceeded, 'تمام شده'):
            self.budget.require_available(self.uid)

    def test_missing_prompt_does_not_reserve(self):
        class Engine:
            def generate(self, prompt, max_tokens=100):
                raise AssertionError('Must not be called')
        with self.assertRaises(TypeError):
            meter_engine(Engine(), self.budget, self.uid).generate(max_tokens=100)
        self.assertEqual(self.budget.status(self.uid)['tokens_remaining'], 10000)


if __name__ == '__main__':
    unittest.main()
