#!/usr/bin/env bash
# ============================================================
#  Dubai Hunt — one-shot deploy for Ubuntu 22.04 (root user OK).
#  Run on the VPS as the user that owns the project dir:
#      cd ~/dubai-hunt && bash deploy/deploy.sh
#
#  Works on Hostinger (root), Oracle Cloud (ubuntu), Hetzner, etc.
#  Idempotent — re-runnable. Will not destroy SQLite DB or .env files.
# ============================================================
set -euo pipefail

# Detect runtime user + home so the same script works on Hostinger (root)
# AND Oracle/Hetzner (ubuntu) AND anywhere else.
DEPLOY_USER="$(whoami)"
DEPLOY_HOME="$HOME"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# We need sudo for system-wide things. If we're root, sudo is a no-op shim.
if [[ "$DEPLOY_USER" == "root" ]]; then
    SUDO=""
else
    SUDO="sudo"
fi

# ─── style helpers ────────────────────────────────────────────────────────────
step() { echo -e "\n\e[1;34m▶ $*\e[0m"; }
ok()   { echo -e "  \e[32m✓\e[0m $*"; }
warn() { echo -e "  \e[33m⚠\e[0m $*"; }

echo "════════════════════════════════════════════════════════════════"
echo "  Dubai Hunt deploy"
echo "════════════════════════════════════════════════════════════════"
echo "  User:        $DEPLOY_USER"
echo "  Home:        $DEPLOY_HOME"
echo "  Project dir: $PROJECT_DIR"
echo

# ─── 1. system packages ───────────────────────────────────────────────────────
step "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -qq
# Note: chromium-browser is a transitional package on 22.04+; the real Chromium for ARM
# is best installed via Patchright/Playwright (handled in Step 3). Skip apt's chromium-browser
# (it's a snap shim) — we just need its system deps.
$SUDO apt-get install -y -qq --no-install-recommends \
    python3 python3-pip python3-venv sqlite3 \
    fonts-liberation libnss3 libatk-bridge2.0-0 libxss1 libgbm1 libasound2 \
    libxkbcommon0 libdrm2 libxcomposite1 libxdamage1 libxrandr2 libxshmfence1 \
    git curl ca-certificates iptables-persistent
ok "apt packages installed"

# Node.js 24 via NodeSource (if not present or too old)
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | grep -oP '\d+' | head -1)" -lt 20 ]]; then
    step "Installing Node.js 24"
    curl -fsSL https://deb.nodesource.com/setup_24.x | $SUDO -E bash -
    $SUDO apt-get install -y -qq nodejs
fi
ok "Node $(node -v), npm $(npm -v)"

# ─── 2. iptables (Hostinger usually has none, Oracle has REJECT default) ──────
step "Ensuring inbound ports 80/443 are open"
if ! $SUDO iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null; then
    # Try to insert BEFORE any REJECT line (Oracle Ubuntu); on Hostinger this is a no-op append
    $SUDO iptables -I INPUT 1 -p tcp --dport 80  -m state --state NEW,ESTABLISHED -j ACCEPT
fi
if ! $SUDO iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null; then
    $SUDO iptables -I INPUT 1 -p tcp --dport 443 -m state --state NEW,ESTABLISHED -j ACCEPT
fi
$SUDO netfilter-persistent save >/dev/null 2>&1 || $SUDO iptables-save | $SUDO tee /etc/iptables/rules.v4 >/dev/null
ok "Ports 80 + 443 open"

# ─── 3. python venv + deps ────────────────────────────────────────────────────
step "Setting up Python venv"
cd "$PROJECT_DIR"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q fastapi uvicorn[standard] patchright playwright beautifulsoup4 lxml
python3 -m patchright install chromium >/dev/null 2>&1 || python3 -m playwright install chromium >/dev/null 2>&1
ok "Python env ready"

# ─── 4. node deps for the bot ─────────────────────────────────────────────────
step "Installing Node deps"
cd "$PROJECT_DIR/Telegram Bot"
npm install --silent --no-audit --no-fund
ok "Telegram Bot/node_modules ready"
cd "$PROJECT_DIR"

# ─── 5. DB init ───────────────────────────────────────────────────────────────
step "Initialising SQLite DB"
.venv/bin/python -c "import sys; sys.path.insert(0,'.'); from db.db import init_db; init_db(); print('DB ready')"
ROW_COUNT=$(.venv/bin/python -c "import sqlite3; con=sqlite3.connect('db/dubai_hunt.db'); print(con.execute('SELECT COUNT(*) FROM cars').fetchone()[0])")
if [[ "$ROW_COUNT" -eq 0 ]]; then
    warn "cars table empty — running migrate_from_json.py if JSON snapshots present"
    .venv/bin/python -X utf8 db/migrate_from_json.py || true
fi
ok "DB ready ($ROW_COUNT cars rows pre-existing)"

# ─── 6. systemd units ─────────────────────────────────────────────────────────
step "Installing systemd services"

$SUDO tee /etc/systemd/system/dubai-hunt-api.service >/dev/null <<EOF
[Unit]
Description=Dubai Hunt FastAPI
After=network.target

[Service]
Type=simple
User=${DEPLOY_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${PROJECT_DIR}/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 80
Restart=on-failure
RestartSec=5
# Allow binding to port 80 without being root (only needed if User != root)
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
EOF

$SUDO tee /etc/systemd/system/dubai-hunt-bot.service >/dev/null <<EOF
[Unit]
Description=Dubai Hunt Telegram Bot
After=network.target dubai-hunt-api.service
Wants=dubai-hunt-api.service

[Service]
Type=simple
User=${DEPLOY_USER}
WorkingDirectory=${PROJECT_DIR}/Telegram Bot
ExecStart=/usr/bin/node tg_bot.js
Restart=on-failure
RestartSec=5
StandardOutput=append:${PROJECT_DIR}/Telegram Bot/bot.log
StandardError=append:${PROJECT_DIR}/Telegram Bot/bot.err

[Install]
WantedBy=multi-user.target
EOF

$SUDO systemctl daemon-reload
$SUDO systemctl enable --now dubai-hunt-api.service
$SUDO systemctl enable --now dubai-hunt-bot.service
sleep 3
$SUDO systemctl is-active --quiet dubai-hunt-api && ok "API service up" || warn "API not running — check 'journalctl -u dubai-hunt-api -n 50'"
$SUDO systemctl is-active --quiet dubai-hunt-bot && ok "Bot service up" || warn "Bot not running — check 'journalctl -u dubai-hunt-bot -n 50'"

# ─── 7. cron for daily scrapes ────────────────────────────────────────────────
step "Setting up cron for daily scrapes (12:00 / 12:30 UTC = 18:00 / 18:30 BD)"
CRON_CARS="0 12 * * * cd ${PROJECT_DIR} && ${PROJECT_DIR}/.venv/bin/python -X utf8 'Car Search - Dubai UAE/scrape_dubai_cars.py' >> /var/log/dubai-cars.log 2>&1"
CRON_APTS="30 12 * * * cd ${PROJECT_DIR} && ${PROJECT_DIR}/.venv/bin/python -X utf8 'Apartment Search - Dubai/scrape_apartments.py' >> /var/log/dubai-apts.log 2>&1"

$SUDO touch /var/log/dubai-cars.log /var/log/dubai-apts.log
$SUDO chown "${DEPLOY_USER}:${DEPLOY_USER}" /var/log/dubai-cars.log /var/log/dubai-apts.log

( crontab -l 2>/dev/null | grep -v 'dubai-hunt' || true ; echo "$CRON_CARS" ; echo "$CRON_APTS" ) | crontab -
ok "Cron installed"

# ─── 8. health check ──────────────────────────────────────────────────────────
step "Health check"
sleep 3
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/ || echo "000")
[[ "$HTTP_CODE" == "200" ]] && ok "API responding on :80 (HTTP 200)" || warn "API not responding on :80 (got HTTP $HTTP_CODE) — try 'sudo journalctl -u dubai-hunt-api -n 30'"

PUBIP=$(curl -s --max-time 3 ifconfig.me || echo "<your-ip>")
echo
echo "════════════════════════════════════════════════════════════════"
echo "  ✅  Deploy complete"
echo "════════════════════════════════════════════════════════════════"
echo
echo "  Landing:    http://${PUBIP}/"
echo "  Cars:       http://${PUBIP}/Car%20Deals%20Frontend/"
echo "  Apartments: http://${PUBIP}/Apartment%20Hunt%20Frontend/"
echo "  Ops:        http://${PUBIP}/Ops%20Dashboard/"
echo "  API docs:   http://${PUBIP}/docs"
echo
echo "  Manage:"
echo "    systemctl status dubai-hunt-api dubai-hunt-bot"
echo "    journalctl -u dubai-hunt-api -f      # tail API log"
echo "    journalctl -u dubai-hunt-bot -f      # tail bot log"
echo "    crontab -l                            # show daily scrapes"
echo
