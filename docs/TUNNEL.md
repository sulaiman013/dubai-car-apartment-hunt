# Phone Access via Cloudflare Quick Tunnel

A free, ephemeral public HTTPS URL pointing to a Python static-file server on your laptop.

## What it does

1. Starts `python -m http.server 8765 --bind 127.0.0.1` in the project root
2. Starts `cloudflared tunnel --url http://localhost:8765`
3. Cloudflared connects outbound to Cloudflare's edge and reverse-tunnels HTTPS traffic to your laptop
4. The CLI prints a URL like `https://random-words.trycloudflare.com` — open this on any device

## Run it

```bash
# Double-click or:
powershell -ExecutionPolicy Bypass -File share_via_tunnel.ps1
```

What you'll see:
```
===========================================
 Dubai Hunt - phone tunnel
===========================================
 Serving root:  C:\Users\Lenovo\Desktop\dubai cars
 Local URL:     http://localhost:8765/

 Started local server (PID 12345)
 Local server responding (HTTP 200)

 Starting Cloudflare Quick Tunnel...
 Watch for: https://something-random.trycloudflare.com
```

Then cloudflared prints something like:
```
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at:                                           |
|  https://reported-kids-regard-lodge.trycloudflare.com                                        |
+--------------------------------------------------------------------------------------------+
```

## Pages reachable

- `https://<tunnel>/` — landing (links to both dashboards)
- `https://<tunnel>/Car%20Deals%20Frontend/` — cars dashboard
- `https://<tunnel>/Apartment%20Hunt%20Frontend/` — apartments dashboard
- `https://<tunnel>/Car%20Search%20-%20Dubai%20UAE/dubai_cars.csv` — raw cars CSV
- `https://<tunnel>/Apartment%20Search%20-%20Dubai/apartments.csv` — raw apartments CSV

(The space-containing folder names URL-encode to `%20`.)

## Stop

- Close the cmd window (Ctrl+C), **or**
- `Stop-Process -Name cloudflared, python` in PowerShell

The script's `finally` clause also kills the local python server when cloudflared exits.

## Caveats

### The URL is ephemeral
Every fresh launch yields a new `*.trycloudflare.com` URL. Bookmark it but expect rotation if your laptop reboots or you stop the tunnel.

### No auth
Anyone with the URL can browse. Treat the URL as a shared secret. Don't paste in public chats / screenshots / Slack.

### Bandwidth
Cloudflare Quick Tunnel is free for development use. Plenty for personal browsing. Heavy concurrent users could hit limits but you're a sample size of one.

### Persistent named tunnel (future)
If you want a stable URL like `cars.yourdomain.com`, you'd need:
- A Cloudflare account
- A domain on Cloudflare
- `cloudflared tunnel login` → `cloudflared tunnel create cars` → DNS route → run with `tunnel run`

Out of scope for now; ephemeral works for one user.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `cloudflared.exe not found` | Wasn't installed | Re-download: https://github.com/cloudflare/cloudflared/releases/latest (Windows AMD64 binary) into `~/cloudflared/` |
| Local server status != 200 | Python not on PATH, or port 8765 already used | `Get-Process python` then kill; or change the port in `share_via_tunnel.ps1` |
| `Failed to dial to edge` | No internet | Wait |
| Tunnel works but pages 404 | Subfolder name typo in URL | Use the exact `/Car%20Deals%20Frontend/` path (case-sensitive on Linux/Cloudflare even though Windows isn't) |
| Tunnel works but `data.js` is stale | Browser cached | Hard refresh: Ctrl+Shift+R (desktop) / pull to refresh (mobile) |

## Why not just expose the static HTML directly via a free host?

- Data is regenerated locally daily by scheduled tasks. A static host would need a deploy step.
- Tunnel is zero-deploy: the same file the scraper writes is the file the browser reads.
- Trade-off: laptop must be on while you want to browse.

## Why not ngrok?

Same idea, but ngrok requires an account for HTTPS, free tier has tighter limits, and we already have cloudflared installed. Could swap if you ever want a stable subdomain via ngrok paid.
