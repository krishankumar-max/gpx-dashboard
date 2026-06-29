"""
Central configuration — reads from .env and environment variables.
All other modules import from here; nothing reads os.environ directly.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Resolve project root (two levels up from this file) ──────────────────────
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── API ───────────────────────────────────────────────────────────────────────
SAPPHYRE_API_KEY: str = os.environ["SAPPHYRE_API_KEY"]
SAPPHYRE_BASE_URL: str = "https://cashback.sapphyre.in/api/stats/postbacks"
SAPPHYRE_TIMEZONE: str = "Asia/Kolkata"

# ── Sync tuning ───────────────────────────────────────────────────────────────
# SYNC_WORKERS: parallel page-fetching threads PER day (inner pool).
# Hard-capped at 8 to prevent memory and connection exhaustion on t3.micro.
# More than 8 concurrent threads on 1GB RAM causes OOM before any data is saved.
SYNC_WORKERS: int    = min(int(os.getenv("SYNC_WORKERS", "6")), 8)

# SYNC_PAGE_SIZE: rows per API request.  The Sapphyre API silently caps responses
# at 500 rows regardless of this value — see API_MAX_PAGE_SIZE below.
SYNC_PAGE_SIZE: int  = int(os.getenv("SYNC_PAGE_SIZE", "500"))

# SYNC_DAY_WORKERS: how many dates to fetch in parallel (outer pool).
#                   1 = safest for t3.micro (6 page-threads already running).
SYNC_DAY_WORKERS: int = int(os.getenv("SYNC_DAY_WORKERS", "1"))

# DB_BATCH_SIZE: rows accumulated before flushing to the storage layer.
# Keeps peak in-memory list bounded regardless of total day size.
DB_BATCH_SIZE: int   = int(os.getenv("DB_BATCH_SIZE", "5000"))

SYNC_DAYS_BACK: int  = int(os.getenv("SYNC_DAYS_BACK", "7"))

# ── Storage paths ─────────────────────────────────────────────────────────────
DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DIR: Path  = DATA_DIR / "raw"
AGG_DIR: Path  = DATA_DIR / "aggregated"

# Create local directories only when using LocalStorage.
# When STORAGE_BACKEND=s3 these paths are irrelevant and should not be created,
# especially inside an EC2 instance where /data may be read-only or unwanted.
if os.getenv("STORAGE_BACKEND", "local").lower() != "s3":
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    AGG_DIR.mkdir(parents=True, exist_ok=True)

# ── Columns to retain from the API ───────────────────────────────────────────
KEEP_COLS: list[str] = [
    "_id",
    "partnerValid",
    "valid",
    "capValid",
    "goal",
    "cid",
    "country",
    "state",
    "city",
    "offer",
    "partner",
    "advertiser",
    "time",
    "errors",
    "payout",
    "revenue",
    "payoutBackup",
    "revenueBackup",
    "currency",
    "offerName",
    "advertiserName",
]

# ── Aggregation grouping keys ─────────────────────────────────────────────────
AGG_GROUP_COLS: list[str] = ["date", "partner", "offerName", "goal"]
AGG_VALUE_COLS: list[str] = ["revenue", "payout", "conversions", "valid_conversions", "unique_installs"]

# ── HTTP client settings ──────────────────────────────────────────────────────
HTTP_TIMEOUT_SECONDS: int = 60
HTTP_MAX_RETRIES: int = int(os.getenv("HTTP_MAX_RETRIES", "10"))  # per-page retry ceiling
API_MAX_PAGE_SIZE: int = 500  # Sapphyre hard-caps every response at 500 rows regardless of limit=
HTTP_RETRY_WAIT_MIN: float = 1.0
HTTP_RETRY_WAIT_MAX: float = 30.0

# ─────────────────────────────────────────────────────────────────────────────
# AWS / Production configuration
# All values default to local-development mode when env vars are absent.
# ─────────────────────────────────────────────────────────────────────────────

# ── Persistence backends ──────────────────────────────────────────────────────
# REPO_BACKEND=json  → reads/writes data/config/*.json  (default, no DB needed)
# REPO_BACKEND=pg    → reads/writes PostgreSQL via DATABASE_URL
REPO_BACKEND: str = os.getenv("REPO_BACKEND", "json")   # json | pg
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# ── Analytics storage backend ─────────────────────────────────────────────────
# STORAGE_BACKEND=local → Parquet files stay in data/raw/ + data/aggregated/
# STORAGE_BACKEND=s3    → Parquet files go to S3_BUCKET (set S3_BUCKET + AWS_REGION)
STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "local")  # local | s3
S3_BUCKET: str       = os.getenv("S3_BUCKET", "")
S3_RAW_PREFIX: str   = os.getenv("S3_RAW_PREFIX", "raw/")
S3_AGG_PREFIX: str   = os.getenv("S3_AGG_PREFIX", "aggregated/")
AWS_REGION: str      = os.getenv("AWS_REGION", "ap-south-1")

# ── Cache backend ─────────────────────────────────────────────────────────────
# CACHE_BACKEND=dict  → in-process Python dict (default, single-process only)
# CACHE_BACKEND=redis → Redis via REDIS_URL (multi-process / multi-instance)
CACHE_BACKEND: str = os.getenv("CACHE_BACKEND", "dict")   # dict | redis
REDIS_URL: str     = os.getenv("REDIS_URL", "")

# ── Application ───────────────────────────────────────────────────────────────
SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-change-in-production")
LOG_LEVEL: str  = os.getenv("LOG_LEVEL", "INFO")

# ── Supabase Auth ─────────────────────────────────────────────────────────────
# SUPABASE_URL:             project URL — used to build the JWKS endpoint for
#                           local JWT verification. Safe to commit; not a secret.
# SUPABASE_PUBLISHABLE_KEY: anon/public key sent to the browser for the JS client.
# SUPABASE_SECRET_KEY:      service_role key — reserved for future Supabase admin
#                           operations (not used for JWT verification).
#                           Never expose to the frontend or commit to git.
#
# JWT verification path: {SUPABASE_URL}/auth/v1/.well-known/jwks.json
# Keys are cached in-process by PyJWT — no outbound HTTP per request.
# When SUPABASE_URL is empty all auth checks are bypassed (dev mode).
SUPABASE_URL:             str = os.getenv("SUPABASE_URL",             "")
SUPABASE_PUBLISHABLE_KEY: str = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SUPABASE_SECRET_KEY:      str = os.getenv("SUPABASE_SECRET_KEY",      "")

# ── CORS ───────────────────────────────────────────────────────────────────────
# Comma-separated list of allowed origins for the API.
# Defaults to localhost-only for development.  In production, set to the
# exact domain(s) serving the frontend, e.g. "https://dashboard.example.com".
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5001,http://127.0.0.1:5001",
    ).split(",")
    if o.strip()
]

# ── File uploads ──────────────────────────────────────────────────────────────
# UPLOAD_BACKEND=local → files written to data/uploads/ on disk
# UPLOAD_BACKEND=s3    → files written directly to S3_BUCKET/UPLOAD_PREFIX
UPLOAD_BACKEND: str = os.getenv("UPLOAD_BACKEND", "local")  # local | s3
UPLOAD_PREFIX: str  = os.getenv("UPLOAD_PREFIX", "uploads/")
