"""Authentication, tenant routing and account administration for the HTTP app."""
import asyncio
import json
import os
from fastapi import Request
from fastapi.responses import JSONResponse, FileResponse
from app import paths
from app.auth import COOKIE, verify


def install(app, accounts):
    locks = {}

    def fail(message, status=403, **details):
        return JSONResponse({'error': message, **details}, status_code=status)

    @app.middleware('http')
    async def protect(request: Request, call_next):
        route = request.url.path
        # Self-registration is intentionally disabled. Only the administrator
        # route /api/admin/users can create accounts; there is no public form.
        if route.rstrip('/') in ('/api/auth/register', '/api/auth/signup'):
            return fail('ثبت‌نام عمومی غیرفعال است؛ ایجاد حساب فقط توسط ادمین انجام می‌شود.')
        if not route.startswith('/api/'):
            return await call_next(request)
        # Also cover middleware-generated responses, not just route handlers.
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            from urllib.parse import urlsplit
            origin = request.headers.get('origin')
            if request.headers.get('x-gisclaw') != '1' or (origin and urlsplit(origin).netloc.lower() != request.headers.get('host', '').lower()):
                return fail('درخواست از مبدأ نامعتبر است.')
        if route == '/api/auth/login':
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 4096:
                    return fail('درخواست بیش از حد بزرگ است.', 413)
                request._body = getattr(request, '_body', b'') + chunk
            return await call_next(request)
        user = await asyncio.to_thread(accounts.session, request.cookies.get(COOKIE))
        if not user:
            return fail('برای ادامه وارد حساب کاربری شوید.', 401)
        request.state.user = user
        admin = user['role'] == 'admin'
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and not route.endswith('/upload'):
            payload = bytearray()
            async for chunk in request.stream():
                if len(payload) + len(chunk) > 65536:
                    return fail('درخواست بیش از حد بزرگ است.', 413)
                payload.extend(chunk)
            request._body = bytes(payload)
        if not admin:
            if route.startswith(('/api/admin', '/api/skills', '/api/memory', '/api/browse')):
                return fail('این بخش فقط در اختیار مدیر سامانه است.')
            if route.startswith('/api/settings') and route not in ('/api/settings', '/api/settings/ui', '/api/settings/viewer_follow'):
                return fail('تنظیمات سامانه فقط در اختیار مدیر است.')
            if route.startswith('/api/run'):
                if route == '/api/run/active' and request.method == 'GET':
                    return JSONResponse({'active': None})
                return fail('اجرای تحلیل کاربران تا راه‌اندازی محیط اجرای ایزوله غیرفعال است.')
            if route.endswith(('/geoprocess', '/attach')):
                return fail('این عملیات تا راه‌اندازی محیط اجرای ایزوله برای کاربران فعال نیست.')
        token = paths.tenant_root.set(accounts.root(user))
        try:
            # Serialize mutations per tenant. One ASGI worker is required (as with the existing sandbox).
            if not admin and request.method not in ('GET', 'HEAD', 'OPTIONS') and route.startswith(('/api/projects', '/api/archived')):
                lock = locks.setdefault(user['id'], asyncio.Lock())
                async with lock:
                    # Reload after taking the same lock used for admin quota edits.
                    user = accounts.get(user['id'])
                    if request.method != 'DELETE':
                        try:
                            used = await asyncio.to_thread(accounts.usage, user)
                        except OSError:
                            return fail('محاسبهٔ فضای مصرفی ممکن نیست؛ برای جلوگیری از عبور از سهمیه، بارگذاری متوقف شد. با مدیر تماس بگیرید.', 503, code='storage_unavailable')
                        remaining = user['quota'] - used - 65536
                        quota_details = dict(code='storage_quota_exceeded', quota_bytes=user['quota'],
                                             used_bytes=used, available_bytes=max(0, remaining), reserved_bytes=65536)
                        # A larger account quota must not allow unbounded request buffering.
                        limit = max(0, min(remaining, 50 * 1024 * 1024)) if route.endswith('/upload') else max(0, min(remaining, 16384))
                        upload = route.endswith('/upload')
                        length = request.headers.get('content-length', '')
                        if upload and length.isdigit() and int(length) > 50 * 1024 * 1024:
                            return fail('حجم هر فایل نباید بیش از ۵۰ مگابایت باشد.', 413, code='upload_too_large')
                        quota_message = (f"فضای اختصاصی کافی نیست. سهمیه: {user['quota'] / 1048576:.2f} MiB، "
                                         f"مصرف‌شده: {used / 1048576:.2f} MiB، قابل بارگذاری: {max(0, remaining) / 1048576:.2f} MiB "
                                         '(۶۴ KiB برای اطلاعات پروژه محفوظ است). فایل حذف کنید یا از ادمین افزایش فضا بخواهید.')
                        quota_limited = remaining <= (50 * 1024 * 1024 if upload else 16384)
                        message = (quota_message
                                   if remaining <= (50 * 1024 * 1024 if upload else 16384)
                                   else ('حجم هر فایل نباید بیش از ۵۰ مگابایت باشد.' if upload else 'درخواست بیش از حد بزرگ است.'))
                        if length.isdigit() and int(length) > limit:
                            return fail(message, 413, **(quota_details if quota_limited else {'code': 'upload_too_large'}))
                        if remaining <= 0:
                            return fail(quota_message, 413, **quota_details)
                        data = bytearray()
                        async for chunk in request.stream():
                            if len(data) + len(chunk) > limit:
                                return fail(message, 413, **(quota_details if quota_limited else {'code': 'upload_too_large'}))
                            data.extend(chunk)
                        request._body = bytes(data)
                    return await call_next(request)
            return await call_next(request)
        finally:
            paths.tenant_root.reset(token)

    @app.post('/api/auth/login')
    async def login(request: Request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError('درخواست نامعتبر است.')
            token, user = await asyncio.to_thread(accounts.login, body.get('username'), body.get('password'), request.client.host if request.client else 'unknown')
        except (ValueError, TypeError):
            return fail('ورود ناموفق بود؛ اطلاعات ورود را بررسی کنید. پس از تلاش‌های مکرر ۱۵ دقیقه صبر کنید.', 401)
        response = JSONResponse(accounts.public(user))
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=request.url.scheme == 'https' or os.environ.get('GISCLAW_SECURE_COOKIES') == '1', max_age=12 * 3600, path='/')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/api/auth/logout')
    async def logout(request: Request):
        accounts.logout(request.cookies.get(COOKIE, ''))
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE, path='/')
        return response

    @app.get('/api/auth/me')
    async def me(request: Request):
        return accounts.public(request.state.user)

    @app.post('/api/auth/password')
    async def change_password(request: Request):
        body = await request.json()
        if not verify(body.get('current_password'), request.state.user['password']):
            return fail('رمز فعلی نادرست است.', 400)
        try:
            accounts.update(request.state.user['id'], password=body.get('new_password', ''))
        except ValueError as exc:
            return fail(str(exc), 400)
        return {'ok': True, 'login_required': True}

    @app.get('/api/account')
    async def account(request: Request):
        return accounts.public(request.state.user)

    @app.get('/api/admin/users')
    async def users():
        return [accounts.public(u) for u in accounts.users()]

    @app.post('/api/admin/users')
    async def create_user(request: Request):
        body = await request.json()
        try:
            return accounts.public(accounts.create(body.get('username'), body.get('password'), body.get('role', 'user')))
        except ValueError as exc:
            return fail(str(exc), 400)

    @app.patch('/api/admin/users/{uid}')
    async def update_user(uid: str, request: Request):
        body = await request.json()
        if body.get('active') is not None and not isinstance(body['active'], bool):
            return fail('وضعیت کاربر نامعتبر است.', 400)
        if uid == request.state.user['id'] and body.get('active') is False:
            return fail('حساب جاری را نمی‌توانید غیرفعال کنید.', 400)
        try:
            async with locks.setdefault(uid, asyncio.Lock()):
                return accounts.public(accounts.update(uid, password=body.get('password'), active=body.get('active'), quota=body.get('quota')))
        except ValueError as exc:
            return fail(str(exc), 400)

    def file_path(uid, relative):
        user = accounts.get(uid)
        if not user or not relative or any(p.startswith('.') for p in relative.replace('\\', '/').split('/')):
            raise ValueError('مسیر فایل نامعتبر است.')
        return paths.safe_join(accounts.root(user), relative)

    @app.get('/api/admin/users/{uid}/files')
    async def files(uid: str):
        user = accounts.get(uid)
        if not user:
            return fail('کاربر یافت نشد.', 404)
        root = accounts.root(user)
        result = []
        for p in paths.dir_tree(root):
            try:
                full = paths.safe_join(root, p)
                if os.path.isfile(full):
                    result.append({'path': p, 'bytes': os.path.getsize(full)})
            except (ValueError, FileNotFoundError):
                continue
        return result

    @app.get('/api/admin/users/{uid}/file')
    async def download(uid: str, path: str):
        try:
            target = file_path(uid, path)
            if not os.path.isfile(target):
                raise ValueError('فایل یافت نشد.')
            return FileResponse(target, filename=os.path.basename(target), media_type='application/octet-stream')
        except ValueError as exc:
            return fail(str(exc), 404)

    @app.delete('/api/admin/users/{uid}/file')
    async def delete_file(uid: str, path: str):
        try:
            target = file_path(uid, path)
            os.remove(target)
            return {'ok': True}
        except (ValueError, OSError):
            return fail('فایل حذف نشد؛ مسیر یا وضعیت فایل را بررسی کنید.', 400)
