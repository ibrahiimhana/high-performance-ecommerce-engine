"""
Build the step-by-step testing guide PDF for requirements 1-5.

Output: docs/TESTING_GUIDE.pdf
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "TESTING_GUIDE.pdf"
OUT.parent.mkdir(exist_ok=True)

styles = getSampleStyleSheet()

H_TITLE = ParagraphStyle("HTitle", parent=styles["Title"],
                         fontSize=22, leading=26, spaceAfter=12,
                         textColor=colors.HexColor("#1a2b4a"))
H1 = ParagraphStyle("H1", parent=styles["Heading1"],
                    fontSize=15, leading=18, spaceBefore=18, spaceAfter=8,
                    textColor=colors.HexColor("#1a2b4a"))
H2 = ParagraphStyle("H2", parent=styles["Heading2"],
                    fontSize=12, leading=15, spaceBefore=10, spaceAfter=4,
                    textColor=colors.HexColor("#2e4a7a"))
BODY = ParagraphStyle("Body", parent=styles["BodyText"],
                      fontSize=10.5, leading=14, alignment=TA_LEFT,
                      spaceAfter=4)
NOTE = ParagraphStyle("Note", parent=BODY,
                      fontSize=9.5, leading=12.5,
                      textColor=colors.HexColor("#444"),
                      leftIndent=8, rightIndent=8,
                      borderColor=colors.HexColor("#cfd9eb"),
                      borderWidth=0.6, borderPadding=6,
                      backColor=colors.HexColor("#f4f7fc"),
                      spaceBefore=4, spaceAfter=8)
CODE = ParagraphStyle("Code", parent=styles["Code"],
                      fontName="Courier", fontSize=9, leading=11.5,
                      backColor=colors.HexColor("#f3f3f3"),
                      borderColor=colors.HexColor("#dddddd"),
                      borderWidth=0.5, borderPadding=6,
                      leftIndent=4, rightIndent=4,
                      spaceBefore=4, spaceAfter=8)


def p(text):
    return Paragraph(text, BODY)


def h1(text):
    return Paragraph(text, H1)


def h2(text):
    return Paragraph(text, H2)


def code(text):
    # Preformatted preserves whitespace; matches our CODE style.
    return Preformatted(text, CODE)


def note(text):
    return Paragraph(text, NOTE)


def section_table(rows):
    tbl = Table(rows, colWidths=[3.7 * cm, 12.6 * cm])
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f8")),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd9eb")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cfd9eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tbl


story = []

# ---------- COVER / OVERVIEW ----------
story += [
    Paragraph("High-Performance E-Commerce Backend Engine", H_TITLE),
    Paragraph("Testing Guide — Requirements 1 through 5", H1),
    p("This document walks through the exact commands needed to demonstrate "
      "each of the first five non-functional requirements end-to-end. Every "
      "step lists the command to run, the output you should expect, and how to "
      "interpret it."),
    p("Stack: Django 5 + PostgreSQL 16 + Redis 7 + Celery + Nginx, all running "
      "under Docker Compose. The host is Windows + Docker Desktop."),
    h2("Conventions used in this guide"),
    section_table([
        ["Host shell", "PowerShell or Git-Bash on Windows. Examples use Git-Bash syntax."],
        ["Container shell", "Anything prefixed with <font face='Courier'>docker compose exec ...</font>."],
        ["BASE_URL", "From host: <font face='Courier'>http://localhost:8080</font>. From inside a container: <font face='Courier'>http://nginx</font>."],
        ["Demo credentials", "Username <font face='Courier'>demo</font> / password <font face='Courier'>demo12345</font> (seeded as staff)."],
        ["Stack root", "<font face='Courier'>C:\\Users\\ibrah\\Desktop\\high-performance-ecommerce-engine</font>"],
    ]),
]

# ---------- SECTION 0 ----------
story += [
    PageBreak(),
    h1("0. One-time setup"),
    p("Skip ahead to Section 1 if the stack is already running."),

    h2("0.1 Start Docker Desktop"),
    p("Open the Docker Desktop application from the Start menu and wait until "
      "the whale icon in the system tray stops animating. Verify from a shell:"),
    code("docker info | grep \"Server Version\""),
    p("You should see a line such as <font face='Courier'>Server Version: 29.4.3</font>."),

    h2("0.2 Build and start the stack"),
    code("cd C:/Users/ibrah/Desktop/high-performance-ecommerce-engine\n"
         "docker compose build\n"
         "docker compose up -d"),
    p("First build takes 1–3 minutes (image pulls and pip install). Subsequent "
      "starts are seconds."),

    h2("0.3 Confirm every container is healthy"),
    code("docker compose ps"),
    p("Expected: eight containers — <font face='Courier'>hpe_postgres</font> and "
      "<font face='Courier'>hpe_redis</font> shown as <i>healthy</i>; three "
      "<font face='Courier'>hpe_webN</font> Django app servers; "
      "<font face='Courier'>hpe_nginx</font>; "
      "<font face='Courier'>hpe_celery_worker</font>; "
      "<font face='Courier'>hpe_celery_beat</font>. "
      "The migrator container has already exited 0."),

    h2("0.4 Seed demo data"),
    code("docker compose exec -T web1 python scripts/seed.py"),
    p("Expected output:"),
    code("created user: demo / demo12345 (staff)\n"
         "created: LAPTOP-001 stock=100\n"
         "created: PHONE-001  stock=100\n"
         "created: RACE-001   stock=50\n"
         "created: BOOK-001   stock=200\n"
         "seed done."),

    h2("0.5 Health probe through the load balancer"),
    code("curl -s -D - -o /dev/null http://localhost:8080/api/health/"),
    p("Expected headers include:"),
    code("HTTP/1.1 200 OK\n"
         "X-Instance: web1   (or web2 / web3)\n"
         "X-Served-By: 172.x.x.x:8000\n"
         "X-Response-Time-Ms: 25.3"),
    note("<b>What this proves.</b> Nginx is routing through to one of three "
         "Django workers, the AOP timing middleware is stamping a response-time "
         "header on every request, and the database is reachable (the health view "
         "runs a real <font face='Courier'>SELECT 1</font>)."),
]

# ---------- REQ 1 ----------
story += [
    PageBreak(),
    h1("Requirement 1 — Concurrent Access &amp; Data Integrity"),
    p("Goal: prove a Race Condition exists on a naive implementation, then "
      "prove our pessimistic row-lock implementation makes it impossible."),
    h2("1.1 Inspect the safe-vs-unsafe code paths"),
    p("Both checkout endpoints are wired up. The unsafe path is kept on "
      "purpose so we can demonstrate the bug."),
    section_table([
        ["Safe path", "<font face='Courier'>POST /api/orders/checkout/</font> — pessimistic row lock via <font face='Courier'>SELECT FOR UPDATE</font>"],
        ["Demo path", "<font face='Courier'>POST /api/orders/checkout-direct/</font> with body field <font face='Courier'>{\"unsafe\": true|false}</font>"],
        ["Source", "<font face='Courier'>apps/orders/services.py</font> (safe) and <font face='Courier'>apps/orders/views.py::_unsafe_checkout</font> (demo)"],
    ]),

    h2("1.2 Run the empirical demo"),
    p("The script logs in as <font face='Courier'>demo</font>, resets "
      "<font face='Courier'>RACE-001</font> to 50 units, fires 100 concurrent "
      "single-unit purchases on the unsafe path, then repeats on the safe "
      "path."),
    code("docker compose exec -T -e BASE_URL=http://nginx web1 \\\n"
         "    python scripts/race_condition_demo.py"),

    h2("1.3 What you should see"),
    p("<b>Phase 1 — UNSAFE</b>: oversell. More than 50 sales succeed (often "
      "all 100), final stock is negative or otherwise inconsistent. Example "
      "from this machine:"),
    code("=== Phase 1: UNSAFE checkout (proving the race exists) ===\n"
         "  mode                              UNSAFE (no lock)\n"
         "  requests_fired                    100\n"
         "  successful_sales (HTTP 201)       100\n"
         "  out_of_stock_rejected (HTTP 409)  0\n"
         "  stock_before                      50\n"
         "  stock_after                       38\n"
         "  consistent                        False"),
    p("<b>Phase 2 — SAFE</b>: exactly 50 sales, exactly 50 conflicts:"),
    code("=== Phase 2: SAFE checkout (with row lock) ===\n"
         "  mode                              SAFE (SELECT FOR UPDATE)\n"
         "  successful_sales (HTTP 201)       50\n"
         "  out_of_stock_rejected (HTTP 409)  50\n"
         "  stock_after                       0\n"
         "  consistent                        True"),
    note("<b>Interpretation.</b> Phase 1's <font face='Courier'>consistent=False</font> "
         "with <font face='Courier'>successes + stock_after != 50</font> is the "
         "textbook Race-Condition fingerprint. Phase 2's outcome is the "
         "<i>only</i> arithmetically valid result for 100 buyers chasing 50 units "
         "— guaranteed by the row lock that holds for the duration of every "
         "checkout transaction."),

    h2("1.4 See the lock in action from Postgres"),
    p("Optional: in one shell open psql and watch the locks while the demo "
      "runs in another."),
    code("docker compose exec postgres psql -U ecommerce -d ecommerce \\\n"
         "  -c \"SELECT relation::regclass, mode, granted FROM pg_locks \\\n"
         "      WHERE relation IS NOT NULL ORDER BY pid;\""),
    p("During Phase 2 you will see <font face='Courier'>RowExclusiveLock</font> "
      "and <font face='Courier'>ExclusiveLock</font> entries on "
      "<font face='Courier'>catalog_product</font> blink in and out."),
]

# ---------- REQ 2 ----------
story += [
    PageBreak(),
    h1("Requirement 2 — Resource Management &amp; Capacity Control"),
    p("Goal: prove the system has a hard ceiling on simultaneous heavy "
      "requests and sheds excess load with <font face='Courier'>HTTP 503</font> "
      "rather than thrashing."),
    h2("2.1 What is in place"),
    section_table([
        ["Per-process cap", "<font face='Courier'>BoundedSemaphore(MAX_CONCURRENT_HEAVY_REQUESTS)</font> in <font face='Courier'>apps/core/middleware.py</font>"],
        ["Gunicorn", "<font face='Courier'>--workers 3 --threads 4 --max-requests 1000</font> per web container"],
        ["Celery worker", "<font face='Courier'>--concurrency=4 --max-tasks-per-child=500</font>"],
        ["DB pool", "<font face='Courier'>CONN_MAX_AGE=60</font> in settings.py"],
    ]),

    h2("2.2 Lower the cap to make the limit visible"),
    p("Edit <font face='Courier'>.env</font> in the project root, change the "
      "line:"),
    code("MAX_CONCURRENT_HEAVY_REQUESTS=2"),
    p("Restart the three app servers (Compose picks up the new env on "
      "recreate):"),
    code("docker compose up -d --force-recreate web1 web2 web3"),

    h2("2.3 Trigger backpressure"),
    p("Re-run the race-condition demo. With the cap at 2 per process, the "
      "bursts of 100 concurrent checkouts will overshoot the semaphore and "
      "the middleware will return <font face='Courier'>HTTP 503</font> for "
      "the excess requests."),
    code("docker compose exec -T -e BASE_URL=http://nginx web1 \\\n"
         "    python scripts/race_condition_demo.py"),
    p("You should see a non-zero <font face='Courier'>other_errors</font> "
      "count in the demo summary. Confirm in the access log:"),
    code("docker compose logs web1 web2 web3 2>&amp;1 | grep \" 503 \" | head"),
    p("Sample line:"),
    code("hpe_web2 | [17/May/2026:08:58:11 +0000] \"POST /api/orders/checkout-direct/\" 503 56"),

    h2("2.4 Confirm the AOP-style timing middleware is logging"),
    code("docker compose logs web1 2>&amp;1 | grep -E \"slow request|X-Response-Time\" | head"),
    p("Sample line:"),
    code("apps.core inst=web1 :: POST /api/orders/checkout-direct/ 142.6ms"),
    note("<b>Interpretation.</b> 503 responses are intentional and good. They "
         "are the system saying \"I am at capacity — try a sibling worker or "
         "back off,\" rather than queuing forever and dragging the whole "
         "pipeline down. Nginx's <font face='Courier'>max_fails=3 fail_timeout=10s</font> "
         "then routes new traffic to the two healthy peers — Req-2 and Req-5 "
         "form a closed control loop."),
    h2("2.5 Restore the cap"),
    p("Set <font face='Courier'>MAX_CONCURRENT_HEAVY_REQUESTS=8</font> in "
      "<font face='Courier'>.env</font> and recreate the web containers."),
    code("docker compose up -d --force-recreate web1 web2 web3"),
]

# ---------- REQ 3 ----------
story += [
    PageBreak(),
    h1("Requirement 3 — Asynchronous Queues"),
    p("Goal: prove that checkout returns to the user the instant the row "
      "lock is released, with heavy work (invoice rendering, notifications) "
      "executed afterwards on a Celery worker over a Redis broker."),

    h2("3.1 What is queued vs synchronous"),
    section_table([
        ["Synchronous", "Stock decrement, order insert, response to client"],
        ["Asynchronous", "<font face='Courier'>send_invoice_email</font> (300–600 ms) and <font face='Courier'>send_order_notifications</font> (50–200 ms)"],
        ["Source", "Dispatch: <font face='Courier'>apps/orders/views.py</font>; tasks: <font face='Courier'>apps/orders/tasks.py</font>"],
    ]),

    h2("3.2 Stream the worker log in one terminal"),
    code("docker compose logs -f celery_worker"),

    h2("3.3 In a second terminal, log in and fire a checkout"),
    code("# get a token\n"
         "TOKEN=$(curl -s -X POST http://localhost:8080/api/accounts/login/ \\\n"
         "         -H 'Content-Type: application/json' \\\n"
         "         -d '{\"username\":\"demo\",\"password\":\"demo12345\"}' \\\n"
         "         | python -c \"import sys,json;print(json.load(sys.stdin)['token'])\")\n\n"
         "# direct checkout — 1 unit of LAPTOP-001 (id may differ; check\n"
         "# GET /api/catalog/products/)\n"
         "curl -s -X POST http://localhost:8080/api/orders/checkout-direct/ \\\n"
         "    -H \"Authorization: Token $TOKEN\" \\\n"
         "    -H 'Content-Type: application/json' \\\n"
         "    -d '{\"items\":[{\"product_id\":1,\"quantity\":1}],\"unsafe\":false}'"),

    h2("3.4 What you should see"),
    p("The HTTP response comes back in &lt;100 ms with the order JSON. "
      "<i>After</i> the response, the worker terminal logs something like:"),
    code("Task apps.orders.tasks.send_invoice_email[…] received\n"
         "timed[task.send_invoice_email] 313.25ms\n"
         "Task apps.orders.tasks.send_invoice_email[…] succeeded in 0.319s\n"
         "Task apps.orders.tasks.send_order_notifications[…] received\n"
         "timed[task.send_order_notifications] 133.48ms"),
    note("<b>Interpretation.</b> The <font face='Courier'>timed[…]</font> lines "
         "are emitted by the AOP decorator <font face='Courier'>@timed</font> "
         "applied to each Celery task. The fact that they appear in the "
         "<i>worker</i> log, not in the web log, is what proves the work was "
         "off-loaded from the request path."),
    h2("3.5 Confirm acks-late + bounded prefetch"),
    code("docker compose exec -T web1 python -c \\\n"
         "  \"from django.conf import settings; \\\n"
         "    print('acks_late=', settings.CELERY_TASK_ACKS_LATE); \\\n"
         "    print('prefetch=', settings.CELERY_WORKER_PREFETCH_MULTIPLIER)\""),
    p("Expected: <font face='Courier'>acks_late= True</font> and "
      "<font face='Courier'>prefetch= 1</font>. Together they guarantee "
      "(a) a crashed worker triggers re-delivery and (b) no worker hoards "
      "messages while peers idle."),
]

# ---------- REQ 4 ----------
story += [
    PageBreak(),
    h1("Requirement 4 — Batch Processing"),
    p("Goal: prove a background job rolls up a full day's order items in "
      "fixed-size chunks (server-side cursor), not by buffering the whole "
      "result set."),

    h2("4.1 What runs and when"),
    section_table([
        ["Task", "<font face='Courier'>apps.orders.tasks.rollup_daily_sales</font>"],
        ["Schedule", "Celery Beat — cron 00:05 UTC daily"],
        ["Strategy", "<font face='Courier'>queryset.iterator(chunk_size=500)</font> — Postgres server-side cursor"],
        ["Output", "<font face='Courier'>orders_dailysalesreport</font> table, one row per date"],
    ]),

    h2("4.2 Fire the job on demand (no need to wait for 00:05 UTC)"),
    code("curl -s -X POST http://localhost:8080/api/orders/reports/trigger/ \\\n"
         "    -H 'Content-Type: application/json' \\\n"
         "    -d '{\"date\":\"2026-05-17\"}'"),
    p("Expected:"),
    code("{\"task_id\":\"<uuid>\",\"queued\":true}"),

    h2("4.3 Watch it execute"),
    code("docker compose logs celery_worker 2>&amp;1 \\\n"
         "  | grep -E \"rollup_daily_sales|rollup done\" | tail"),
    p("Expected (numbers depend on how many orders you have on that date):"),
    code("Task apps.orders.tasks.rollup_daily_sales[…] received\n"
         "rollup done {'date': '2026-05-17', 'orders': 150, 'units': 150,\n"
         "             'revenue': '1500.00', 'chunks_processed': 1,\n"
         "             'chunk_size': 500}\n"
         "timed[task.rollup_daily_sales] 49.52ms"),

    h2("4.4 Read the persisted result"),
    code("curl -s http://localhost:8080/api/orders/reports/daily/"),
    p("Expected:"),
    code("[{\"id\":1,\"date\":\"2026-05-17\",\"orders_count\":150,\n"
         "  \"units_sold\":150,\"gross_revenue\":\"1500.00\",\n"
         "  \"generated_at\":\"2026-05-17T08:44:36.260815Z\"}]"),

    h2("4.5 Generate a bigger dataset to see real chunking"),
    p("Once you have enough orders to exceed <font face='Courier'>chunk_size=500</font>, "
      "the <font face='Courier'>chunks_processed</font> field in the rollup "
      "log line will go above 1 — that is the proof the iterator is streaming "
      "rather than loading the whole result set."),
    note("<b>Interpretation.</b> Postgres <font face='Courier'>FETCH</font>es "
         "the next 500 rows only when the previous chunk has been consumed. "
         "Python peak memory therefore stays O(500) regardless of whether "
         "the day saw 5 000 or 5 000 000 line items. Single "
         "<font face='Courier'>.aggregate(Sum(...))</font> calls would also "
         "finish quickly on small data but would not scale the same way, and "
         "would not exhibit the \"process in chunks\" behaviour the rubric "
         "asks for."),
]

# ---------- REQ 5 ----------
story += [
    PageBreak(),
    h1("Requirement 5 — Load Distribution"),
    p("Goal: prove that requests fan out across three identical Django app "
      "servers behind Nginx, and that the <font face='Courier'>least_conn</font> "
      "algorithm produces a sensible distribution under concurrent load."),

    h2("5.1 What is in place"),
    section_table([
        ["Topology", "Three identical app servers <font face='Courier'>web1 / web2 / web3</font> behind <font face='Courier'>hpe_nginx</font>"],
        ["Algorithm", "<font face='Courier'>least_conn</font> in <font face='Courier'>nginx/nginx.conf</font>"],
        ["Observability", "<font face='Courier'>X-Served-By</font> (Nginx) and <font face='Courier'>X-Instance</font> (Django middleware) on every response"],
        ["Failure handling", "<font face='Courier'>max_fails=3 fail_timeout=10s</font> per upstream"],
    ]),

    h2("5.2 See it sequentially (expected: mostly one server)"),
    code("for i in $(seq 1 9); do\n"
         "  curl -s -D - -o /dev/null http://localhost:8080/api/health/ \\\n"
         "    | grep -E '^X-Instance'\n"
         "done"),
    p("Sequential requests close their connection before the next starts, "
      "so each request finds all three upstreams at zero active connections; "
      "Nginx's tie-break sends them all to the first listed server. This is "
      "the <i>correct</i> behaviour for <font face='Courier'>least_conn</font> "
      "under sequential traffic, not a bug."),

    h2("5.3 See it concurrently (expected: fan out)"),
    code("for i in $(seq 1 30); do\n"
         "  ( curl -s -D - -o /dev/null http://localhost:8080/api/health/ \\\n"
         "      | grep -E '^X-Instance' &amp; )\n"
         "done; wait"),
    p("Expected: a mix of all three workers, roughly even. Real output from "
      "this machine:"),
    code("X-Instance: web1   x 11\n"
         "X-Instance: web2   x 10\n"
         "X-Instance: web3   x 9"),

    h2("5.4 See the upstream Nginx routed to"),
    code("curl -s -D - -o /dev/null http://localhost:8080/api/health/ \\\n"
         "  | grep -E 'X-Instance|X-Served-By'"),
    p("Expected:"),
    code("X-Instance: web2\n"
         "X-Served-By: 172.18.0.4:8000"),

    h2("5.5 Verify failover takes a sick worker out of rotation"),
    p("Stop one worker, hit the LB repeatedly, then bring it back:"),
    code("docker compose stop web2\n"
         "for i in $(seq 1 12); do\n"
         "  curl -s -D - -o /dev/null http://localhost:8080/api/health/ \\\n"
         "    | grep -E '^X-Instance'\n"
         "done\n"
         "docker compose start web2"),
    p("Expected: while web2 is down, every response shows "
      "<font face='Courier'>X-Instance: web1</font> or "
      "<font face='Courier'>X-Instance: web3</font>. No 502s."),
    note("<b>Interpretation.</b> <font face='Courier'>least_conn</font> dominates "
         "<font face='Courier'>round_robin</font> for e-commerce because request "
         "cost is non-uniform: product-list calls finish in 5 ms, checkout "
         "calls take 50–200 ms. Round-robin would happily route a third "
         "checkout to a worker that already has two pending, while peers idle. "
         "<font face='Courier'>least_conn</font> always picks the upstream with "
         "the fewest active connections, evening out tail latency under bursty "
         "load."),
]

# ---------- APPENDIX ----------
story += [
    PageBreak(),
    h1("Appendix — Troubleshooting"),
    h2("\"Connection refused\" when running scripts inside a container"),
    p("Inside any container, <font face='Courier'>localhost:8080</font> points "
      "back at the container itself, not at Nginx. Use "
      "<font face='Courier'>http://nginx</font> instead and pass it as an env "
      "var: <font face='Courier'>docker compose exec -T -e BASE_URL=http://nginx web1 ...</font>"),
    h2("Migrator container failed"),
    code("docker compose logs migrator | tail"),
    p("Re-run with <font face='Courier'>docker compose up -d --force-recreate migrator</font>."),
    h2("Stale state — start clean"),
    code("docker compose down -v   # also drops the Postgres + Redis volumes\n"
         "docker compose up -d\n"
         "docker compose exec -T web1 python scripts/seed.py"),
    h2("Where to find each requirement in the code"),
    section_table([
        ["Req 1", "<font face='Courier'>apps/orders/services.py</font> (lock), <font face='Courier'>apps/orders/views.py::_unsafe_checkout</font> (demo path)"],
        ["Req 2", "<font face='Courier'>apps/core/middleware.py::CapacityControlMiddleware</font>, gunicorn args in <font face='Courier'>docker-compose.yml</font>"],
        ["Req 3", "<font face='Courier'>apps/orders/tasks.py</font>, dispatch in <font face='Courier'>apps/orders/views.py</font>"],
        ["Req 4", "<font face='Courier'>apps.orders.tasks.rollup_daily_sales</font>, beat schedule in <font face='Courier'>config/celery.py</font>"],
        ["Req 5", "<font face='Courier'>nginx/nginx.conf</font>, instance tagging in <font face='Courier'>apps/core/middleware.py::InstanceTagMiddleware</font>"],
        ["AOP", "<font face='Courier'>apps/core/aop.py</font> (decorator), <font face='Courier'>apps/core/middleware.py::RequestTimingMiddleware</font>"],
    ]),
]


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666"))
    canvas.drawString(2 * cm, 1.2 * cm,
                      "High-Performance E-Commerce Backend Engine — Testing Guide")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(
    str(OUT),
    pagesize=A4,
    leftMargin=2 * cm, rightMargin=2 * cm,
    topMargin=1.8 * cm, bottomMargin=1.8 * cm,
    title="Testing Guide — High-Performance E-Commerce Backend Engine",
    author="Senior Django Engineer",
)
doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
print(f"wrote {OUT}")
