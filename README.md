## المتطلب 1 — حماية البيانات المشتركة من التضارب (Concurrent Access & Data Integrity)

**ما تم تنفيذه.** دالة الـ checkout في [`apps/orders/services.py`](apps/orders/services.py) تغلّف قسم تخفيض المخزون داخل `@transaction.atomic` وتحصل على قفل صف (row lock) في Postgres عبر `Product.objects.select_for_update()`. يتم ترتيب العناصر بحسب product id قبل أخذ القفل بحيث يكون ترتيب الأقفال (global lock order) ثابتاً عبر جميع المعاملات — وبذلك يصبح نمط الانسداد المتبادل AB / BA مستحيلاً.

**طريقة الاختبار.**

```powershell
docker compose exec -T -e BASE_URL=http://nginx web1 python scripts/race_condition_demo.py
```

السكربت يُطلق 100 عملية شراء متزامنة (وحدة واحدة لكل طلب) على منتج رصيده 50 وحدة، مرتين — مرة على المسار الذي يحوي تضارباً متعمداً (`unsafe=true`) ومرة على المسار المحمي بالقفل. الجولة الأولى تبيع أكثر من الرصيد المتاح (تُثبت وجود الـ Race Condition)؛ الجولة الثانية تبيع 50 بالضبط وترفض 50 طلباً بـ HTTP 409 وتطبع `consistent = True`.

---

## المتطلب 2 — إدارة الموارد الحاسوبية (Resource Management & Capacity Control)

**ما تم تنفيذه.** ثلاث طبقات مستقلة تحدّ من التزامن: `BoundedSemaphore` في [`apps/core/middleware.py::CapacityControlMiddleware`](apps/core/middleware.py) يضبط الطلبات الثقيلة بحد أعلى `MAX_CONCURRENT_HEAVY_REQUESTS` لكل بروسس (افتراضياً 8)؛ Gunicorn مع `--workers 3 --threads 4 --max-requests 1000`؛ وعمّال Celery مع `--concurrency=4 --max-tasks-per-child=500`. عند تجاوز الحد، الـ middleware يُرجع HTTP 503 فوراً بدلاً من إبقاء الطلب في الطابور إلى ما لا نهاية.

**طريقة الاختبار.**

```powershell
# lower the cap so the limit is visible
(Get-Content .env) -replace 'MAX_CONCURRENT_HEAVY_REQUESTS=\d+', 'MAX_CONCURRENT_HEAVY_REQUESTS=2' | Set-Content .env
docker compose up -d --force-recreate web1 web2 web3

# generate a burst
docker compose exec -T -e BASE_URL=http://nginx web1 python scripts/race_condition_demo.py

# count the 503s the system shed
docker compose logs web1 web2 web3 2>&1 | Select-String " 503 " | Measure-Object | Select-Object Count

# restore
(Get-Content .env) -replace 'MAX_CONCURRENT_HEAVY_REQUESTS=\d+', 'MAX_CONCURRENT_HEAVY_REQUESTS=8' | Set-Content .env
docker compose up -d --force-recreate web1 web2 web3
```

أي قيمة غير صفرية في عدّ الـ 503 تُثبت أن الـ semaphore يَدفع الحمل الزائد بدلاً من ترك العمّال في حالة استنزاف.

---

## المتطلب 3 — المعالجة غير المتزامنة (Asynchronous Queues)

**ما تم تنفيذه.** المهام البطيئة وغير الحرجة تُنقَل إلى Celery عبر وسيط Redis. عند الـ checkout يتم استدعاء `send_invoice_email` و `send_order_notifications` (في [`apps/orders/tasks.py`](apps/orders/tasks.py)) بواسطة `.delay(...)` ويعود الردّ إلى المستخدم فوراً. الإعدادان `CELERY_TASK_ACKS_LATE=True` و `prefetch_multiplier=1` يحافظان على سلامة الطابور حتى في حال انهيار العامل.

**طريقة الاختبار.** افتح نافذتين: في الأولى نراقب سجل العامل، وفي الثانية نطلق طلب checkout:

```powershell
# window 1
docker compose logs -f celery_worker

# window 2
$T = (Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/accounts/login/ `
       -ContentType "application/json" `
       -Body (@{ username="demo"; password="demo12345" } | ConvertTo-Json)).token

Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/orders/checkout-direct/ `
    -Headers @{ Authorization = "Token $T" } `
    -ContentType "application/json" `
    -Body (@{ items=@(@{product_id=1; quantity=1}); unsafe=$false } | ConvertTo-Json)
```

ردّ الـ HTTP يصل فوراً، أما السطور `timed[task.send_invoice_email]` و `timed[task.send_order_notifications]` فتظهر في سجل العامل بعد لحظات — السبب والنتيجة منفصلان زمنياً بشكل واضح.

---

## المتطلب 4 — معالجة البيانات على دفعات (Batch Processing)

**ما تم تنفيذه.** المهمة `rollup_daily_sales` في [`apps/orders/tasks.py`](apps/orders/tasks.py) تُجمّع صفوف الـ `OrderItem` ليوم كامل في سجل واحد من `DailySalesReport`. تستخدم `queryset.iterator(chunk_size=500)` — وهي تستفيد من server-side cursor في Postgres — بحيث تبقى ذروة استهلاك الذاكرة في Python بحجم O(500) سواء كان عدد العناصر في اليوم 5 000 أو 5 000 000. مُجدوَلة عبر Celery Beat الساعة 00:05 UTC يومياً.

**طريقة الاختبار.**

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/orders/reports/trigger/ `
    -ContentType "application/json" `
    -Body (@{ date="2026-06-19" } | ConvertTo-Json)

docker compose logs celery_worker --tail 50 | Select-String "rollup done"
Invoke-RestMethod http://localhost:8080/api/orders/reports/daily/ | Format-Table
```

سطر `rollup done` في السجل يُظهر `chunks_processed: N, chunk_size: 500`، ونقطة النهاية `daily-reports` تُرجع السجل المُخزَّن.

---

## المتطلب 5 — توزيع الأحمال (Load Distribution)

**ما تم تنفيذه.** ثلاثة خوادم Django متماثلة (`web1`/`web2`/`web3`) خلف Nginx باستراتيجية `least_conn` لاختيار الخادم الأعلى (انظر [`nginx/nginx.conf`](nginx/nginx.conf)). كل ردّ يحمل ترويستَي `X-Served-By` (عنوان الـ upstream) و `X-Instance` (وسم العامل من [`InstanceTagMiddleware`](apps/core/middleware.py)). الإعداد `max_fails=3 fail_timeout=10s` يُخرج الخادم المتعطل من الدوران تلقائياً. اختيار `least_conn` بدل `round_robin` كان مقصوداً: طلبات الـ checkout أثقل بكثير من التصفّح، والـ round-robin قد يوزّع طلب checkout ثالث على عامل لديه بالفعل اثنان قيد التنفيذ بينما زملاؤه عاطلون.

**طريقة الاختبار.**

```powershell
$jobs = 1..30 | ForEach-Object {
    Start-Job -ScriptBlock {
        (Invoke-WebRequest -Uri http://localhost:8080/api/health/ -UseBasicParsing).Headers["X-Instance"]
    }
}
$results = $jobs | Wait-Job | Receive-Job
$jobs | Remove-Job
$results | Group-Object | Select-Object Count, Name | Sort-Object Count -Descending
```

ينبغي أن يظهر العمّال الثلاثة في الهيستوغرام بأعداد متقاربة.

---

## المتطلب 6 — استراتيجية التخزين المؤقت (Distributed Caching)

**ما تم تنفيذه.** قراءات تفاصيل المنتج تمرّ عبر [`apps/catalog/cache_services.py::get_product_from_cache`](apps/catalog/cache_services.py)، التي تتحقق من Redis (`product:{id}`) ولا تلجأ إلى Postgres إلا عند الـ miss. الكتابات التي تُعدّل المخزون تستدعي `invalidate_product_cache(id)` من داخل معاملة الـ checkout، لذا قيم الـ cache لا تتأخر أبداً خلف المخزون الفعلي. نقطة النهاية Top-Products تُخزِّن قائمة من 20 منتجاً تحت المفتاح `top_products` لمدة 10 دقائق.

**طريقة الاختبار.**

```powershell
# hit product detail a few times
1..3 | ForEach-Object { Invoke-RestMethod http://localhost:8080/api/catalog/products/1/ | Out-Null }
docker compose logs web1 web2 web3 --tail 50 | Select-String "CACHE (HIT|MISS)"
```

النتيجة المتوقعة: `CACHE MISS` واحد ثم `CACHE HIT` في باقي الطلبات. ثم نختبر إبطال الـ cache:

```powershell
# change stock — should drop the cache key
$T = (Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/accounts/login/ `
       -ContentType "application/json" `
       -Body (@{ username="demo"; password="demo12345" } | ConvertTo-Json)).token
Invoke-RestMethod -Method Put -Uri http://localhost:8080/api/catalog/products/1/ `
    -Headers @{ Authorization = "Token $T" } `
    -ContentType "application/json" `
    -Body (@{ stock=50 } | ConvertTo-Json)
# next read shows CACHE MISS again
Invoke-RestMethod http://localhost:8080/api/catalog/products/1/ | Out-Null
docker compose logs web1 web2 web3 --tail 5 | Select-String "CACHE"
```

---

## المتطلب 7 — التحكم في الأقفال (Concurrency Control — Optimistic + Pessimistic)

**ما تم تنفيذه.** استراتيجيتا قفل تعيشان جنباً إلى جنب في [`apps/orders/services.py`](apps/orders/services.py): `checkout` (تشاؤمي — `SELECT FOR UPDATE`) و `checkout_optimistic` (بدون قفل صف — جملة `UPDATE catalog_product SET stock=..., version=version+1 WHERE id=? AND version=?` شرطية، مع إعادة محاولة محدودة حتى 5 مرات وفترة انتظار عشوائية بين المحاولات). القفل التشاؤمي يلائم الصفوف الساخنة في عملية تخفيض سريعة حيث احتمالية التضارب ≈ 1؛ القفل المتفائل يلائم الصفوف الباردة حيث احتمالية التضارب ≈ 0.

**طريقة الاختبار.**

```powershell
docker compose exec -T -e BASE_URL=http://nginx web1 python scripts/optimistic_lock_demo.py
```

نفس فكرة عرض المتطلب الأول: 100 طلب شراء متزامن (وحدة واحدة لكل طلب) على منتج رصيده 50 وحدة. النتيجة المتوقعة: 50 طلباً بـ HTTP 201 بالضبط، والباقي بـ HTTP 409 (موزّعة بين "نفاد المخزون" و "تعارض متزامن")، و `consistent = True`، و `version_after >= success` (وهذا يُثبت أن الـ conditional UPDATE هو من قام بالعمل فعلاً).

---

## المتطلب 8 — سلامة المعاملات (Transaction Integrity / ACID)

**ما تم تنفيذه.** بوابة دفع محاكاة في [`apps/orders/payments.py`](apps/orders/payments.py) تُطلق `PaymentDeclined` أو `PaymentGatewayError` بناءً على المعطيات. الاستدعاء يجلس داخل نفس كتلة `@transaction.atomic` التي تحتوي تخفيض المخزون وإنشاء الـ Order وصفوف الـ `OrderItem` (انظر `_charge_or_rollback` في [`apps/orders/services.py`](apps/orders/services.py)). أي فشل في أي خطوة يُرجِع كل شيء إلى الحالة الأصلية: يُستعاد المخزون، لا يبقى سجل `Order`، ولا يُحفظ سجل `Payment`.

**طريقة الاختبار.**

```powershell
docker compose exec -T -e BASE_URL=http://nginx web1 python scripts/acid_demo.py
```

ثلاث جولات: 30 دفعة مرفوضة (يُتوقّع 30 × HTTP 402 وبدون أي أثر جانبي)، 30 خطأ بوابة (30 × HTTP 502 وبدون أي أثر جانبي)، 30 دفعة ناجحة (30 × HTTP 201، انخفاض المخزون بمقدار 30، و +30 من الـ `APPROVED` payments). السكربت يستخدم `assert` للتحقق من الفروقات ويخرج بقيمة غير صفرية عند أي انحراف. "ALL PHASES PASSED" تعني أن خصائص ACID محقَّقة.

---

## المتطلب 9 — اختبار الاستقرار تحت الضغط (Stress Testing)

**ما تم تنفيذه.** سيناريو حركة مرور واقعية للتجارة الإلكترونية مُعرّف في [`loadtest/locustfile.py`](loadtest/locustfile.py) — تصفّح كثيف مع رشّة من عمليات الـ checkout. ردود 503 على الـ checkout مُصنّفة كـ backpressure متوقّع (صمّام الأمان من المتطلب 2)، وليست أعطالاً. خدمة Locust تعمل تحت Docker Compose profile بحيث لا يبدأ تشغيلها مع `up -d` العادي.

**طريقة الاختبار.**

```powershell
docker compose --profile loadtest run --rm locust
```

يُشغّل 100 مستخدم متزامن لمدة 60 ثانية. آخر تشغيل: **4,401 طلب، 0 فشل، 73.7 req/s، الوسيط 8 ms، p95 = 180 ms**. الأرقام الكاملة وفحوصات سلامة البيانات في [docs/STRESS_TEST_REPORT.md](docs/STRESS_TEST_REPORT.md). افتح `loadtest/report.html` للعرض البياني.

---

## المتطلب 10 — القياس وتحديد الاختناقات (Benchmarking & Bottleneck Analysis)

**ما تم تنفيذه.** أداة قياس percentile في [`scripts/benchmark.py`](scripts/benchmark.py) قاست نقطة نهاية تفاصيل المنتج المُفترض أنها مُخزَّنة فأظهرت p50 = 8.04 ms. التحقيق عبر ترويسة `X-Response-Time-Ms` و query log الخاص بـ Postgres كشف أن كل "cache hit" كان يُنفّذ في الواقع 2 SELECT و UPDATE واحدة على `catalog_product` (مفتاح الـ cache المعتمد على الـ version كان يفرض قراءة من قاعدة البيانات لحساب المفتاح، والـ view كانت تُحدّث `views_count` بشكل متزامن). الحل: استخدام مفتاح `product:{id}` فقط (صفر استعلامات قاعدة بيانات عند الـ hit)، إبطال صريح للـ cache عند تعديل المخزون، وتأجيل زيادات `views_count` إلى `redis.INCR` تُكنَس كل 60 ثانية بواسطة مهمة Celery beat جديدة ([`apps/catalog/tasks.py::flush_view_counters`](apps/catalog/tasks.py)).

**طريقة الاختبار.**

```powershell
# copy the benchmark into the container (or rebuild the image)
docker cp scripts/benchmark.py hpe_web1:/app/scripts/benchmark.py

docker compose exec -T web1 python scripts/benchmark.py `
    --url http://nginx/api/catalog/products/1/ `
    --requests 500 --concurrency 5 --label AFTER
```

النتائج بعد التحسين: **p50 = 4.10 ms (−49 %)، p99 = 9.71 ms (−43 %)، الإنتاجية 543 → 848 req/s (+56 %)، عدد استعلامات قاعدة البيانات لكل hit انخفض من 3 إلى 0.** المنهجية وجدول قبل/بعد الكامل في [docs/BENCHMARK_REPORT.md](docs/BENCHMARK_REPORT.md).

---

## خارطة الملفات (File map)

| الموضوع | الموقع |
|---|---|
| القفل التشاؤمي + المتفائل في الـ checkout (المتطلبان 1 و 7) | [apps/orders/services.py](apps/orders/services.py) |
| محاكاة بوابة الدفع (المتطلب 8) | [apps/orders/payments.py](apps/orders/payments.py) |
| المهام غير المتزامنة + المعالجة على دفعات (المتطلبان 3 و 4) | [apps/orders/tasks.py](apps/orders/tasks.py) |
| Capacity middleware + AOP timing (المتطلبان 2 و 5) | [apps/core/middleware.py](apps/core/middleware.py) |
| الـ Cache + العدّاد (المتطلبان 6 و 10) | [apps/catalog/cache_services.py](apps/catalog/cache_services.py)، [apps/catalog/tasks.py](apps/catalog/tasks.py) |
| إعدادات الـ Load Balancer (المتطلب 5) | [nginx/nginx.conf](nginx/nginx.conf) |
| سكربتات العرض التجريبي | [scripts/](scripts) |
| سيناريو اختبار الضغط | [loadtest/locustfile.py](loadtest/locustfile.py) |
| التقارير | [docs/STRESS_TEST_REPORT.md](docs/STRESS_TEST_REPORT.md)، [docs/BENCHMARK_REPORT.md](docs/BENCHMARK_REPORT.md) |
