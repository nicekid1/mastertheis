from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS
import pytest
from app.auth import Accounts
from app.token_budget import TokenBudgetExceeded, meter_engine
from src.agent.llm_engine import OpenAIEngine, ClaudeEngine


@pytest.fixture
def account(tmp_path):
    store = Accounts(str(tmp_path))
    user = store.create('budget_user', '1')
    return store, user['id']


def test_default_persistence_concurrency_and_idempotent_settlement(account):
    store, uid = account
    assert store.tokens.status(uid)['tokens_remaining'] == 10000
    def reserve(_):
        try:
            return store.tokens.reserve(uid, 2000, 8000)[0]
        except TokenBudgetExceeded:
            return None
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(reserve, range(2)))
    ids = [r for r in results if r]
    assert len(ids) == 1
    assert store.tokens.status(uid)['tokens_remaining'] == 0
    store.tokens.settle(ids[0], 1000)
    store.tokens.settle(ids[0], 1)
    assert Accounts(store.workspace).tokens.status(uid)['tokens_remaining'] == 9000
    other = store.create('other_budget_user', '1')
    assert store.tokens.status(other['id'])['tokens_remaining'] == 10000


def test_full_budget_stops_before_network(account):
    store, uid = account
    rid, _ = store.tokens.reserve(uid, 100, 9900)
    store.tokens.settle(rid, 10000)
    class Engine:
        max_tokens = 2000
        def generate(self, prompt='', max_tokens=None):
            pytest.fail('Network call must not occur')
    with pytest.raises(TokenBudgetExceeded):
        meter_engine(Engine(), store.tokens, uid).generate('hello')


def test_reasoning_cap_and_cached_usage(account):
    store, uid = account
    seen = []
    def create(**kw):
        seen.append(kw)
        return NS(choices=[NS(message=NS(content='ok'))], usage=NS(prompt_tokens=100, completion_tokens=40, prompt_tokens_details=NS(cached_tokens=20)))
    engine = OpenAIEngine(model='gpt-5-test', api_key='test', max_tokens=20000)
    engine.client = NS(chat=NS(completions=NS(create=create)))
    result = meter_engine(engine, store.tokens, uid).generate('hello')
    assert seen[0]['max_completion_tokens'] == 10000 - 1024 - 5
    assert 'temperature' not in seen[0]
    assert result['usage_total'] == 140  # cache already included in prompt tokens
    assert store.tokens.status(uid)['tokens_used'] == 140
    assert store.tokens.status(uid)['tokens_reserved'] == 0


def test_claude_cache_reads_and_writes_count(account):
    store, uid = account
    engine = ClaudeEngine(model='test', api_key='test')
    engine.client = NS(messages=NS(create=lambda **kw: NS(content=[NS(type='text', text='ok')], usage=NS(input_tokens=100, output_tokens=40, cache_read_input_tokens=20, cache_creation_input_tokens=30))))
    result = meter_engine(engine, store.tokens, uid).generate('', user_segments=['history', 'question'])
    assert result['usage_total'] == 190
    assert store.tokens.status(uid)['tokens_used'] == 190


@pytest.mark.parametrize('failure', ['exception', 'no_usage'])
def test_uncertain_calls_keep_reservation(account, failure):
    store, uid = account
    class Engine:
        max_tokens = 1000
        def generate(self, prompt='', max_tokens=None):
            if failure == 'exception':
                raise TimeoutError('ambiguous transport failure')
            return {'text': 'missing usage'}
    engine = meter_engine(Engine(), store.tokens, uid)
    if failure == 'exception':
        with pytest.raises(TimeoutError):
            engine.generate('hi')
    else:
        engine.generate('hi')
    assert store.tokens.status(uid)['tokens_reserved'] == 2026
    assert Accounts(store.workspace).tokens.status(uid)['tokens_reserved'] == 2026


def test_oversized_prompt_is_rejected_before_call(account):
    store, uid = account
    class Engine:
        max_tokens = 1000
        def generate(self, prompt='', max_tokens=None):
            pytest.fail('Oversized prompt must not reach provider')
    with pytest.raises(TokenBudgetExceeded):
        meter_engine(Engine(), store.tokens, uid).generate('ت' * 6000)
    assert store.tokens.status(uid)['tokens_remaining'] == 10000


def test_connection_test_is_metered_to_authenticated_account(client, monkeypatch):
    from app import runner
    class Engine:
        max_tokens = 512
        def generate(self, prompt='', max_tokens=None):
            assert 0 < max_tokens <= 512
            return {'text': 'ok', 'usage_total': 23}
    monkeypatch.setattr(runner, 'init_llm', lambda cfg: Engine())
    before = client.get('/api/account').json()
    response = client.post('/api/settings/providers/openai/test', json={'model_name': 'test'})
    assert response.status_code == 200 and response.json()['ok'], response.text
    after = client.get('/api/account').json()
    assert after['tokens_used'] - before['tokens_used'] == 23
    assert before['tokens_remaining'] - after['tokens_remaining'] == 23


def test_cancel_after_model_call_still_records_usage(account):
    import threading
    from app.runner import guard_engine, RunStopped
    store, uid = account
    cancel = threading.Event()
    class Engine:
        max_tokens = 100
        def generate(self, prompt='', max_tokens=None):
            cancel.set()
            return {'text': 'ok', 'usage_total': 25}
    engine = guard_engine(meter_engine(Engine(), store.tokens, uid), cancel)
    with pytest.raises(RunStopped):
        engine.generate('hi')
    assert store.tokens.status(uid)['tokens_used'] == 25
