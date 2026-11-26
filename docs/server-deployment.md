# راهنمای استقرار آزمایشی امن شهرکاو

این راهنما برای میزبانی شهرکاو کنار یک اپ دیگر روی همان سرور است. Nginx سیستم
می‌تواند مشترک بماند، اما شهرکاو با دامنه، vhost، پورت loopback، کاربر Linux،
Docker rootless، داده، imageها و Compose project مجزای خودش اجرا می‌شود. فایل
`nginx-shahrkav.conf.example` فقط یک سایت جدا تعریف می‌کند؛ فایل Nginx اپ فعلی
را جایگزین یا ویرایش نکنید. Compose معمولی `docker-compose.yml` برای توسعه است.

## پیش‌نیازها

- Linux به‌روز با cgroup v2 و Docker rootless؛ برای شهرکاو یک کاربر Linux
  اختصاصی و غیر root بسازید و daemon آن را با اپ موجود مشترک نکنید.
- DNS دامنه به IP سرور اشاره کند. روی فایروال فقط SSH و TCP پورت‌های 80 و 443
  را باز کنید؛ پورت اختصاصی اپ (18765) نباید از اینترنت قابل دسترسی باشد.
- برای تحلیل GIS، daemon rootless باید محدودیت‌های cgroup v2، memory، PIDs و
  seccomp را پشتیبانی کند. محدودیت‌های منابع VPS را پیش از استفاده با دادهٔ واقعی
  بررسی کنید.

## آماده‌سازی

کاربر سیستمی `shahrkav` و مسیرهای جدا برای کد و داده بسازید. سورس را مثلاً در
`/opt/shahrkav/app` قرار دهید؛ داده‌ها در `/srv/shahrkav/data` می‌مانند و نباید
داخل پوشهٔ اپ فعلی یا سورس باشند:

```sh
sudo useradd --create-home --shell /bin/bash shahrkav
sudo install -d -o shahrkav -g shahrkav -m 750 /opt/shahrkav/app
sudo install -d -o shahrkav -g shahrkav -m 700 /srv/shahrkav/data
```

Docker rootless را برای همین کاربر نصب/راه‌اندازی کنید و daemon آن را با
`systemctl --user` یا روش توزیع خودکار بعد از reboot فعال نگه دارید. UID را با
`id -u shahrkav` بگیرید. به‌عنوان کاربر `shahrkav` یک context اختصاصی بسازید
که به socket همان daemon وصل است؛ برای مثال:

```sh
sudo -iu shahrkav
docker context create shahrkav --docker "host=unix:///run/user/$(id -u)/docker.sock"
```

بعد از اینکه نسخهٔ موردنظر روی GitHub قرار گرفت، سورس را داخل مسیر خالی
`/opt/shahrkav/app` بگیرید:

```sh
git clone --branch main --single-branch \
  https://github.com/nicekid1/mastertheis.git /opt/shahrkav/app
```

اگر push هنوز انجام نشده یا مخزن خصوصی است، کد را با روش امنی مثل `rsync` یا
کلید deploy به همان مسیر منتقل کنید؛ `.env`، کلیدها و پوشهٔ دادهٔ کامپیوتر خود
را انتقال ندهید. سپس به‌عنوان `shahrkav`:

```sh
cd /opt/shahrkav/app
cp .env.server.example .env
chmod 600 .env
```

در `.env` آدرس socket را با UID واقعی همین کاربر تنظیم کنید. همچنین دامنه و
subnet را در بخش‌های بعدی با مقادیر خودتان هماهنگ کنید. مقدار نمونهٔ
`GISCLAW_DATA` عمداً جدا از پروژه است.

قبل از راه‌اندازی، مطمئن شوید subnet تعریف‌شده در `.env` با شبکهٔ LAN، VPN یا
Docker daemon، project name، image tagها، پورت، subnet و پوشهٔ داده برای شهرکاو
جدا هستند. اگر subnet نمونه با شبکهٔ LAN، VPN یا Docker دیگری تداخل دارد،
subnet، gateway و IP اپ را با هم در یک بازهٔ خالی عوض کنید. Nginx gateway مورد اعتماد در
`FORWARDED_ALLOW_IPS` است؛ پورت 18765 فقط روی loopback منتشر می‌شود.

هیچ‌وقت socket مربوط به Docker سیستمی (`/var/run/docker.sock`) را جایگزین
نکنید. imageهای شهرکاو را در daemon اختصاصی خودش بسازید:

```sh
docker --context shahrkav build -f Dockerfile -t shahrkav:runtime-base .
docker --context shahrkav build --build-arg GISCLAW_BASE_IMAGE=shahrkav:runtime-base \
  -f Dockerfile.rootless -t shahrkav:isolated .
docker --context shahrkav compose -p shahrkav \
  -f docker-compose.rootless.yml -f docker-compose.server.yml config
docker --context shahrkav compose -p shahrkav \
  -f docker-compose.rootless.yml -f docker-compose.server.yml up -d
```

ساخت image به دسترسی registry و دریافت وابستگی‌ها نیاز دارد. اگر دریافت image
پایه یا dependency شکست خورد، علت registry/DNS/دسترسی سرور را رفع کنید؛ daemon
ناامن، اجرای privileged یا socket ریشه را جایگزین نکنید. این محیط فعلی دسترسی
به VPS شما ندارد و موفقیت build روی سرور هنوز تأیید نشده است.

## دامنه، Nginx و HTTPS

برای شهرکاو یک دامنه/subdomain جدا بسازید و A/AAAA را به IP همین سرور وصل کنید.
Nginx فعلی را حذف یا جایش را نگیرید. ابتدا یک موقتاً HTTP-only server block با
`server_name` دامنهٔ شهرکاو و مسیر challenge زیر فعال کنید تا گواهی گرفته شود:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name shahrkav.example.com;
    location ^~ /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 200 "Shahrkav TLS setup"; }
}
```

فایل را به‌عنوان یک سایت جدید فعال کنید (مثلاً `sites-available/shahrkav` و
symlink اختصاصی در `sites-enabled`)، سپس پیش از reload:

```sh
sudo nginx -t && sudo systemctl reload nginx
sudo install -d -m 755 /var/www/html/.well-known/acme-challenge
sudo certbot certonly --webroot -w /var/www/html -d shahrkav.example.com
```

حالا دامنه و مسیر گواهی را در `nginx-shahrkav.conf.example` جایگزین کنید و همان
فایل را به‌جای server block موقت بگذارید. این vhost به `127.0.0.1:18765` وصل
می‌شود، SSE را buffer نمی‌کند و مهلت پاسخ را برای تحلیل‌های طولانی تنظیم می‌کند.
قبل از reload هر بار `sudo nginx -t` اجرا کنید. certbot renewal را هم بررسی کنید.
دامنهٔ نمونه را واقعاً جایگزین کنید؛ Nginx تا وقتی فایل cert وجود نداشته باشد
با vhost نهایی start/reload نمی‌شود.

بعد از تأیید HTTPS، از این مسیر یک administrator بسازید:

```sh
docker --context shahrkav compose -p shahrkav \
  -f docker-compose.rootless.yml -f docker-compose.server.yml \
  exec gisclaw python -m app.auth create-admin --workspace /workspace
```

رمز یکتای قوی انتخاب کنید (حداقل 16 نویسه توصیه می‌شود). ثبت‌نام عمومی خاموش
است. کلید مدل را از Settings وارد کنید؛ کلیدها در پوشهٔ داده نگه‌داری می‌شوند
و نباید در Git، لاگ، تصویر Docker یا پیام‌ها قرار بگیرند.

## کنترل‌های فعال این پروفایل

- اپ فقط روی `127.0.0.1:18765` منتشر می‌شود؛ cookieها Secure/HttpOnly و SameSite
  هستند و هدرهای امنیتی را vhost شهرکاو در Nginx اضافه می‌کند.
- مسیر قدیمی اجرای کد داخل سرور خاموش است. GIS chat فقط با worker ایزولهٔ آماده
  فعال می‌شود؛ آماده نبودن worker دیگر به اجرای ناایمن داخل اپ منجر نمی‌شود.
- محدودیت حساب توکن در این پروفایل فعال و چت متنی جداگانه خاموش است. سهمیهٔ فایل
  همان مقدار حساب (پیش‌فرض 50 MiB) می‌ماند؛ محدودیت ورودی/زمان worker نیز برای
  محافظت از منابع اجرا باقی است.
- فایل‌سیستم ریشهٔ coordinator فقط‌خواندنی، capabilities حذف‌شده، no-new-privileges
  و محدودیت حافظه/فرایند دارد. دادهٔ کاربر در mount جداگانه است. worker تحلیل
  شبکه، کلیدها، socket و mount میزبان ندارد.

## بررسی پس از راه‌اندازی

1. `docker --context shahrkav compose -p shahrkav ... ps` را بررسی کنید؛ لاگ اپ نباید شامل
   کلید یا رمز باشد.
2. از یک دستگاه بیرونی HTTPS را باز کنید. مطمئن شوید `http://domain` به HTTPS
   می‌رود و `http://server-ip:18765` از بیرون باز نیست. vhost اپ قبلی هم باید
   بدون تغییر در دسترس بماند.
3. ورود مدیر، ساخت کاربر آزمایشی، رد ورود ناشناس، رد ثبت‌نام، سهمیهٔ فایل و
   جداسازی پروژه‌های دو کاربر را بررسی کنید.
4. worker را در محیط سالم بررسی کنید: در حساب کاربر گزینهٔ تحلیل باید آماده باشد؛
   یک تحلیل کوچک روی دادهٔ غیرحساس انجام دهید و مالکیت خروجی را تأیید کنید.
   اگر worker آماده نیست، تحلیل باید غیرفعال/با خطای واضح باشد و هرگز از مسیر
   قدیمی استفاده نکند.
5. از کل `/srv/shahrkav/data` نسخهٔ پشتیبان رمزگذاری‌شده و خارج از سرور بگیرید؛
   بازیابی آن را هم آزمایش کنید. پوشه شامل پروژه‌ها، حساب‌ها، تنظیمات و کلیدهاست.

اگر loginها روی همهٔ کاربران یک محدودیت IP مشترک نشان دادند، ابتدا آدرس peer
واقعی‌ای را که worker/rootless port-forward به اپ می‌رساند بررسی کنید و فقط
همان آدرس را در `GISCLAW_TRUSTED_PROXY_IP`/`FORWARDED_ALLOW_IPS` اعتماد کنید؛
آن را روی `*` نگذارید. این جزئیات با backend شبکهٔ rootless و میزبان فرق می‌کند.

## نگه‌داری و محدودیت مسئولیت

پیش از به‌روزرسانی از داده پشتیبان بگیرید و پوشهٔ داده را حذف یا جایگزین نکنید.
همهٔ workerها و API را با یک نسخهٔ سازگار بالا بیاورید؛ چند API worker یا اجرای
هم‌زمان نسخهٔ rootful و rootless روی یک پوشهٔ داده پشتیبانی نمی‌شود. ورود مدیر،
کلیدهای مدل و داده‌های آپلودی همچنان دارایی حساس‌اند.

این پروفایل سخت‌سازی پایه برای آزمایش محدود است، نه ممیزی امنیتی یا تضمین
مناسب‌بودن برای دادهٔ حساس/کاربران ناشناس. rootless container مرز امنیتی معادل
ماشین مجازی نیست. سیستم‌عامل، kernel، Docker، Nginx، DNS، firewall، پشتیبان‌گیری
و دسترسی مدیریتی سرور باید جداگانه نگه‌داری شوند.
