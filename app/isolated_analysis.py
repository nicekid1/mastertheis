"""Trusted coordinator for disposable rootless Docker GIS jobs.

Run the API natively under an unprivileged account with a dedicated rootless
daemon. Never mount a privileged Docker socket into the application container.
Only JSON crosses this boundary; never unpickle worker output.
"""
import asyncio
import base64
import json
import logging
import os
from pathlib import Path, PurePosixPath
import secrets
import subprocess
import tempfile
import threading
import time
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
from app import paths

MAX_BYTES = 50 * 1024 * 1024
JOB_SLOT = threading.BoundedSemaphore(1)
_readiness = (0.0, False)
log = logging.getLogger(__name__)


class AnalysisError(ValueError):
    def __init__(self, message, status=400, code='invalid_analysis'):
        super().__init__(message)
        self.status, self.code = status, code


def available():
    global _readiness
    if os.environ.get('GISCLAW_ISOLATED_ANALYSIS') != '1':
        return False
    now = time.monotonic()
    if now - _readiness[0] < 5:
        return _readiness[1]
    try:
        result = subprocess.run(['docker', 'info', '--format', '{{json .}}'],
                                capture_output=True, text=True, timeout=5, check=True)
        info = json.loads(result.stdout)
        ready = ('name=rootless' in info.get('SecurityOptions', [])
                and 'name=seccomp,profile=builtin' in info.get('SecurityOptions', [])
                and info.get('CgroupVersion') == '2'
                and info.get('MemoryLimit') is True and info.get('PidsLimit') is True)
    except (OSError, ValueError, subprocess.SubprocessError):
        ready = False
    _readiness = (now, ready)
    return ready


def relative_name(value):
    if not isinstance(value, str) or not value or '\x00' in value:
        raise AnalysisError('مسیر فایل نامعتبر است.')
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or '..' in path.parts or '\\' in value or any(p.startswith('.') for p in path.parts):
        raise AnalysisError('مسیر فایل نامعتبر است.')
    return str(path)


def snapshot_inputs(pdir, selection):
    """Copy source data and explicitly selected output layers, not output history.

    Shapefile companions must travel together. The byte cap still protects the
    worker's bounded temporary filesystem; it is separate from account quotas.
    """
    pdir = Path(pdir)
    candidates = {}

    def validate(path):
        name = relative_name(path.relative_to(pdir).as_posix())
        # Reject links in any component, even links pointing inside the project.
        current = path
        while current != pdir:
            if current.is_symlink():
                raise AnalysisError('لینک فایل یا پوشه در ورودی تحلیل پذیرفته نمی‌شود.')
            current = current.parent
        paths.safe_join(str(pdir), name)
        return name

    data = pdir / 'data'
    validate(data)
    validate(pdir / 'outputs')  # also protect the eventual output commit target
    for path in sorted(data.rglob('*')):
        name = validate(path)
        if path.is_file():
            candidates[name] = path

    for group in selection:
        if group['where'] != 'outputs':
            continue
        source = pdir / 'outputs' / relative_name(group['path'])
        validate(source)
        for member in paths.companion_files(str(source)):
            path = Path(member)
            candidates[validate(path)] = path

    def check_size(total):
        if total > MAX_BYTES:
            raise AnalysisError(
                f'حجم داده‌های ورودی و خروجی‌های انتخاب‌شده برای این تحلیل {total / 1048576:.2f} MiB است؛ '
                f'سقف محیط تحلیل {MAX_BYTES / 1048576:g} MiB است. '
                'از پروژه‌ای با داده‌های کمتر استفاده کنید یا انتخاب خروجی‌های حجیم را پاک کنید. '
                'این محدودیت مربوط به توکن نیست و خروجی‌های انتخاب‌نشده محاسبه نمی‌شوند.',
                413, 'analysis_input_too_large')

    # Preflight before reading/encoding any file. Recheck actual bytes to bound
    # allocation if a file grows between the metadata scan and the read.
    check_size(sum(path.stat().st_size for path in candidates.values()))
    files, total = {}, 0
    for name, path in candidates.items():
        validate(path)
        with path.open('rb') as stream:
            content = stream.read(MAX_BYTES - total + 1)
        total += len(content)
        check_size(total)
        files[name] = base64.b64encode(content).decode()
    return files


def command(name):
    return ['docker', 'run', '--rm', '-i', '--name', name, '--network', 'none',
            '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--user', '65534:65534', '--memory', '1g', '--memory-swap', '1g',
            '--cpus', '1', '--pids-limit', '64', '--ulimit', 'nofile=256:256',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m,mode=1777',
            '-e', 'MPLCONFIGDIR=/tmp/mpl', '-e', 'HOME=/tmp',
            '--entrypoint', 'python', os.environ.get('GISCLAW_WORKER_IMAGE', 'gisclaw:latest'),
            '-m', 'app.isolated_worker']


def execute(job, llm, *, timeout=300):
    steps, calls = [], 0
    name = 'gisclaw-job-' + secrets.token_hex(12)
    proc = subprocess.Popen(command(name), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    expired = threading.Event()
    cleanup_done = threading.Event()
    cleanup_lock = threading.Lock()
    def stop():
        # Deadline and request cleanup can run concurrently. Do not return or
        # release the job slot until the thread removing the container finishes.
        with cleanup_lock:
            if cleanup_done.is_set():
                return
            expired.set()
            proc.kill()
            try:
                subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
            cleanup_done.set()
    timer = threading.Timer(timeout, stop)
    timer.start()
    try:
        proc.stdin.write(json.dumps(job).encode() + b'\n')
        proc.stdin.flush()
        for _ in range(64):
            line = proc.stdout.readline(80 * 1024 * 1024)
            if not line or not line.endswith(b'\n'):
                if expired.is_set():
                    raise AnalysisError('زمان مجاز تحلیل پایان یافت؛ محدودهٔ تحلیل را کوچک‌تر کنید.', 504, 'analysis_timeout')
                raise AnalysisError('محیط اجرای تحلیل پیش از ارسال نتیجه قطع شد؛ این خطا به‌تنهایی به معنی کمبود حافظه یا سهمیه نیست.', 502, 'worker_exited')
            try:
                message = json.loads(line)
            except (ValueError, UnicodeError):
                raise AnalysisError('پیام محیط اجرای تحلیل قابل خواندن نیست؛ ارتباط داخلی worker باید بررسی شود.', 502, 'worker_invalid_json') from None
            if not isinstance(message, dict):
                raise AnalysisError('ساختار پیام محیط اجرای تحلیل نامعتبر است.', 502, 'worker_invalid_message')
            if message.get('type') == 'step':
                if len(steps) >= 24 or any(not isinstance(message.get(k, ''), str) for k in ('action', 'code', 'observation')):
                    raise AnalysisError('گزارش مراحل worker نامعتبر است.', 502, 'worker_invalid_message')
                steps.append({k: message.get(k, '')[:limit] for k, limit in [('action', 100), ('code', 16000), ('observation', 4000)]})
                steps[-1]['success'] = message.get('success') is not False
                continue
            if message.get('type') == 'error':
                # Workers are untrusted: never echo their exception text.
                errors = {
                    'output_limit': ('حجم فایل‌های تولیدشده از فضای مجاز خروجی بیشتر است؛ خروجی کوچک‌تری درخواست کنید.', 413),
                    'output_link': ('خروجی تحلیل شامل لینک فایل است و برای ایمنی ذخیره نشد.', 422),
                    'temporary_storage_full': ('فضای موقت محیط تحلیل پر شده است؛ حجم داده‌های میانی را کاهش دهید.', 507),
                    'worker_memory': ('محیط تحلیل نتوانست حافظهٔ لازم را تخصیص دهد؛ تحلیل را روی دادهٔ کوچک‌تری اجرا کنید.', 503),
                }
                code = message.get('code')
                if not isinstance(code, str) or code not in errors:
                    code = 'worker_execution_failed'
                detail, status = errors.get(code, ('اجرای داخلی worker با خطا متوقف شد؛ این خطا مربوط به پاسخ HTTP مدل نیست.', 502))
                raise AnalysisError(detail, status, code)
            if message.get('type') == 'done':
                message['steps'] = steps
                message['code'] = message.get('code', '')[:100000] if isinstance(message.get('code', ''), str) else ''
                return message
            if message.get('type') != 'llm':
                raise AnalysisError('نوع پیام محیط اجرای تحلیل ناشناخته است.', 502, 'worker_invalid_message')
            system, question = message.get('system_prompt'), message.get('user_message')
            if not isinstance(system, str) or not isinstance(question, str):
                raise AnalysisError('ساختار پیام worker برای مدل نامعتبر است؛ متن دستور و گفتگو باید رشته باشد.', 502, 'analysis_context_invalid')
            # Temporary test policy: no application-level character quota.
            # Previously rejected len(system) + len(question) > 32000 here.
            # Keep type validation, bounded RPC frames and worker isolation;
            # the provider still enforces its own model context window.
            if calls >= 16:
                raise AnalysisError('تحلیل به سقف مراحل ارتباط با مدل رسید.', 422, 'analysis_round_limit')
            calls += 1
            started = time.monotonic()
            try:
                response = llm.generate(prompt='', system_prompt=system, user_message=question, max_tokens=2048)
            finally:
                # Size and timing only: no instructions, file contents or keys.
                log.warning('Model RPC call=%d system_chars=%d user_chars=%d elapsed_ms=%d', calls, len(system), len(question), (time.monotonic() - started) * 1000)
            if expired.is_set():
                raise AnalysisError('زمان مجاز تحلیل پایان یافت؛ محدودهٔ تحلیل را کوچک‌تر کنید.', 504, 'analysis_timeout')
            proc.stdin.write(json.dumps({'text': response.get('text', '')}).encode() + b'\n')
            proc.stdin.flush()
        raise AnalysisError('تحلیل به سقف مراحل ارتباط با مدل رسید؛ درخواست را به مراحل کوچک‌تر تقسیم کنید.', 422, 'analysis_round_limit')
    except Exception as exc:
        exc.analysis_steps = steps
        raise
    finally:
        timer.cancel()
        stop()
        proc.wait(timeout=10)
        proc.stdin.close()
        proc.stdout.close()


def install(app, accounts, store, runner):
    @app.post('/api/projects/{pid}/analysis')
    async def analyze(pid: str, request: Request):
        if not available():
            return JSONResponse({'error': 'محیط اجرای rootless هنوز پیکربندی نشده است. راهنمای docs/isolated-analysis.md را بررسی کنید.'}, status_code=503)
        user = accounts.get(request.state.user['id'])
        pdir = Path(paths.project_dir(pid))
        if not (pdir / 'project.json').is_file():
            return JSONResponse({'error': 'پروژه یافت نشد.'}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({'error': 'درخواست تحلیل باید JSON معتبر باشد.'}, status_code=400)
        if not isinstance(body, dict) or not isinstance(body.get('instruction'), str) or not body['instruction'].strip() or len(body['instruction']) > 4000:
            return JSONResponse({'error': 'متن درخواست تحلیل نامعتبر است.'}, status_code=400)
        ready = [m['id'] for m in store.models_public() if m['enabled'] and m['ready']]
        if body.get('model') not in ready:
            return JSONResponse({'error': 'مدل آماده‌ای انتخاب نشده است.'}, status_code=400)

        def work():
            from app.feature_selection import source_version
            selection = body.get('selection', [])
            if not isinstance(selection, list) or len(selection) > 20:
                raise AnalysisError('انتخاب عوارض نامعتبر است.')
            sources = []
            selected_count = 0
            for group in selection:
                if not isinstance(group, dict) or group.get('where') not in ('data', 'outputs'):
                    raise AnalysisError('برای تحلیل ایزوله، عوارض را از داده‌ها یا خروجی‌های پروژه انتخاب کنید.')
                ids = group.get('ids')
                if not isinstance(ids, list) or not ids or len(ids) > 5000 or any(type(i) is not int or i < 0 for i in ids):
                    raise AnalysisError('شناسهٔ عوارض انتخابی نامعتبر است؛ حداکثر ۵۰۰۰ عارضه انتخاب کنید.')
                selected_count += len(set(ids))
                if selected_count > 5000:
                    raise AnalysisError('در مجموع حداکثر ۵۰۰۰ عارضه برای هر تحلیل انتخاب کنید.')
                source = paths.safe_join(str(pdir / group['where']), relative_name(group.get('path', '')))
                if source_version(source) != group.get('version'):
                    raise AnalysisError('لایه تغییر کرده است؛ آن را دوباره بارگذاری و انتخاب کنید.', 409, 'selection_changed')
                sources.append((source, group['version']))
            files = snapshot_inputs(pdir, selection)
            if any(source_version(source) != version for source, version in sources):
                raise AnalysisError('لایه هنگام تهیهٔ نسخهٔ تحلیل تغییر کرد.', 409, 'selection_changed')
            remaining = min(MAX_BYTES, user['quota'] - accounts.usage(user) - 65536) if user['role'] != 'admin' else MAX_BYTES
            if remaining <= 0:
                raise AnalysisError('فضای کافی برای ذخیرهٔ خروجی تحلیل وجود ندارد.', 413, 'storage_quota_exceeded')
            accounts.tokens.require_available(user['id'])
            llm = runner.guard_engine(runner.meter_engine(runner.init_llm(store.model_config(body['model'])), user['id']))
            result = execute({'files': files, 'instruction': body['instruction'],
                              'selection': selection, 'output_limit': remaining}, llm)
            outputs = result.get('outputs')
            if not isinstance(outputs, dict) or len(outputs) > 256:
                raise AnalysisError('فهرست خروجی worker نامعتبر است یا بیش از ۲۵۶ فایل دارد؛ هیچ خروجی ذخیره نشد.', 502, 'worker_invalid_outputs')
            # Validate every artifact before committing any file. Untrusted paths
            # are never used for host extraction; data is decoded as regular files.
            decoded = {}
            total = 0
            for name, content in outputs.items():
                name = relative_name(name)
                try:
                    if not isinstance(content, str):
                        raise ValueError('Expected encoded text')
                    data = base64.b64decode(content, validate=True)
                except (ValueError, TypeError):
                    raise AnalysisError('محتوای فایل خروجی هنگام انتقال از worker نامعتبر است؛ هیچ خروجی ذخیره نشد.', 502, 'worker_invalid_file') from None
                total += len(data)
                if total > remaining:
                    raise AnalysisError('حجم خروجی از فضای باقی‌مانده بیشتر است.', 413, 'storage_quota_exceeded')
                if name in decoded:
                    raise AnalysisError('نام فایل خروجی تکراری است.')
                decoded[name] = data
            job_id = 'analysis-' + secrets.token_hex(8)
            (pdir / 'outputs').mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.analysis-', dir=pdir) as staging:
                for name, data in decoded.items():
                    target = Path(staging) / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                if user['role'] != 'admin' and accounts.usage(user) + 65536 > accounts.get(user['id'])['quota']:
                    raise AnalysisError('فضای باقی‌مانده برای ثبت خروجی کافی نیست.', 413, 'storage_quota_exceeded')
                if decoded:
                    os.rename(staging, pdir / 'outputs' / job_id)
            return {'answer': str(result.get('answer', ''))[:20000], 'success': bool(result.get('success')),
                    'outputs': [job_id + '/' + name for name in decoded], 'usage': accounts.tokens.status(user['id']),
                    'code': result.get('code', ''), 'steps': result.get('steps', [])}
        # Middleware holds the per-user mutation/quota lock for the entire job.
        def serialized_work():
            if not JOB_SLOT.acquire(blocking=False):
                raise AnalysisError('محیط تحلیل مشغول است؛ پس از پایان اجرای جاری دوباره تلاش کنید.', 409, 'analysis_busy')
            try:
                return work()
            finally:
                JOB_SLOT.release()
        task = asyncio.create_task(asyncio.to_thread(serialized_work))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Keep the quota lock until output commit completes after disconnect.
            try:
                await task
            finally:
                raise
        except AnalysisError as exc:
            reference = secrets.token_hex(6)
            log.warning('Isolated analysis rejected ref=%s code=%s status=%s', reference, exc.code, exc.status)
            return JSONResponse({'error': str(exc) + f' شناسهٔ پیگیری: {reference}', 'code': exc.code, 'error_id': reference, 'steps': getattr(exc, 'analysis_steps', [])}, status_code=exc.status)
        except ValueError as exc:
            from app.token_budget import TokenBudgetExceeded
            if isinstance(exc, TokenBudgetExceeded):
                return JSONResponse({'error': str(exc), 'code': 'token_quota_exceeded'}, status_code=429)
            reference = secrets.token_hex(6)
            frames = ' > '.join(f'{Path(f.filename).name}:{f.lineno}:{f.name}'
                                for f in traceback.extract_tb(exc.__traceback__)[-8:])
            log.error('Isolated analysis invalid data ref=%s type=%s frames=%s', reference, type(exc).__name__, frames)
            return JSONResponse({'error': 'پردازش داده در سرور با خطای اعتبارسنجی متوقف شد؛ علت در لاگ سرور ثبت شد.' + f' شناسهٔ پیگیری: {reference}', 'code': 'analysis_invalid_data', 'error_id': reference}, status_code=400)
        except Exception as exc:
            reference = secrets.token_hex(6)
            # No provider payload, prompt, API key or exception message in logs.
            # Stack locations and type are enough to diagnose programmer errors.
            frames = ' > '.join(f'{Path(f.filename).name}:{f.lineno}:{f.name}'
                                for f in traceback.extract_tb(exc.__traceback__)[-8:])
            log.error('Isolated analysis failure ref=%s type=%s frames=%s', reference, type(exc).__name__, frames)
            if isinstance(exc, runner.ModelTimeout):
                message, status, code = str(exc), 504, 'model_timeout'
            elif isinstance(exc, runner.ApiCallFailed):
                message, status, code = 'فراخوانی مدل ناموفق بود؛ مدیر باید اتصال و پاسخ ارائه‌دهندهٔ مدل را بررسی کند.', 502, 'model_call_failed'
                provider_http = exc.provider_status
                log.error('Provider failure ref=%s http_status=%s', reference, provider_http)
                explanations = {400: 'ارائه‌دهنده درخواست مدل را نپذیرفت؛ سازگاری پارامترها یا اندازهٔ متن باید بررسی شود.',
                                401: 'ارائه‌دهنده کلید API را نپذیرفت؛ مدیر باید کلید را بررسی کند.',
                                402: 'ارائه‌دهنده پرداخت یا اعتبار حساب API را نپذیرفت؛ این موضوع سهمیهٔ توکن داخل برنامه نیست.',
                                403: 'ارائه‌دهنده دسترسی این حساب به مدل را رد کرد.',
                                404: 'ارائه‌دهنده مدل یا مسیر API درخواستی را پیدا نکرد.',
                                429: 'ارائه‌دهنده درخواست را به‌دلیل محدودیت یا سهمیهٔ خودش رد کرد؛ محدودیت داخلی توکن برنامه خاموش‌کردنی است ولی این خطا مربوط به سرویس بیرونی است.'}
                if provider_http:
                    message = explanations.get(provider_http, 'سرویس ارائه‌دهندهٔ مدل با خطا پاسخ داد؛ افزایش زمان انتظار این پاسخ خطا را برطرف نمی‌کند.') + f' HTTP {provider_http}.'
            elif isinstance(exc, BrokenPipeError):
                message, status, code = 'ارتباط با محیط اجرای تحلیل قطع شد؛ وضعیت worker و محدودیت منابع را بررسی کنید.', 502, 'worker_disconnected'
            elif isinstance(exc, PermissionError):
                message, status, code = 'سرور اجازهٔ خواندن ورودی یا ذخیرهٔ خروجی را ندارد؛ مدیر باید مجوز پوشه‌های پروژه را بررسی کند.', 500, 'storage_permission_denied'
            elif isinstance(exc, FileNotFoundError):
                message, status, code = 'یکی از فایل‌های ورودی یا اجزای محیط اجرا یافت نشد؛ پروژه را تازه‌سازی کنید و در صورت تکرار با مدیر تماس بگیرید.', 500, 'analysis_resource_missing'
            else:
                message, status, code = 'خطای داخلی در اجرای تحلیل رخ داد؛ این پیام به‌معنی اتمام سهمیه نیست. شناسهٔ پیگیری را به مدیر بدهید.', 500, 'analysis_internal_error'
            return JSONResponse({'error': message + f' شناسهٔ پیگیری: {reference}', 'code': code, 'error_id': reference,
                                 'provider_status': getattr(exc, 'provider_status', None), 'steps': getattr(exc, 'analysis_steps', [])}, status_code=status)
