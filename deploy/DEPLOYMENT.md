# Sapphyre Analytics — EC2 Deployment Runbook

**Target**: AWS EC2 t2.micro (1 vCPU, 1 GB RAM) · Ubuntu 22.04 LTS · ap-south-1  
**Stack**: Python 3.12 · Flask · Gunicorn · Nginx · PostgreSQL (local) · S3 (Parquet files)  
**Monthly AWS cost estimate**: ~$0 (Free Tier) + ~$0.10–0.50 S3 depending on data volume

---

## Architecture Overview

```
Internet → EC2 Security Group (443/80) → Nginx → Gunicorn (127.0.0.1:5001) → Flask App
                                                                                    ↓
                                                         PostgreSQL (localhost:5432)
                                                         S3 (Parquet files)
```

Everything runs on a single EC2 instance. No RDS, no ALB, no ElastiCache.

---

## Prerequisites

### AWS side

1. Launch EC2 instance:
   - AMI: Ubuntu Server 22.04 LTS (HVM)
   - Instance type: t2.micro (Free Tier eligible)
   - Storage: 20 GB gp2 (Free Tier: 30 GB)
   - Security Group: allow SSH (22), HTTP (80), HTTPS (443) from 0.0.0.0/0
   - Key pair: create and download `.pem` file

2. Create S3 bucket:
   - Bucket name: `sapphyre-analytics-data` (or your choice)
   - Region: ap-south-1
   - Block all public access: ON
   - Versioning: OFF (saves cost)

3. Create IAM role for EC2 (no access keys needed):
   - Go to IAM → Roles → Create Role → AWS Service → EC2
   - Attach inline policy:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],
       "Resource": [
         "arn:aws:s3:::sapphyre-analytics-data",
         "arn:aws:s3:::sapphyre-analytics-data/*"
       ]
     }]
   }
   ```
   - Attach this role to your EC2 instance

4. (Optional) Point a domain at the EC2's Elastic IP.

---

## First-Time Deployment

### Step 1 — SSH into the instance

```bash
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>
```

### Step 2 — Upload application files

```bash
# From your local machine:
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude 'data/' --exclude '.env' \
    ./ ubuntu@<EC2_PUBLIC_IP>:/opt/sapphyre/
```

Or use git:

```bash
ssh ubuntu@<EC2_PUBLIC_IP>
sudo git clone https://github.com/your-org/sapphyre.git /opt/sapphyre
```

### Step 3 — Run the bootstrap script

```bash
cd /opt/sapphyre
export DB_PASSWORD="choose_a_strong_password_here"
sudo bash deploy/setup.sh
```

This installs all system packages, PostgreSQL, Nginx, Python venv, and the systemd service.

### Step 4 — Configure environment variables

```bash
sudo nano /opt/sapphyre/.env
```

Fill in:

| Variable | Value |
|---|---|
| `SAPPHYRE_API_KEY` | Your API key |
| `SECRET_KEY` | Run: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | `postgresql://sapphyre:<password>@localhost:5432/sapphyre_db` |
| `S3_BUCKET` | Your S3 bucket name |
| `STORAGE_BACKEND` | `s3` |
| `REPO_BACKEND` | `pg` |
| `AWS_REGION` | `ap-south-1` |

### Step 5 — Update Nginx config with your domain

```bash
sudo nano /etc/nginx/sites-available/sapphyre
# Replace all instances of "your-domain.com" with your actual domain
sudo nginx -t && sudo systemctl reload nginx
```

If you don't have a domain yet, comment out the HTTP→HTTPS redirect block and use the HTTP block only.

### Step 6 — Run database migrations

```bash
cd /opt/sapphyre
source .venv/bin/activate
alembic upgrade head
```

### Step 7 — Migrate existing JSON data (if applicable)

```bash
cd /opt/sapphyre
source .venv/bin/activate
python scripts/migrate_to_pg.py
```

To reset and reload from scratch:
```bash
python scripts/migrate_to_pg.py --reset
```

### Step 8 — Start the service

```bash
sudo systemctl start sapphyre
sudo systemctl status sapphyre
```

### Step 9 — Verify

```bash
# Check Gunicorn is listening
curl http://127.0.0.1:5001/api/status

# Check Nginx is proxying correctly
curl http://localhost/api/status

# Check logs
sudo journalctl -u sapphyre -n 50
tail -f /var/log/sapphyre/gunicorn_error.log
```

### Step 10 — SSL (free with Let's Encrypt)

```bash
sudo certbot --nginx -d your-domain.com
# Auto-renewal is set up automatically by certbot
```

---

## Updates / Redeployment

```bash
# On your local machine:
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude 'data/' --exclude '.env' \
    ./ ubuntu@<EC2_PUBLIC_IP>:/opt/sapphyre/

# On the server:
ssh ubuntu@<EC2_PUBLIC_IP>
cd /opt/sapphyre
source .venv/bin/activate
pip install -r requirements.txt --quiet

# Run migrations if schema changed:
alembic upgrade head

# Reload Gunicorn (zero-downtime):
sudo systemctl reload sapphyre
# OR full restart:
sudo systemctl restart sapphyre
```

---

## Backup Strategy

### PostgreSQL backup (daily, automated)

```bash
# Create backup script
sudo tee /opt/sapphyre/deploy/backup_pg.sh <<'EOF'
#!/bin/bash
set -euo pipefail
BACKUP_DIR="/opt/sapphyre/backups/pg"
DATE=$(date +%Y-%m-%d)
mkdir -p "$BACKUP_DIR"
sudo -u postgres pg_dump sapphyre_db | gzip > "$BACKUP_DIR/sapphyre_$DATE.sql.gz"
# Keep only last 30 days
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +30 -delete
echo "Backup complete: $BACKUP_DIR/sapphyre_$DATE.sql.gz"
EOF
chmod +x /opt/sapphyre/deploy/backup_pg.sh
```

```bash
# Add to crontab (runs 2am IST = 8:30pm UTC)
(crontab -l 2>/dev/null; echo "30 20 * * * /opt/sapphyre/deploy/backup_pg.sh >> /var/log/sapphyre/backup.log 2>&1") | crontab -
```

### S3 backup

Parquet files in S3 are your primary data store for raw/aggregated data. They are redundant by default (S3 Standard has 99.999999999% durability). No additional backup needed unless you want cross-region replication (not required for Free Tier budget).

### Config file backup (JSON)

If running with `REPO_BACKEND=json`, back up:
```bash
/opt/sapphyre/data/config/publishers.json
/opt/sapphyre/data/config/partners.json
/opt/sapphyre/data/config/game_configs.json
```

These are small files — copy them into the S3 bucket:
```bash
aws s3 cp /opt/sapphyre/data/config/ s3://sapphyre-analytics-data/config-backup/ --recursive
```

---

## PostgreSQL Operations

```bash
# Connect to database
sudo -u postgres psql sapphyre_db

# Check table row counts
SELECT schemaname, relname, n_live_tup
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC;

# Check database size
SELECT pg_size_pretty(pg_database_size('sapphyre_db'));

# Vacuum (reclaim space)
VACUUM ANALYZE;

# Restart PostgreSQL
sudo systemctl restart postgresql
```

### Alembic cheat sheet

```bash
cd /opt/sapphyre && source .venv/bin/activate

# Show current migration
alembic current

# Apply all pending migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1

# Create new migration
alembic revision --autogenerate -m "description"
```

---

## S3 Operations

```bash
# List Parquet files
aws s3 ls s3://sapphyre-analytics-data/raw/ --recursive

# Check total size
aws s3 ls s3://sapphyre-analytics-data/ --recursive --human-readable --summarize

# Manually sync a local file to S3
aws s3 cp data/raw/2024-01-15.parquet s3://sapphyre-analytics-data/raw/

# Download a specific day for local debugging
aws s3 cp s3://sapphyre-analytics-data/raw/2024-01-15.parquet /tmp/
```

---

## Common Troubleshooting

### App won't start

```bash
sudo journalctl -u sapphyre -n 100 --no-pager
# Check for import errors, missing .env vars, DB connection failures
```

### 502 Bad Gateway from Nginx

```bash
# Is Gunicorn running?
sudo systemctl status sapphyre
curl http://127.0.0.1:5001/api/status

# Check Nginx error log
sudo tail -f /var/log/nginx/sapphyre_error.log
```

### Database connection refused

```bash
# Is PostgreSQL running?
sudo systemctl status postgresql

# Test connection manually
sudo -u postgres psql -c "\l"

# Check pg_hba.conf allows local connections
sudo cat /etc/postgresql/*/main/pg_hba.conf | grep sapphyre
```

### S3 access denied

```bash
# Verify IAM role is attached to the instance
aws sts get-caller-identity

# Test S3 access
aws s3 ls s3://sapphyre-analytics-data/

# If using IAM role (recommended), no credentials needed
# If using access keys, check .env for AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
```

### High memory usage (t2.micro OOM)

```bash
# Check memory
free -h

# Check which process is using the most
htop

# Reduce Gunicorn workers in gunicorn.conf.py
# workers = 2  (instead of min(4, ...))
# Then restart:
sudo systemctl restart sapphyre
```

---

## Monitoring (Free Tier)

**CloudWatch** provides basic EC2 metrics (CPU, network, disk) at no cost in Free Tier.

```bash
# Install CloudWatch agent (optional but recommended)
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb
```

Alternatively, use `/api/health/digest` to check operational health from the dashboard itself.

---

## AWS Free Tier Budget Summary

| Service | Usage | Monthly Cost |
|---|---|---|
| EC2 t2.micro | 750 hrs/month | $0 (Free Tier) |
| EBS 20 GB gp2 | Included | $0 (Free Tier) |
| S3 Storage | < 5 GB | $0 (Free Tier) |
| S3 Requests | < 20K PUT/2K GET | $0 (Free Tier) |
| Data Transfer | < 100 GB out | $0 (Free Tier) |
| **Total** | | **~$0/month** |

After Free Tier expires (12 months): ~$8–10/month.

---

## Security Checklist

- [ ] `.env` file has `chmod 600` and is owned by `sapphyre` user
- [ ] `.env` is in `.gitignore` — never committed
- [ ] EC2 Security Group: SSH (22) restricted to your IP only
- [ ] PostgreSQL only listens on `localhost` (not exposed externally)
- [ ] Gunicorn only binds to `127.0.0.1:5001` (not `0.0.0.0`)
- [ ] HTTPS enabled with Let's Encrypt cert
- [ ] IAM role used for S3 access (no hardcoded AWS credentials)
- [ ] Strong `SECRET_KEY` generated and set
- [ ] Strong PostgreSQL password set
- [ ] Nginx security headers enabled (X-Frame-Options, CSP, etc.)
- [ ] HSTS enabled after confirming HTTPS works
