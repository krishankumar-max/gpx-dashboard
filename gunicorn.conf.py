# gunicorn.conf.py — Gunicorn production configuration
#
# Usage:
#   gunicorn --config gunicorn.conf.py "app:app"
#
# EC2 t2.micro has 1 vCPU and 1 GB RAM.
# 2 workers × 2 threads = 4 concurrent requests — safe for t2.micro.
# Increase workers on t2.small or larger.

import multiprocessing
import os

# ── Workers ───────────────────────────────────────────────────────────────────
# Formula: (2 × CPU cores) + 1, capped at 4 for t2.micro RAM budget.
# Each worker loads the full Flask app + pandas/pyarrow into memory (~150 MB).
workers     = min(4, (2 * multiprocessing.cpu_count()) + 1)
worker_class = "sync"       # sync workers are fine — no async endpoints
threads     = 2             # 2 threads per worker for concurrent requests

# ── Network ───────────────────────────────────────────────────────────────────
bind        = "127.0.0.1:5001"   # Nginx proxies to this; never expose to 0.0.0.0
backlog     = 256

# ── Timeouts ──────────────────────────────────────────────────────────────────
# Sync endpoint can run for minutes on large date ranges.
timeout     = 300           # 5 minutes — covers large syncs
keepalive   = 5
graceful_timeout = 30

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog   = "/var/log/sapphyre/gunicorn_access.log"
errorlog    = "/var/log/sapphyre/gunicorn_error.log"
loglevel    = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sµs'

# ── Process ───────────────────────────────────────────────────────────────────
pidfile     = "/var/run/sapphyre/gunicorn.pid"
daemon      = False         # systemd manages the process — never daemonise here

# ── Security ─────────────────────────────────────────────────────────────────
limit_request_line    = 4096
limit_request_fields  = 100
limit_request_field_size = 8190

# ── Hooks ─────────────────────────────────────────────────────────────────────
def on_starting(server):
    server.log.info("Sapphyre Analytics starting up...")

def worker_exit(server, worker):
    server.log.info(f"Worker {worker.pid} exited.")
