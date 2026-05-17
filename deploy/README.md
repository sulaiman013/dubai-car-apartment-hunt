# Deploy → Oracle Cloud (Ubuntu 22.04, ARM Ampere A1)

Single-host deployment. One port (80) serves API + dashboards. SSH key auth.
Both scrapes run as nightly cron jobs (18:00 / 18:30 BD = 12:00 / 12:30 UTC).

## Prerequisites (done)
- ✅ Oracle Cloud account, free trial active (Singapore region)
- ✅ SSH key at `~/.ssh/oracle_dubai` (private) and `.pub` (public)

## What you do in the Oracle Console (5 minutes)
1. **Compute → Instances → Create instance**
2. Name: `dubai-hunt`
3. Image: **Canonical Ubuntu 22.04 (LTS)**
4. Shape: **VM.Standard.A1.Flex** with **4 OCPUs + 24 GB RAM** (full free quota)
5. SSH keys: paste the `oracle_dubai.pub` line shown in chat
6. Boot volume: **50 GB**, VPU = **10 (Balanced)** — free tier
7. Create

In the new instance's **VCN → Security List**, add ingress for:
- TCP 80   from `0.0.0.0/0`
- TCP 443  from `0.0.0.0/0`

Copy the **Public IPv4** address.

## What I do automatically (after you paste the IP)
- Generate the exact 2 commands you run on the laptop
- The first uploads the project files (rsync via SSH)
- The second SSHes in and runs `deploy.sh`
- The script idempotently sets up: Python, Node, Chromium, SQLite, FastAPI service, Telegram bot service, cron for daily scrapes, iptables for ports 80/443

Total wall-clock time after IP is pasted: ~10 minutes.

## What the deploy.sh does on the VM
1. `apt update` + install Python, Node 24, Chromium, sqlite3, iptables-persistent
2. Create Python venv, install fastapi/uvicorn/patchright/playwright
3. Install patchright + chromium browser
4. `cd Telegram Bot && npm install`
5. Initialise SQLite DB (idempotent — uses existing if present)
6. Install two systemd units:
   - `dubai-hunt-api.service` → uvicorn on port 80 (binds via `CAP_NET_BIND_SERVICE`)
   - `dubai-hunt-bot.service` → node tg_bot.js
7. Install cron entries for daily scrapes
8. Open ports 80 + 443 in iptables (persistent across reboots)
9. Health-check the API responds with HTTP 200

## After deploy succeeds
- Public landing page:  `http://<ip>/`
- Cars dashboard:       `http://<ip>/Car%20Deals%20Frontend/`
- Apartments dashboard: `http://<ip>/Apartment%20Hunt%20Frontend/`
- Ops Dashboard:        `http://<ip>/Ops%20Dashboard/`
- API docs (Swagger):   `http://<ip>/docs`
- Bot:                  `@Dubai_013_bot` on Telegram (same as before)

## Important — stop the laptop bot first
Two bots on the same Telegram token = 409 Conflict. Before deploying to VM:

```powershell
Stop-Process -Name node -Force -ErrorAction SilentlyContinue
```

Optionally disable the Windows scheduled tasks (they'll still try to start the laptop bot at next logon):

```powershell
Disable-ScheduledTask -TaskName DubaiHunt_TGbot
Disable-ScheduledTask -TaskName DubaiHunt_API
Disable-ScheduledTask -TaskName DubaiCarHunt_Daily
Disable-ScheduledTask -TaskName DubaiApartmentHunt_Daily
```

(You can re-enable them later if you want the laptop as a fallback.)

## After free trial expires (~30 days)
**Convert to Pay-As-You-Go** in Billing settings. Stays $0 actual spend as long as you remain within Always Free quota, but:
- Bypasses the 7-day idle reclamation policy
- Bypasses ARM capacity rationing
- The VM stays running indefinitely
