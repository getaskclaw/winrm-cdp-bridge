# Chrome on Windows — Remote Control Runbook

Controlling a Chrome browser running on a remote Windows host from Linux via WinRM. Two Chromes available: **Stable** (main, has X login cookies) and **Canary 146** (separate binary, for CDP without killing stable).

## Architecture

Linux (41030 / this machine)
  │
  ├── pywinrm (NTLM auth) ──► WinRM HTTP :5985 ──► Windows VPS (<windows-tailscale-ip>)
  │                                                    │
  │                  ┌──────────────────────────────────┤
  │                  ▼                                  ▼
  │           Chrome Stable                      Chrome Canary / OpenCLI
  │           (logged-in X)                      (CDP / cookie strategy)

Credentials file: `$WINRM_CREDENTIALS` (format: `host=`, `user=`, `pass=`, transport: NTLM).

## Connection

```python
import winrm
session = winrm.Session(
    f"http://{HOST}:5985/wsman",
    auth=(f".\\{USER}", PASSWORD),
    transport="ntlm",
    server_cert_validation="ignore",
)
result = session.run_ps("whoami")
```

NTLM is required. Basic auth fails. Prefix username with `.\\`.

Helper: `echo 'Get-Process chrome' | python3 /root/2604/win/winrm_ps.py`

## Three Approaches

| Approach | Requires | When to use |
|----------|----------|-------------|
| **CDP** (DevTools Protocol) | `--remote-debugging-port` + WebSocket | Full browser control: navigate, click, extract DOM, run JS. Chrome 148+ POST broken — use WebSocket. |
| **OpenCLI Browser Bridge** | Chrome running with Bridge | Structured data from X/Reddit. `[cookie]` strategy needs no CDP. `[intercept]` needs CDP. |
| **UIA** (UI Automation) | RDP session | Read-only extraction from visible browser fallback. Slow, fragile. |

**Rule:** Need X login? Use OpenCLI `[cookie]` (tweets, profile, web read) or Chrome Canary + CDP. Never kill stable Chrome.

## CDP — Key Patterns

**Scan existing ports first:**
```powershell
$ports = @(9222, 9229, 9240, 9250); foreach ($p in $ports) {
    try { Invoke-RestMethod -Uri "http://127.0.0.1:$p/json/version" -TimeoutSec 2 -ErrorAction Stop } catch {}}
```

**Chrome 148+ quirk:** `chrome://inspect` toggle binds a port but `/json/version` returns 404. HTTP CDP POST to `/devtools/page/<id>` returns empty body. Must use WebSocket for commands.

**Launch Canary (safe — separate binary, won't merge with stable):**
```powershell
& "C:\Program Files\Google\Chrome Canary\Application\chrome.exe" `
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9250 `
  --user-data-dir="C:\Temp\chrome_scrape" --no-first-run --no-default-browser-check
```

**Make visible on RDP desktop (scheduled task with correct -UserId):**
```powershell
$action = New-ScheduledTaskAction -Execute "C:\Program Files\Google\Chrome Canary\Application\chrome.exe" -Argument '--remote-debugging-port=9250 --user-data-dir=C:\Temp\chrome_scrape'
$principal = New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName 'ChromeCDP' -Action $action -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(3)) -Principal $principal -Force
Start-ScheduledTask -TaskName 'ChromeCDP'
```

**Tunnel remote CDP to Linux (portproxy):**
```powershell
netsh interface portproxy add v4tov4 listenport=9250 connectaddress=127.0.0.1 connectport=9250
netsh advfirewall firewall add rule name="CDP 9250" dir=in action=allow protocol=TCP localport=9250
```

**Kill specific hung Chrome by CDP port (never blanket kill):**
```powershell
$pid = (netstat -ano | Select-String 'LISTENING' | Select-String ':9250') -replace '.*\s+(\d+)$','$1'
if ($pid -match '^\d+$') { Stop-Process -Id $pid -Force }
```

## OpenCLI Strategy Types

| Strategy | CDP needed? | Commands |
|----------|------------|----------|
| `[cookie]` | No | `twitter tweets`, `twitter profile`, `twitter trending`, `web read` |
| `[intercept]` | Yes | `twitter search`, `twitter notifications` |
| `[public]` | No | `hackernews search`, `reddit hot`, `bluesky search` |
| `[ui]` | Yes | `twitter post`, `twitter like` |

**Profile management (must combine with command in WinRM — each run_ps is fresh):**
```powershell
opencli profile use stable_profile 2>$null; opencli twitter tweets marclou --limit 5
```
Or auto-detect: `opencli profile list | Select-String "connected"`

## Quoting Pattern (WinRM → PS → CDP)

Base64-encode scripts for reliability:
```python
import base64
b64 = base64.b64encode(ps_content.encode('utf-8')).decode('ascii')
session.run_ps(f'[System.IO.File]::WriteAllBytes("C:\\Temp\\script.ps1", [System.Convert]::FromBase64String("{b64}"))')
```

For large files >5KB: use temporary HTTP server on Linux, download via `curl.exe` on Windows.

## Safety Rules

- **Never** `Stop-Process -Name chrome -Force` — destroys DPAPI cookies in all instances
- **Targeted kill only** via `netstat -ano | findstr :<port>`
- **Reuse running Chrome** — OpenCLI `[cookie]` works on already-running stable Chrome without CDP
- **Canary for CDP** — separate binary, won't merge. `C:\Program Files\Google\Chrome Canary\Application\chrome.exe`
- **No clipboard** in automation — use SendKeys or CDP `Page.navigate`
