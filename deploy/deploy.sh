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
    git curl ca-certificates iptables-persistent xvfb \
    debian-keyring debian-archive-keyring apt-transport-https
ok "apt packages installed"

# Pinned public IP for cert hostname (sslip.io magic-DNS)
PUB_IP=$(curl -4 -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
SSLIP_HOST="${PUB_IP}.sslip.io"
echo "  Public IP: $PUB_IP  →  HTTPS host: $SSLIP_HOST"

# Node.js 24 via NodeSource (if not present or too old)
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | grep -oP '\d+' | head -1)" -lt 20 ]]; then
    step "Installing Node.js 24"
    if [[ "$DEPLOY_USER" == "root" ]]; then
        curl -fsSL https://deb.nodesource.com/setup_24.x | bash -
    else
        curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
    fi
    $SUDO apt-get install -y -qq nodejs
fi
ok "Node $(node -v), npm $(npm -v)"

# ─── 1b. Caddy (auto-HTTPS reverse proxy) ─────────────────────────────────────
if ! command -v caddy >/dev/null 2>&1; then
    step "Installing Caddy (auto-HTTPS)"
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | $SUDO gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | $SUDO tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq caddy
fi
ok "Caddy $(caddy version 2>&1 | head -1)"

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
# Playwright/Patchright ship Chromium binaries but require system shared libs
# (libcups2, libpango, libnspr4, etc.). install-deps knows the canonical set.
python3 -m playwright install-deps chromium >/dev/null 2>&1 || \
    $SUDO apt-get install -y -qq libcups2 libpango-1.0-0 libcairo2 libnspr4 >/dev/null 2>&1 || true
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

# ─── 5b. regenerate data.js for cars + apartments dashboards ──────────────────
step "Regenerating dashboard data.js files"
.venv/bin/python -X utf8 "Car Deals Frontend/prep_data.py" 2>&1 | tail -3 || warn "cars prep_data.py failed"
.venv/bin/python -X utf8 "Apartment Hunt Frontend/prep_data.py" 2>&1 | tail -3 || warn "apts prep_data.py failed"
ok "data.js refreshed"

# ─── 5c. tighten secret + DB permissions ──────────────────────────────────────
step "Tightening file permissions"
chmod 600 "${PROJECT_DIR}/Telegram Bot/.env" 2>/dev/null || true
chmod 600 "${PROJECT_DIR}/db/dubai_hunt.db" 2>/dev/null || true
ok "Secrets + DB are now 0600"

# ─── 6. systemd units ─────────────────────────────────────────────────────────
step "Installing systemd services"

$SUDO tee /etc/systemd/system/dubai-hunt-api.service >/dev/null <<EOF
[Unit]
Description=Dubai Hunt FastAPI (internal — Caddy fronts 80/443)
After=network.target

[Service]
Type=simple
User=${DEPLOY_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=CORS_ORIGINS=https://${SSLIP_HOST},http://${SSLIP_HOST},http://${PUB_IP},http://127.0.0.1:8090,http://localhost:8090
ExecStart=${PROJECT_DIR}/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8090
Restart=on-failure
RestartSec=5

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
$SUDO systemctl enable dubai-hunt-api.service dubai-hunt-bot.service >/dev/null 2>&1
# Always restart so freshly-pulled code (and updated unit files) take effect
$SUDO systemctl restart dubai-hunt-api.service
$SUDO systemctl restart dubai-hunt-bot.service
sleep 3
$SUDO systemctl is-active --quiet dubai-hunt-api && ok "API service up" || warn "API not running — check 'journalctl -u dubai-hunt-api -n 50'"
$SUDO systemctl is-active --quiet dubai-hunt-bot && ok "Bot service up" || warn "Bot not running — check 'journalctl -u dubai-hunt-bot -n 50'"

# ─── 7. cron for daily scrapes ────────────────────────────────────────────────
step "Setting up cron for daily scrapes (12:00 / 12:30 UTC = 18:00 / 18:30 BD)"
CRON_CARS="0 12 * * * cd ${PROJECT_DIR} && ${PROJECT_DIR}/.venv/bin/python -X utf8 'Car Search - Dubai UAE/scrape_dubai_cars.py' >> /var/log/dubai-cars.log 2>&1"
# Apartments scraper uses Patchright with headless=False to bypass Bayut's bot wall.
# On a headless VPS that requires a virtual display — xvfb-run wraps it transparently.
CRON_APTS="30 12 * * * cd ${PROJECT_DIR} && /usr/bin/xvfb-run -a ${PROJECT_DIR}/.venv/bin/python -X utf8 'Apartment Search - Dubai/scrape_apartments.py' >> /var/log/dubai-apts.log 2>&1"

$SUDO touch /var/log/dubai-cars.log /var/log/dubai-apts.log
$SUDO chown "${DEPLOY_USER}:${DEPLOY_USER}" /var/log/dubai-cars.log /var/log/dubai-apts.log

( crontab -l 2>/dev/null | grep -v 'dubai-hunt' || true ; echo "$CRON_CARS" ; echo "$CRON_APTS" ) | crontab -
ok "Cron installed"

# ─── 7b. SSH hardening + fail2ban ─────────────────────────────────────────────
# Only disable password auth if the running SSH user has at least one authorized key —
# otherwise we'd lock the operator out of the box.
step "SSH hardening + fail2ban"
AUTH_KEYS="${DEPLOY_HOME}/.ssh/authorized_keys"
if [[ -s "$AUTH_KEYS" ]]; then
    # Cloud-init / cloud-image drop-ins under /etc/ssh/sshd_config.d/ are loaded
    # alphabetically AND the first occurrence of each directive wins. So we
    # write to 01-* to beat any 50-cloud-init.conf default.
    SSHD_DROPIN=/etc/ssh/sshd_config.d/01-dubai-hunt-hardening.conf
    $SUDO tee "$SSHD_DROPIN" >/dev/null <<'EOF'
# Managed by deploy.sh — re-applied on every deploy.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
EOF
    $SUDO chmod 644 "$SSHD_DROPIN"
    # validate before reload — sshd refuses to reload with a bad config
    if $SUDO sshd -t 2>/dev/null; then
        $SUDO systemctl reload ssh 2>/dev/null || $SUDO systemctl reload sshd 2>/dev/null || true
        ok "Password + keyboard-interactive auth disabled (key-only)"
    else
        $SUDO rm -f "$SSHD_DROPIN"
        warn "sshd config validation failed — hardening reverted"
    fi
else
    warn "No SSH key in $AUTH_KEYS — leaving PasswordAuthentication alone to avoid lockout"
fi

# fail2ban: auto-ban brute-forcers
if ! command -v fail2ban-client >/dev/null 2>&1; then
    $SUDO apt-get install -y -qq fail2ban >/dev/null
fi
$SUDO tee /etc/fail2ban/jail.local >/dev/null <<'EOF'
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
EOF
$SUDO systemctl enable --now fail2ban >/dev/null 2>&1 || true
$SUDO systemctl is-active --quiet fail2ban && ok "fail2ban active (sshd jail enabled)" || warn "fail2ban not active — check 'journalctl -u fail2ban -n 30'"

# ─── 7c. Caddy reverse proxy + auto-HTTPS ─────────────────────────────────────
step "Configuring Caddy reverse proxy + Let's Encrypt for ${SSLIP_HOST}"
$SUDO tee /etc/caddy/Caddyfile >/dev/null <<EOF
# Managed by deploy.sh — Dubai Hunt
{
    # global options
    email admin@${SSLIP_HOST}
}

# HTTPS site (Caddy auto-issues + auto-renews Let's Encrypt cert)
${SSLIP_HOST} {
    encode gzip
    reverse_proxy 127.0.0.1:8090
}

# Bare-IP HTTP — redirect to HTTPS host so old http://IP/ links still work
http://${PUB_IP} {
    redir https://${SSLIP_HOST}{uri} permanent
}
EOF
$SUDO systemctl enable caddy >/dev/null 2>&1
$SUDO systemctl restart caddy
sleep 4
$SUDO systemctl is-active --quiet caddy && ok "Caddy active (TLS for ${SSLIP_HOST} provisioning)" \
    || warn "Caddy not active — check 'journalctl -u caddy -n 40'"

# ─── 8. health check ──────────────────────────────────────────────────────────
step "Health check"
sleep 5
# Internal probe — bypasses Caddy
HTTP_INT=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8090/api/health || echo "000")
[[ "$HTTP_INT" == "200" ]] && ok "FastAPI internal :8090 healthy" || warn "FastAPI internal not responding (got $HTTP_INT)"
# External probe via Caddy on the HTTPS host. -k tolerates the brief window before cert lands.
HTTP_EXT=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 15 "https://${SSLIP_HOST}/" || echo "000")
if [[ "$HTTP_EXT" == "200" ]]; then
    ok "HTTPS healthy at https://${SSLIP_HOST}/"
else
    warn "HTTPS not 200 yet (got $HTTP_EXT) — Let's Encrypt cert provisioning can take up to 90s; retry in a minute"
fi

echo
echo "════════════════════════════════════════════════════════════════"
echo "  ✅  Deploy complete"
echo "════════════════════════════════════════════════════════════════"
echo
echo "  Landing:    https://${SSLIP_HOST}/"
echo "  Cars:       https://${SSLIP_HOST}/Car%20Deals%20Frontend/"
echo "  Apartments: https://${SSLIP_HOST}/Apartment%20Hunt%20Frontend/"
echo "  Ops:        https://${SSLIP_HOST}/Ops%20Dashboard/"
echo "  API docs:   https://${SSLIP_HOST}/docs"
echo
echo "  (http://${PUB_IP}/... still works, auto-redirects to HTTPS)"
echo
echo "  Manage:"
echo "    systemctl status dubai-hunt-api dubai-hunt-bot"
echo "    journalctl -u dubai-hunt-api -f      # tail API log"
echo "    journalctl -u dubai-hunt-bot -f      # tail bot log"
echo "    crontab -l                            # show daily scrapes"
echo
