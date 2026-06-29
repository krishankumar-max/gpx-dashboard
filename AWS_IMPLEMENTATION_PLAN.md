# AWS Free Tier Implementation Plan — Sapphyre Dashboard

## Audit Findings

### What Is Already Done

| Component | Status |
|---|---|
| `StorageProvider` ABC | ✅ Complete |
| `LocalStorage` | ✅ Complete |
| `S3Storage` class skeleton | ⚠️ Skeleton — all `NotImplementedError` |
| `StorageFactory` | ✅ Complete |
| `RepositoryFactory` | ✅ Complete (`json` + `pg` routing) |
| `JsonGameConfigRepository` | ✅ Complete |
| `JsonPublisherRepository` | ✅ Complete |
| `JsonPartnerRepository` | ✅ Complete |
| `PgGameConfigRepository` | ⚠️ Skeleton — all `NotImplementedError` |
| `PgPublisherRepository` | ⚠️ Skeleton — all `NotImplementedError` |
| `PgPartnerRepository` | ⚠️ Skeleton — all `NotImplementedError` |
| `PgDb` / session management | ✅ Ready (`init_db()` wired to SQLAlchemy) |
| ORM schema (5 tables) | ✅ Defined in `pg/schema.py` |
| Alembic migrations | ✅ `001_initial_schema.py` exists |
| Service layer (6 services) | ✅ Complete |
| Blueprint layer (8 blueprints) | ✅ Complete |
| `app.py` thin wiring | ✅ Complete (819 lines) |
| `backend/config.py` env vars | ✅ All vars present |

---

### Remaining Filesystem Dependencies

#### 1. `backend/config.py` — Unconditional `mkdir()` at import
```python
RAW_DIR.mkdir(parents=True, exist_ok=True)   # line 42
AGG_DIR.mkdir(parents=True, exist_ok=True)   # line 43
```
**Fix:** Make conditional on `STORAGE_BACKEND != "s3"`.

#### 2. `backend/routes/sync_bp.py` — `api_sync_clear` uses raw filesystem
```python
from backend.config import RAW_DIR, AGG_DIR
for p in list(RAW_DIR.glob("*.parquet")):
    p.unlink(); deleted += 1
for p in list(AGG_DIR.glob("*.parquet")):
    p.unlink(); deleted += 1
```
**Fix:** Add `delete_all_raw()` + `delete_summary()` to `StorageProvider` ABC and call them via the active provider.

#### 3. `backend/services/game_config.py` — `scan_discovered_offers` reads parquet via local path
```python
path = raw_path_fn(date)
if path is None or not Path(path).exists():
    continue
sub = pq.read_table(str(path), columns=[...]).to_pandas()
```
**Fix:** Accept `storage: StorageProvider` instead of `raw_path_fn`. Use `storage.raw_day_exists(date)` + `storage.load_raw_day(date, columns=[...])`.

#### 4. `backend/services/analytics.py` — `offers_map` same pattern
```python
path = raw_path_fn(date)
if path is None or not pq.read_schema(str(path)):
    continue
pairs = pq.read_table(str(path), columns=[...]).to_pandas()
```
**Fix:** Same — accept `storage: StorageProvider`, use provider methods.

#### 5. `backend/routes/admin_bp.py` + `offers_bp.py` — pass `raw_path` as `raw_path_fn`
```python
from backend.storage import raw_path as _raw_path
return jsonify(game_config_svc().get_status(avail_dates, _raw_path, ...))
```
**Fix:** After B3, remove `raw_path_fn` parameter entirely. Services get storage via `deps.py`.

---

### Remaining JSON → PostgreSQL Work

All three `Pg*Repository` classes have stub `NotImplementedError` on every method.

**Tables ready in PostgreSQL (migration 001):**
- `game_configs`
- `publishers`
- `partners`
- `partner_assignments`
- `sync_history`

**Work required:**
1. Implement all CRUD methods in `PgGameConfigRepository`
2. Implement all CRUD methods in `PgPublisherRepository`
3. Implement all CRUD methods in `PgPartnerRepository`
4. Call `init_db()` in `app.py` when `REPO_BACKEND=pg`
5. Create `scripts/migrate_to_pg.py` — one-shot seed from JSON files

---

### `StorageProvider` ABC — Missing Methods

Current ABC is missing two bulk-delete methods needed for `sync/clear`:

```python
# To add:
@abstractmethod
def delete_all_raw(self) -> int:
    """Delete all raw day files. Returns count deleted."""

@abstractmethod  
def delete_summary(self) -> None:
    """Delete the aggregated summary file."""
```

---

## Target Architecture

```
EC2 t2.micro (Ubuntu 22.04)
│
├── Nginx :443/:80
│   ├── /static/** → filesystem (fast static serving)
│   └── /* → proxy_pass to Gunicorn :5001
│
├── Gunicorn :5001
│   └── app:app (Flask)
│       ├── Route → Service → Repository → Storage
│       │                        ├── pg (REPO_BACKEND=pg)  → PostgreSQL (localhost:5432)
│       │                        └── json (REPO_BACKEND=json) → data/config/*.json
│       └── Sync engine (background thread)
│           └── StorageProvider (STORAGE_BACKEND=s3) → S3 Bucket
│
├── PostgreSQL 15 (localhost:5432)
│   └── sapphyre_db
│       ├── game_configs
│       ├── publishers
│       ├── partners
│       ├── partner_assignments
│       └── sync_history
│
└── Logs (local, Loguru)
    └── /var/log/sapphyre/app.log
```

**S3 Bucket layout:**
```
s3://your-bucket/
├── raw/
│   ├── 2026-01-01.parquet
│   └── 2026-01-02.parquet
├── aggregated/
│   └── daily_summary.parquet
├── exports/
└── uploads/
```

---

## Environment Variables

```env
# === API ===
SAPPHYRE_API_KEY=your_api_key_here
SAPPHYRE_BASE_URL=https://cashback.sapphyre.in/api/stats/postbacks

# === Application ===
SECRET_KEY=generate-with-python-secrets-token-hex-32
LOG_LEVEL=INFO
FLASK_ENV=production

# === Repository backend ===
REPO_BACKEND=pg                          # json | pg
DATABASE_URL=postgresql://sapphyre:password@localhost:5432/sapphyre_db

# === Storage backend ===
STORAGE_BACKEND=s3                       # local | s3
S3_BUCKET=your-s3-bucket-name
S3_RAW_PREFIX=raw/
S3_AGG_PREFIX=aggregated/
AWS_REGION=ap-south-1

# === Cache backend ===
CACHE_BACKEND=dict                       # dict (no Redis on Free Tier)

# === Sync tuning ===
SYNC_WORKERS=40
SYNC_PAGE_SIZE=2000
SYNC_DAY_WORKERS=2
SYNC_DAYS_BACK=7
```

---

## Implementation Phases

### Phase A — PostgreSQL repositories (this session)
- A1: `PgGameConfigRepository` — full CRUD
- A2: `PgPublisherRepository` + `PgPartnerRepository` — full CRUD
- A3: Wire `init_db()` into `app.py`; create `scripts/migrate_to_pg.py`

### Phase B — S3 Storage (this session)
- B1: Add `delete_all_raw()` + `delete_summary()` to ABC + `LocalStorage`; fix `sync_bp.py`
- B2: Implement full `S3Storage` (boto3 + s3fs + pyarrow)
- B3: Fix `raw_path_fn` pattern → `StorageProvider` injection in services + routes
- B4: Conditional `mkdir()` in `config.py`

### Phase C — Deployment files (this session)
- `gunicorn.conf.py`
- `nginx/sapphyre.conf` (security headers, rate limiting, static serving, SSL termination)
- `deploy/sapphyre.service` (systemd)
- `deploy/setup.sh` (EC2 bootstrap: Python, PostgreSQL 15, Nginx, Gunicorn)
- `.env.production.template`
- `deploy/DEPLOYMENT.md` (full runbook: launch, configure, deploy, backup, rollback)

### Phase D — Final
- Update `requirements.txt` (gunicorn, psycopg2-binary, sqlalchemy, alembic, boto3, s3fs, tenacity)
- Full smoke test (syntax + import check on all backends)

---

## Deployment Checklist (preview)

**EC2:**
- [ ] Launch t2.micro, Ubuntu 22.04, 20GB gp2 storage, ap-south-1
- [ ] Security group: 22 (your IP), 80 (all), 443 (all)
- [ ] Attach IAM role with S3 read/write policy

**Server setup:**
- [ ] `sudo apt update && sudo apt install -y python3.12 python3.12-venv postgresql-15 nginx`
- [ ] Create PostgreSQL user + database
- [ ] Clone repo, create `.env`, install requirements

**Deploy:**
- [ ] `alembic upgrade head`
- [ ] `python scripts/migrate_to_pg.py` (one-time JSON→PG seed)
- [ ] `sudo systemctl enable --now sapphyre`
- [ ] `sudo nginx -t && sudo systemctl reload nginx`

**Verify:**
- [ ] `curl http://localhost:5001/api/status`
- [ ] Dashboard loads at https://your-domain

**Backup:**
- [ ] S3 versioning enabled on bucket
- [ ] PostgreSQL: daily `pg_dump` cron → S3
- [ ] Logs: `/var/log/sapphyre/` with 30-day rotation

---

## AWS Free Tier Budget

| Service | Usage | Free Tier |
|---|---|---|
| EC2 t2.micro | 24/7 | 750 hrs/mo → $0 |
| S3 storage | ~1 GB Parquet | 5 GB → $0 |
| S3 requests | ~10k/month | 20k PUT + 200k GET → $0 |
| Data transfer | Minimal | 1 GB/month → $0 |
| **Total** | | **~$0/month** |

No RDS, no ALB, no ElastiCache, no Lambda, no CloudFront.
