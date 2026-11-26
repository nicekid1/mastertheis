"""Durable, per-account token reservations; uncertain calls stay charged."""
import inspect
import os
import secrets

TOKEN_LIMIT = 100000


class TokenBudgetExceeded(ValueError):
    pass


class TokenBudget:
    def __init__(self, accounts):
        self.accounts = accounts
        # Temporary test switch: 0 bypasses accounting AND account quota checks.
        # Keep the implementation/history intact; set 1 and restart to restore.
        self.enabled = os.environ.get('GISCLAW_TOKEN_BUDGET_ENABLED', '1') != '0'
        with accounts.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS token_budgets (
                    user_id TEXT PRIMARY KEY, token_limit INTEGER NOT NULL DEFAULT 10000);
                CREATE TABLE IF NOT EXISTS token_requests (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    reserved INTEGER NOT NULL, actual INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE INDEX IF NOT EXISTS token_requests_user ON token_requests(user_id);
                CREATE TABLE IF NOT EXISTS token_reconciliations (
                    request_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    released INTEGER NOT NULL, reason TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            ''')

    def _status(self, db, uid):
        row = db.execute('SELECT token_limit FROM token_budgets WHERE user_id=?', (uid,)).fetchone()
        limit = row[0] if row else TOKEN_LIMIT
        row = db.execute('SELECT COALESCE(SUM(actual),0), COALESCE(SUM(CASE WHEN actual IS NULL THEN reserved ELSE 0 END),0) FROM token_requests WHERE user_id=?', (uid,)).fetchone()
        used, reserved = row
        return dict(token_limit=limit, tokens_used=used, tokens_reserved=reserved,
                    tokens_remaining=max(0, limit - used - reserved))

    def status(self, uid):
        if not self.enabled:
            # No totals are calculated in test mode; null is not "zero usage".
            return dict(token_budget_enabled=False, token_limit=None, tokens_used=None,
                        tokens_reserved=None, tokens_remaining=None)
        with self.accounts.db() as db:
            return dict(self._status(db, uid), token_budget_enabled=True)

    @staticmethod
    def unavailable_message(status):
        if status['tokens_reserved']:
            return (f"سهمیهٔ آزاد کافی نیست؛ مصرف ثبت‌شده: {status['tokens_used']}، "
                    f"رزرو یا مصرف تأییدنشده: {status['tokens_reserved']}، "
                    f"باقی‌مانده: {status['tokens_remaining']}. "
                    'اگر درخواستی در حال اجرا نیست، از مدیر بخواهید رزروها را بررسی کند.')
        return 'سهمیهٔ توکن حساب شما تمام شده است.'

    def require_available(self, uid):
        if not self.enabled:
            return
        status = self.status(uid)
        if status['tokens_remaining'] <= 0:
            raise TokenBudgetExceeded(self.unavailable_message(status))

    def reconcile_unbilled(self, uid, rid, reason):
        """Operator-only repair after investigation; never called by HTTP or expiry.

        Keep the original reservation and an audit record. Never rewrite reported
        usage or automatically release ambiguous provider/timeout failures.
        """
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('An investigation reason is required')
        with self.accounts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT reserved,actual FROM token_requests WHERE id=? AND user_id=?', (rid, uid)).fetchone()
            if row is None:
                raise ValueError('Reservation not found for this account')
            if db.execute('SELECT 1 FROM token_reconciliations WHERE request_id=?', (rid,)).fetchone():
                return False
            if row['actual'] is not None:
                raise ValueError('Cannot release settled usage')
            db.execute('INSERT INTO token_reconciliations(request_id,user_id,released,reason) VALUES(?,?,?,?)',
                       (rid, uid, row['reserved'], reason.strip()))
            db.execute('UPDATE token_requests SET actual=0 WHERE id=? AND user_id=? AND actual IS NULL', (rid, uid))
            return True

    def reserve(self, uid, input_bound, desired_output):
        if not self.enabled:
            return None, desired_output
        if type(input_bound) is not int or input_bound < 0 or type(desired_output) is not int or desired_output <= 0:
            raise ValueError('Invalid token reservation')
        with self.accounts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            user = db.execute('SELECT active FROM users WHERE id=?', (uid,)).fetchone()
            if not user or not user[0]:
                raise TokenBudgetExceeded('حساب کاربری فعال نیست.')
            status = self._status(db, uid)
            remaining = status['tokens_remaining']
            output = min(desired_output, remaining - input_bound)
            if output <= 0:
                if remaining <= 0 or status['tokens_reserved']:
                    raise TokenBudgetExceeded(self.unavailable_message(status))
                raise TokenBudgetExceeded('سهمیهٔ توکن برای این درخواست کافی نیست. متن و سابقهٔ گفتگو را کوتاه‌تر کنید یا با ادمین تماس بگیرید.')
            rid = secrets.token_hex(16)
            db.execute('INSERT INTO token_requests(id,user_id,reserved) VALUES(?,?,?)', (rid, uid, input_bound + output))
            return rid, output

    def settle(self, rid, actual):
        if not self.enabled:
            return
        # Missing usage, provider errors and interrupted calls are ambiguous:
        # never refund an unverified reservation automatically.
        if type(actual) is not int or actual <= 0:
            return
        with self.accounts.db() as db:
            db.execute('UPDATE token_requests SET actual=? WHERE id=? AND actual IS NULL', (actual, rid))


def meter_engine(engine, budget, uid):
    # Accounting wrapper temporarily bypassed for testing, not deleted.
    # Authentication, storage quotas and worker isolation remain enforced.
    if not budget.enabled:
        return engine
    inner = engine.generate
    # Prevent SDK retries from making multiple potentially billed requests per reservation.
    if getattr(engine, 'client', None) is not None and hasattr(engine.client, 'with_options'):
        engine.client = engine.client.with_options(max_retries=0)
    # Avoid the compatibility retry for unsupported sampling parameters as well.
    # Temperature is optional; metered OpenAI-compatible calls omit it entirely.
    if hasattr(engine, '_send_temperature'):
        engine._send_temperature = False

    def generate(*args, **kwargs):
        signature = inspect.signature(inner)
        # Validate the real engine contract before reserving quota. bind_partial
        # used to charge missing-required-argument calls that never reached a provider.
        bound = signature.bind(*args, **kwargs)
        values = dict(bound.arguments)
        extra = next((name for name, param in signature.parameters.items()
                      if param.kind == inspect.Parameter.VAR_KEYWORD), None)
        if extra:
            values.update(bound.arguments.get(extra, {}))
        if 'max_tokens' not in signature.parameters and not extra:
            raise TokenBudgetExceeded('این موتور امکان محدودکردن توکن خروجی را ندارد.')
        segments = values.get('user_segments')
        texts = [values.get('system_prompt') or '']
        texts += segments if segments else [values.get('user_message') or values.get('prompt') or '']
        if not all(isinstance(t, str) for t in texts):
            raise TokenBudgetExceeded('محاسبهٔ سهمیه فقط برای درخواست متنی پشتیبانی می‌شود.')
        # Conservative admission estimate, NOT a provider-independent exact tokenizer.
        # Includes framing reserve; actual reported input/cache/reasoning usage settles it.
        input_bound = sum(len(t.encode('utf-8')) for t in texts) + 1024
        desired = values.get('max_tokens') or getattr(engine, 'max_tokens', 2048)
        rid, cap = budget.reserve(uid, input_bound, desired)
        if 'max_tokens' in signature.parameters:
            bound.arguments['max_tokens'] = cap
        else:
            bound.arguments.setdefault(extra, {})['max_tokens'] = cap
        result = inner(*bound.args, **bound.kwargs)
        budget.settle(rid, result.get('usage_total'))
        return result

    engine.generate = generate
    return engine
