# Chrome on Windows — Remote Control Runbook

Controlling a Chrome browser running on a remote Windows host from Linux via WinRM. Two Chromes available: **Stable** (main, has X login cookies) and **Canary 146** (separate binary, for CDP without killing stable).

## Architecture

```
Linux (41030 / this machine)
  │
  ├── pywinrm (NTLM auth) ──► WinRM HTTP :5985 ──► Windows VPS <your-windows-host> (<windows-tailscale-ip>)
  │                                                    │
  │                  ┌──────────────────────────────────┤
  │                  │          │                       │
  │                  ▼          ▼                       ▼
  │           Chrome Stable  Chrome Canary       OpenCLI Bridge
  │           (logged-in X)  (for CDP/scratch)   (cookie strategy)
  │                                   │
  └── CDP WebSocket ──────────────────┘
      (via tunnel or local WS client on Windows)
```

**Credentials:** `$CASHFLOW_PROJECT/<your-windows-host>` (also mirrored to `$WINRM_CREDENTIALS` for actors pipeline)
- `host=<windows-tailscale-ip>`
- `user=<windows-username>`
- `pass=<strong-password>`
- Transport: `ntlm`

**Key rule:** Never print or include the password in summaries, logs, or outputs.

---

## Connection Quickstart

```python
import winrm
session = winrm.Session(
    f"http://{HOST}:5985/wsman",
    auth=(f".\\{USER}", PASSWORD),
    transport="ntlm",
    server_cert_validation="ignore",
)
result = session.run_ps("whoami")
print(result.std_out.decode())
```

**NTLM is required.** Basic auth fails on this host. Always use `transport='ntlm'` and prefix the username with `.\\`.

A helper script exists at `$CASHFLOW_PROJECT/win/winrm_ps.py` — pipe PowerShell to it from stdin:

```bash
echo 'Get-Process chrome | Format-Table Id, ProcessName' | python3 $CASHFLOW_PROJECT/win/winrm_ps.py
```

---

## Three Approaches — Which to Use

| Approach | Requires | When to use | Pitfalls |
|----------|----------|-------------|----------|
| **CDP** (Chrome DevTools Protocol) | `--remote-debugging-port` + WebSocket | Full browser control: navigate, click, extract DOM, run JS | Chrome 148+ HTTP POST broken; needs WebSocket |
| **OpenCLI Browser Bridge** | Chrome running with Bridge extension | Structured data from X/Reddit/websites (`[cookie]` strategy) | `[intercept]` strategy needs CDP; profile can go stale |
| **UIA** (UI Automation) | RDP session logged in | Read-only extraction from visible browser; fallback when CDP blocked | Slow, fragile, depends on window state |

**Golden rule:** If you need the user's logged-in X session, use **OpenCLI `[cookie]` strategy** or **CDP on Chrome Canary** (doesn't touch stable). Never kill stable Chrome.

---

## CDP — Chrome DevTools Protocol

### Discovery — scan for existing CDP first

Before launching anything, check if a CDP port is already active:

```powershell
$ports = @(9222, 9229, 9240, 9250, 9221, 9230, 9333)
foreach ($p in $ports) {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$p/json/version" -TimeoutSec 2 -ErrorAction Stop
        Write-Output "CDP ACTIVE on port $p — $($resp.Browser)"
    } catch { }
}
```

### Enabling CDP on an already-running Chrome

**Do not kill Chrome.** Open `chrome://inspect/#remote-debugging` in the existing browser and toggle it on.

However, **Chrome 148+ limitation**: the inspect toggle binds a TCP port but does NOT serve the standard HTTP CDP API (`/json/version`, `/json/list` return 404). It only enables mDNS/WebSocket discovery for DevTools on the same machine. You must verify:

```bash
curl -s http://127.0.0.1:9222/json/version
# If 404 → HTTP CDP unavailable. Use WebSocket or OpenCLI instead.
```

For full CDP (Navigate, Runtime.evaluate, etc.), you need **WebSocket** — a Python script on the Windows host using `websockets` library. See existing scrapers at `scripts/cdp-ws-scraper.py` and `scripts/cdp-ws-search-scraper.py`.

### Launching a CDP-enabled Chrome

When you need a fresh CDP-capable Chrome (e.g. for scraping), **always use Chrome Canary** to avoid merging with the stable logged-in Chrome:

```powershell
& "C:\Program Files\Google\Chrome Canary\Application\chrome.exe" `
  --remote-debugging-address=127.0.0.1 `
  --remote-debugging-port=9250 `
  --user-data-dir="C:\Temp\chrome_<purpose>" `
  --no-first-run --no-default-browser-check `
  --new-window https://x.com/login
```

**Critical flags:**
- `--remote-debugging-port=9250` — enables CDP on port 9250
- `--user-data-dir="C:\Temp\..."` — **required for Chrome 136+**; Chrome ignores `--remote-debugging-port` with the default profile
- `--user-data-dir` takes the **root** directory (containing `Default/`), not the profile itself
- Canary is a **different binary** and won't merge with stable Chrome

### Making Chrome visible on the user's desktop

WinRM runs in session 0. Chrome launched from `run_ps()` appears there — invisible to the user's interactive RDP session.

**To make it visible:** Use a scheduled task with the logged-in user:

```powershell
$action = New-ScheduledTaskAction -Execute "C:\Program Files\Google\Chrome Canary\Application\chrome.exe" `
  -Argument '--remote-debugging-port=9250 --user-data-dir=C:\Temp\chrome_scrape --no-first-run --no-default-browser-check --new-window https://x.com/login'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(3)
$principal = New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName 'ChromeCDP' -Action $action -Trigger $trigger -Principal $principal -Force
Start-ScheduledTask -TaskName 'ChromeCDP'
```

**Key:** `-UserId` must match the logged-in RDP user, not the WinRM user. `-LogonType Interactive` puts the window on the user's desktop.

### Remote CDP Tunnel (portproxy)

When Chrome is running with CDP bound to `127.0.0.1` on Windows, tunnel it to Linux for Hermes browser tools:

```powershell
netsh interface portproxy add v4tov4 listenport=9250 connectaddress=127.0.0.1 connectport=9250
netsh advfirewall firewall add rule name="CDP 9250" dir=in action=allow protocol=TCP localport=9250
```

Then set in `config.yaml`:
```yaml
browser:
  cdp_url: 'ws://<windows-tailscale-ip>:9250/devtools/browser/<uuid>'
```

**Clean up:**
```powershell
netsh interface portproxy delete v4tov4 listenport=9250
netsh advfirewall firewall delete rule name="CDP 9250"
```

### CDP in Chrome 148+ — key quirks

1. **HTTP POST to `/devtools/page/<id>` returns empty body.** Chrome accepts the command but returns `Content-Length: 0`. You MUST use WebSocket for command execution.
2. **Process merging.** Every `Start-Process` Chrome launch merges into the existing Chrome process (same PID, same window). Only Chrome Canary (separate binary) avoids this.
3. **Non-default `--user-data-dir` is mandatory.** Chrome 136+ won't honor `--remote-debugging-port` with the default profile.
4. **Profile clones don't preserve X login.** Chrome encrypts cookies with a path-derived key. Clone profiles lose it. User must log in again.
5. **`& "chrome.exe"` is blocking.** It won't return until Chrome exits. Use `Start-Process` with timeout or run in background.

---

## OpenCLI Browser Bridge

### Strategy types

Not all OpenCLI commands need CDP:

| Strategy | CDP needed? | Commands | Notes |
|----------|------------|----------|-------|
| `[cookie]` | **No** | `twitter tweets`, `twitter profile`, `twitter trending`, `web read` | Works on normally-launched Chrome |
| `[intercept]` | **Yes** | `twitter search`, `twitter notifications` | Hangs/timeout if CDP unavailable |
| `[public]` | **No** | `hackernews search`, `bluesky search`, `binance price` | Public APIs, no browser needed |
| `[ui]` | **Yes** | `twitter post`, `twitter like` | Needs CDP for element interaction |

**Key insight:** `[cookie]` commands work without any CDP setup. They extract cookies from Chrome's encrypted SQLite store via DPAPI. This means `twitter tweets`, `twitter profile`, and `web read` all work on a normally-launched stable Chrome.

### Profile management

OpenCLI creates a Browser Bridge profile per Chrome instance. When multiple Chromes are running, you get multiple profiles and must select one:

```powershell
# List profiles
opencli profile list
# → vwncsxtf  connected  — Google Chrome
# → <chrome-profile-id>  connected  — Google Chrome (stable)

# Set active (per session — must combine with command in WinRM)
opencli profile use <chrome-profile-id> 2>$null; opencli twitter tweets marclou --limit 5
```

**Important for WinRM:** Each `run_ps()` call is a fresh PowerShell session. Always combine `profile use` and the command in one string.

### Auto-detect active profile

Instead of hardcoding a profile ID, detect it dynamically:

```powershell
opencli profile list 2>&1 | Select-String "connected" | ForEach-Object { $_.ToString().Split()[0] }
```

The actors pipeline does this in `$CASHFLOW_PROJECT/pipeline/collect_signals.py` (`detect_x_profile()`).

---

## Chrome Management — Safety Rules

### Never blanket-kill Chrome

```powershell
# 🚫 NEVER DO THIS
Stop-Process -Name chrome -Force
```

This destroys DPAPI-encrypted cookies in ALL Chrome instances, logging the user out of X and every other site. The X login in stable Chrome uses DPAPI cookies that don't survive process kill.

### Targeted PID kill (when necessary)

If a specific Chrome instance is hung, kill only the process bound to its CDP port:

```powershell
$pid = (netstat -ano | Select-String 'LISTENING' | Select-String ':9250') -replace '.*\s+(\d+)$','$1'
if ($pid -match '^\d+$') { Stop-Process -Id $pid -Force }
```

### Reuse what's running

Prefer these approaches over launching new Chrome:
- OpenCLI `[cookie]` strategy — works on already-running stable Chrome
- Chrome Canary for CDP — separate binary, doesn't touch stable
- `chrome://inspect/#remote-debugging` toggle on existing Chrome (limited in 148+)
- Scan for existing CDP ports first (someone may have left one from a prior session)

### Two Chrome binaries

| Binary | Path | Purpose |
|--------|------|---------|
| Stable | `C:\Program Files\Google\Chrome\Application\chrome.exe` | User's logged-in X session. Don't kill. |
| Canary | `C:\Program Files\Google\Chrome Canary\Application\chrome.exe` | CDP scraping, temp profiles, isolated automation. |

Chrome Canary is the safe choice for any operation that needs `--remote-debugging-port`.

---

## Quoting Hell — Reliable Patterns

Sending CDP commands through WinRM requires nested quoting: Python → PowerShell → CDP JSON. Use these patterns.

### Writing a PowerShell script to Windows (base64)

```python
import base64

ps_content = '''$CDP = "http://127.0.0.1:9250"
$targets = curl.exe -s "$CDP/json" | ConvertFrom-Json
foreach ($t in $targets) { Write-Output ($t.title + " | " + $t.url) }'''

b64 = base64.b64encode(ps_content.encode('utf-8')).decode('ascii')
session.run_ps(f'[System.IO.File]::WriteAllBytes("C:\\Temp\\script.ps1", [System.Convert]::FromBase64String("{b64}"))')
session.run_ps('C:\\Temp\\script.ps1')
```

### For large scripts (>1200 bytes) — chunked upload

```python
content = ps_content.encode('utf-8')
for i in range(0, len(content), 1200):
    chunk = content[i:i+1200]
    b64 = base64.b64encode(chunk).decode('ascii')
    if i == 0:
        session.run_ps(f'[System.IO.File]::WriteAllBytes("C:\\Temp\\script.ps1", [System.Convert]::FromBase64String("{b64}"))')
    else:
        session.run_ps(f'$b=[System.Convert]::FromBase64String("{b64}");$f=[System.IO.File]::Open("C:\\Temp\\script.ps1",[System.IO.FileMode]::Append);$f.Write($b,0,$b.Length);$f.Close()')
```

### Reading output files back

```python
fetch = '[System.Convert]::ToBase64String([System.IO.File]::ReadAllBytes("C:\\Temp\\output.json"))'
r = session.run_ps(fetch)
clean = [l for l in r.split('\n') if l.strip() and not l.startswith('#<') and not l.startswith('<O')]
data = json.loads(base64.b64decode(clean[0]).decode('utf-8'))
```

### Alternative for large files — temporary HTTP server

For files >5KB, WinRM inline transfers fail silently. Use a temp HTTP server:

```python
# On Linux
import subprocess, time
proc = subprocess.Popen(['python3', '-m', 'http.server', '18999', '--directory', '/tmp'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)

# On Windows (via WinRM)
session.run_ps('curl.exe -s -o "C:\\Temp\\scraper.py" "http://<linux-ip>:18999/scraper.py"')

# Kill server
proc.terminate()
```

**Use the Linux Tailscale IP**, not the Windows IP. Verify file size after transfer.

---

## Common Pitfalls

| # | Pitfall | Fix |
|---|---------|-----|
| 1 | `chrome://inspect` toggle bound a port but HTTP CDP returns 404 (Chrome 148+) | Fall back to OpenCLI `[cookie]` or use WebSocket CDP |
| 2 | Launched Chrome but user says "I don't see it" | Chrome launched in session 0. Use scheduled task with `-LogonType Interactive` and correct `-UserId` |
| 3 | `Start-Process` Chrome merges into existing process (148+) | Use Chrome Canary (different binary) instead |
| 4 | Kill all Chrome → lost X login cookies | Never blanket-kill Chrome. Targeted PID kills only. |
| 5 | CDP POST returns empty body | Chrome 148+ HTTP CDP is half-broken. Use WebSocket |
| 6 | WinRM `2>&1` breaks output type | Don't merge stderr. Capture separately. |
| 7 | Multi-line curl output becomes array in PowerShell | `-join` before processing: `($out) -join "\`n"` |
| 8 | `VIRTUAL_ENV` warning in cron | Harmless. `unset VIRTUAL_ENV` before `uv run` to silence |
| 9 | Async function defined but never called | `async def` inside `try:` defines but doesn't execute | 
| 10 | Clipboard operations during automation | Don't use clipboard for URL/navigation. Use SendKeys or CDP `Page.navigate` |
| 11 | OpenCLI profile doesn't persist across WinRM calls | Combine `profile use` and command in one `run_ps()` string |
| 12 | Profile clone loses X login due to DPAPI path binding | Use Cookie-Only transfer (see `references/cookie-profile-transfer.md`) or login fresh |

---

## Existing Scripts & Tools

| File | Purpose |
|------|---------|
| `$CASHFLOW_PROJECT/win/winrm_ps.py` | Pipe PowerShell from stdin → execute via WinRM |
| `$CASHFLOW_PROJECT/win/enable_cdp_no_clipboard.py` | Enable CDP via UIA on running Chrome (no clipboard) |
| `$CASHFLOW_PROJECT/win/refresh_chrome_policy.py` | Refresh Chrome policy via SendKeys |
| `$CASHFLOW_PROJECT/pipeline/collect_signals.py` | Reddit + X signal collection (uses OpenCLI via WinRM) |
| `$CASHFLOW_PROJECT/win/chrome-cdp-live-session.md` | Legacy CDP notes |
| `$CASHFLOW_PROJECT/win/<your-windows-host>.md` | Windows host general documentation |
| `references/cdp-ws-scraper.py` | CDP WebSocket scraper for X profile timeline |
| `references/cdp-ws-search-scraper.py` | CDP WebSocket scraper for X search results |

---

## Decision Flow

```
Need to control Chrome on <your-windows-host>?
│
├── Need X login cookies?
│   ├── Yes → Use OpenCLI [cookie] strategy (tweets, profile, web read)
│   │         OR Chrome Canary + CDP (fresh profile, user logs in)
│   │         NEVER kill stable Chrome
│   │
│   └── No → Use Chrome Canary + CDP on temp profile
│
├── Need full browser automation (click, navigate, extract)?
│   ├── CDP port already open? → Reuse it (scan :9222-9333)
│   ├── Can use OpenCLI [cookie]? → Faster, no CDP setup needed
│   └── Need CDP → Launch Canary with --remote-debugging-port=9250
│
└── Chrome not responding?
    └── Targeted PID kill via netstat | findstr :<port>
```
