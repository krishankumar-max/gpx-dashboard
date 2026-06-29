#!/usr/bin/env bash
# deploy/setup.sh — EC2 bootstrap for Sapphyre Analytics Dashboard
#
# Tested on: Ubuntu 22.04 LTS (t2.micro, ap-south-1)
# Run as: ubuntu user with sudo rights
#
# Usage:
#   chmod +x deploy/setup.sh
#   sudo bash deploy/setup.sh
#
# After running this script:
#   1. Edit /opt/sapphyre/.env
#   2. Run: sudo systemctl start sapphyre
#   3. Run: sudo certbot --nginx -d your-domain.com

set -euo pipefail

APP_USER="sapphyre"
APP_DIR="/opt/sapphyre"
REPO_URL="${REPO_URL:-}"   # Set this if you want to git clone automatically

echo "════════════════════════════════════════════════════════════"
echo " Sapphyre Analytics — EC2 Setup Script"
echo " Ubuntu 22.04 / t2.micro"
echo "════════════════════════════════════════════════════════════"

# ── 1. System packages ─────────────────────────────────────────────────────────
echo "[1/10] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    python3-pip \
    postgresql \
    postgresql-contrib \
    libpq-dev \
    nginx \
    certbot \
    python3-certbot-nginx \
    git \
    curl \
    htop \
    logrotate \
    awscli \
    build-essential

# ── 2. Create application user ────────────────────────────────────────────────
echo "[2/10] Creating application user..."
id -u "$APP_USER" &>/dev/null || useradd --system --shell /bin/bash --home "$APP_DIR" "$APP_USER"

# ── 3. Create directory structure ─────────────────────────────────────────────
echo "[3/10] Creating directory structure..."
mkdir -p "$APP_DIR"
mkdir -p "$APP_DIR/data/config"
mkdir -p "$APP_DIR/data/raw"
mkdir -p "$APP_DIR/data/aggregated"
mkdir -p /var/log/sapphyre
mkdir -p /var/run/sapphyre

# ── 4. PostgreSQL setup ────────────────────────────────────────────────────────
echo "[4/10] Configuring PostgreSQL..."
systemctl enable postgresql
systemctl start postgresql

# Create database and user
# IMPORTANT: Change 'sapphyre_password' to a strong password before running!
DB_PASS="${DB_PASSWORD:-sapphyre_change_this_password}"

sudo -u postgres psql <<EOF
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sapphyre') THEN
    CREATE ROLE sapphyre LOGIN PASSWORD '${DB_PASS}';
  END IF;
END
\$\$;

SELECT 'CREATE DATABASE sapphyre_db OWNER sapphyre'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'sapphyre_db')\gexec
GRANT ALL PRIVILEGES ON DATABASE sapphyre_db TO sapphyre;
EOF

echo "  PostgreSQL: database 'sapphyre_db' ready."
echo "  DATABASE_URL will be: postgresql://sapphyre:${DB_PASS}@localhost:5432/sapphyre_db"

# ── 5. Deploy application ──────────────────────────────────────────────────────
echo "[5/10] Deploying application..."
if [ -n "$REPO_URL" ]; then
    git clone "$REPO_URL" "$APP_DIR" || git -C "$APP_DIR" pull
else
    echo "  REPO_URL not set — assuming files are already in $APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ── 6. Python virtual environment ─────────────────────────────────────────────
echo "[6/10] Creating Python virtual environment..."
sudo -u "$APP_USER" python3.12 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip --quiet
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet
echo "  Python environment ready."

# ── 7. Environment file ────────────────────────────────────────────────────────
echo "[7/10] Creating .env template (EDIT BEFORE STARTING)..."
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.production.template" "$APP_DIR/.env"
    sed -i "s|DATABASE_URL=.*|DATABASE_URL=postgresql://sapphyre:${DB_PASS}@localhost:5432/sapphyre_db|" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
    echo "  ⚠  Edit $APP_DIR/.env and fill in SAPPHYRE_API_KEY, S3_BUCKET, SECRET_KEY"
fi

# ── 8. Run database migrations ─────────────────────────────────────────────────
echo "[8/10] Skipping migrations (run manually after editing .env)"
echo "  Commands to run after .env is configured:"
echo "    cd $APP_DIR && source .venv/bin/activate"
echo "    alembic upgrade head"
echo "    python scripts/migrate_to_pg.py"

# ── 9. Nginx configuration ─────────────────────────────────────────────────────
echo "[9/10] Installing Nginx configuration..."
cp "$APP_DIR/deploy/nginx/sapphyre.conf" /etc/nginx/sites-available/sapphyre
ln -sf /etc/nginx/sites-available/sapphyre /etc/nginx/sites-enabled/sapphyre
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx || echo "  ⚠  Nginx config check failed — fix sapphyre.conf"

# ── 10. Systemd service ────────────────────────────────────────────────────────
echo "[10/10] Installing systemd service..."
cp "$APP_DIR/deploy/sapphyre.service" /etc/systemd/system/sapphyre.service
systemctl daemon-reload
systemctl enable sapphyre
echo "  Service installed. Start with: sudo systemctl start sapphyre"

# ── Logrotate ──────────────────────────────────────────────────────────────────
cat > /etc/logrotate.d/sapphyre <<'LOGROTATE'
/var/log/sapphyre/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    sharedscripts
    postrotate
        systemctl kill -s USR1 sapphyre 2>/dev/null || true
    endscript
}
LOGROTATE

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo " Setup complete!  Next steps:"
echo ""
echo " 1. Edit $APP_DIR/.env"
echo "    - Set SAPPHYRE_API_KEY"
echo "    - Set S3_BUCKET, STORAGE_BACKEND=s3"
echo "    - Set SECRET_KEY (generate: python3 -c \"import secrets; print(secrets.token_hex(32))\")"
echo "    - Verify DATABASE_URL"
echo ""
echo " 2. Apply migrations:"
echo "    cd $APP_DIR && source .venv/bin/activate"
echo "    alembic upgrade head"
echo "    python scripts/migrate_to_pg.py"
echo ""
echo " 3. Start the service:"
echo "    sudo systemctl start sapphyre"
echo "    sudo systemctl status sapphyre"
echo ""
echo " 4. Set up SSL (free):"
echo "    sudo certbot --nginx -d your-domain.com"
echo ""
echo " 5. Verify:"
echo "    curl http://localhost:5001/api/status"
echo "════════════════════════════════════════════════════════════"
