# Chrome 148+ CDP — Profile Clone Approach

## When to use this

You need to control a live logged-in Chrome session (e.g. X.com) via CDP from a remote Linux host, but:
- The `chrome://inspect/#remote-debugging` toggle resets on restart
- The existing Chrome is managed by another tool (OpenCLI) and you can't control its launch flags
- Chrome 136+ blocks `--remote-debugging-port` for the default profile directory

## The fix: clone the profile, launch a dedicated Chrome

Instead of trying to attach to the existing Chrome process, launch a **separate Chrome instance** with:
- A cloned copy of the logged-in profile (preserves X cookies)
- A non-default `--user-data-dir` (required for Chrome 136+)
- Its own CDP port (e.g. 9229)

## ⚠️ Critical caveat: cloned profiles break CDP relaunch

**The clone approach does NOT reliably work for continued use.** After extensive testing:

| Profile type | First launch with CDP | Re-launch after killing Chrome |
|---|---|---|
| **Fresh empty temp profile** (e.g. `$env:TEMP\chrome-cdp-proof`) | ✅ Works immediately | ✅ Works every time |
| **Clone of Administrator's profile** (robocopy) | ✅ Works once (Phase 4) | ❌ Never works again — Chrome refuses to bind CDP |
| **Fresh re-clone** (delete old clone, re-copy) | ❌ Also fails | N/A |
| **Minimal cookie-only copy** (Local State + Cookies only) | ❌ Fails immediately | N/A |

**Root cause:** Unknown, but empirically confirmed across 6+ attempts with different ports, cleanup, and re-clone strategies. Chrome detects something about the profile that prevents `--remote-debugging-port` from binding.

**Workaround:** Instead of cloning, use a fresh empty temp profile and have the user log in manually:
1. Launch Chrome with `--remote-debugging-port=<port>` and a fresh `--user-data-dir="$env:TEMP\chrome_fresh_<purpose>"`
2. Navigate to the target site via CDP
3. A Chrome window appears on the desktop — user logs in manually
4. **Do NOT kill Chrome** — run the WebSocket scraper against the running session
5. The fresh profile persists the login cookies natively (because it was created at its own path)

This avoids all clone-related issues and works 100% of the time.

## Environment (as tested)

| Property | Value |
|----------|-------|
| Windows host | 26429 (Tailscale) |
| Chrome stable | `C:\Program Files\Google\Chrome\Application\chrome.exe` (v148.0.7778.168) |
| Chrome Canary | `C:\Users\Administrator\AppData\Local\Google\Chrome SxS\Application\chrome.exe` (v150) |
| WinRM user | `winrm_user` (local admin, can read Administrator's files) |
| Source profile | `C:\Users\Administrator\AppData\Local\Google\Chrome\User Data\Default` |
| Python on Windows | Installed at `C:\Program Files\Python312\python.exe` + uv + websockets |

**Important:** Chrome switched `PATH` from `Chrome` to `Chrome SxS` for Canary in recent versions. Canary was found at the Administrator-level path, not under winrm_user.

## Phase results

### Phase 1 — Prove CDP with clean profile ✅
Launch Chrome with a temporary non-default profile and confirm CDP responds on port 9229.

```powershell
$Chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$DebugRoot = Join-Path $env:TEMP 'chrome-cdp-proof'
New-Item -ItemType Directory -Path $DebugRoot | Out-Null
Start-Process -FilePath $Chrome -ArgumentList @(
  '--remote-debugging-address=127.0.0.1',
  '--remote-debugging-port=9229',
  ("--user-data-dir=`"$DebugRoot`""),
  '--no-first-run', '--no-default-browser-check', 'about:blank'
)
Start-Sleep -Seconds 4
curl.exe -s http://127.0.0.1:9229/json/version
```

**Result:** Chrome/148.0.7778.168, Protocol-Version 1.3, all CDP metadata present.

### Phase 2 — Find source profile ✅
- WinRM user `winrm_user` IS a local admin
- Source profile at `C:\Users\Administrator\AppData\Local\Google\Chrome\User Data`
- Profile name: `Default` (not `Profile 1`)
- Cookes file: `Default\Network\Cookies` (20KB)

### Phase 3 — Clone the profile ✅
```powershell
$SourceRoot = "C:\Users\Administrator\AppData\Local\Google\Chrome\User Data"
$CloneRoot = "C:\Users\winrm_user\AppData\Local\Google\Chrome\User Data CDP Clone"
robocopy $SourceRoot $CloneRoot /E /R:1 /W:1 /XJ `
    /XD 'Crashpad' 'GrShaderCache' 'ShaderCache' 'Cache' 'Code Cache' 'downloads' 'FileTypePolicies' ...
    /XF 'Singleton*' 'lockfile' 'BrowserMetrics*' '*.tmp' ...
    /NFL /NDL /NJH /NJS
```

**Result:** 1,676 files, 202 MB copied in ~1 second.

### Phase 4 — Launch cloned debug Chrome ✅
```powershell
$Args = '--remote-debugging-address=127.0.0.1 --remote-debugging-port=9229 --user-data-dir="C:\Users\winrm_user\AppData\Local\Google\Chrome\User Data CDP Clone" --no-first-run --no-default-browser-check --new-window https://x.com/marclou'
Start-Process -FilePath $Chrome -ArgumentList $Args
```

**Result:** CDP listening on 9229 (PID 2540), page loads "Marc Lou (@marclou) / X".

### Phase 5 — CDP HTTP API behavior (Chrome 148) ⚠️

| Endpoint | Method | Works? | Notes |
|----------|--------|--------|-------|
| `/json` | GET | ✅ Yes | Returns full target list |
| `/json/version` | GET | ✅ Yes | Returns browser metadata |
| `/json/new?url=X` | PUT | ✅ Yes | Creates new tab, navigates to X |
| `/devtools/page/<id>` | POST | ❌ No | Returns HTTP 200 with Content-Length: 0 |
| `/devtools/browser/<id>` | POST | ❌ No | Same — 200 with empty body |

**CDP HTTP POST commands silently fail to return response bodies in Chrome 148.** The connection is accepted (200 OK), but no CDP result is returned. For full CDP control, you MUST use WebSocket.

## The correct flag shape (critical!)

```powershell
# WRONG — Chrome ignores the flags entirely:
--user-data-dir="<clone_root>\Profile 1"

# RIGHT:
--user-data-dir="<clone_root>" --profile-directory="Profile 1"
```

`--user-data-dir` takes the **root** directory (containing `Default/`, `Profile 1/`, etc.). `--profile-directory` selects which profile within it to use.

## Trying to POST via curl/WebClient/Invoke-RestMethod

All approaches were tested:
- `curl.exe -d $json_body` — POST succeeds but no response body
- `curl.exe --data-binary $json_body` — same
- `curl.exe -d @file` — PowerShell interprets `@` as splatting
- `Get-Content file | curl.exe -d @-` — PowerShell parses `@-` as splatting
- `[System.Net.WebClient]::UploadString()` — same empty response
- `Invoke-RestMethod` — returns `""` (empty JSON string)
- `[System.Net.HttpWebRequest]` — response stream is empty

**Conclusion:** Chrome 148's HTTP CDP API is half-functional. Discovery works, execution doesn't. WebSocket is required.

## WinRM + PowerShell file-writing strategy

When using `[System.IO.File]::WriteAllBytes` through WinRM `run_ps()`:

1. Keep each WinRM command under ~5000 characters (base64 included)
2. For large scripts, write in ~1200-byte UTF-8 chunks:
   - First chunk: `WriteAllBytes` (creates the file)
   - Subsequent chunks: `Open("path", [System.IO.FileMode]::Append)` then `Write` + `Close`
3. Watch for the typo `[System.IOFileMode]::Append` (missing dot) — it silently fails
4. Read results back as base64: `[System.Convert]::ToBase64String([System.IO.File]::ReadAllBytes("$env:TEMP\out.json"))`
5. Filter the response: skip lines starting with `#<` or `<O` (PowerShell CLIXML noise)

## PowerShell pitfalls with native commands

- **`2>&1` changes output type** from `string` to `ErrorRecord[]`. Don't use it when you need string methods.
- **Multi-line output becomes array.** `$out = curl.exe ...` creates one string per line. Use `($out) -join "\`n"` before parsing.
- **`@` for file input is splatting, not curl syntax.** Always use `Invoke-RestMethod` or pipe via stdin differently.

## CDP over WebSocket (the working approach)

Since Chrome 148's HTTP CDP API returns empty bodies, you MUST use WebSocket to send CDP commands and receive responses. The cleanest way is to install Python on the Windows host and use the `websockets` library.

### Step 1: Install Python + uv + websockets on Windows

If `winget` is not available, download and install Python silently via curl:

```powershell
# Download installer (25 MB)
curl.exe -sL -o "$env:TEMP\python-3.12.9-amd64.exe" `
  https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe

# Silent install
Start-Process -FilePath "$env:TEMP\python-3.12.9-amd64.exe" `
  -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_pip=1 TargetDir=""C:\Program Files\Python312""" `
  -Wait -NoNewWindow

# Verify
& "C:\Program Files\Python312\python.exe" --version

# Install uv
& "C:\Program Files\Python312\python.exe" -m pip install uv -q

# Install websockets
& "C:\Program Files\Python312\python.exe" -m uv pip install websockets -q
```

### Step 2: Write the Python CDP WebSocket scraper to Windows

Use the base64-file-chunk technique to transfer a Python script to Windows:

```python
import winrm, base64

s = winrm.Session(...)

# Read the Python script
with open('/path/to/scraper.py', 'rb') as f:
    content = f.read()

# Write in ~1200-byte chunks
chunk_size = 1200
for i in range(0, len(content), chunk_size):
    chunk = content[i:i+chunk_size]
    b64 = base64.b64encode(chunk).decode('ascii')
    if i == 0:
        s.run_ps(f'[System.IO.File]::WriteAllBytes("$env:TEMP\\scraper.py", ' +
                 f'[System.Convert]::FromBase64String("{b64}"))')
    else:
        # Append mode — note the dot between IO and FileMode!
        s.run_ps(f'$b=[System.Convert]::FromBase64String("{b64}");' +
                 f'$f=[System.IO.File]::Open("$env:TEMP\\scraper.py",' +
                 f'[System.IO.FileMode]::Append);$f.Write($b,0,$b.Length);$f.Close()')

# Execute on Windows
PY = "C:\\Program Files\\Python312\\python.exe"
r = s.run_ps(f'& "{PY}" "$env:TEMP\\scraper.py" 2>&1')
```

### Step 3: Python WebSocket CDP client (core pattern)

```python
import asyncio, json, websockets, urllib.request

async def cdp_via_websocket():
    # Get page list via HTTP (this still works)
    with urllib.request.urlopen("http://127.0.0.1:9229/json") as f:
        targets = json.loads(f.read())
    
    pages = [t for t in targets if t["type"] == "page"]
    ws_url = pages[0]["webSocketDebuggerUrl"]
    
    async with websockets.connect(ws_url) as ws:
        # CDP commands are JSON over WebSocket
        # Send: {"id": 1, "method": "Runtime.evaluate", "params": {...}}
        # Receive: {"id": 1, "result": {"result": {"value": ...}}}
        
        def send(method, params=None, cmd_id=1):
            return json.dumps({"id": cmd_id, "method": method, 
                              "params": params or {}})
        
        # Navigate
        await ws.send(send("Page.navigate", {"url": "https://x.com/marclou"}))
        await ws.recv()  # wait for response
        await asyncio.sleep(6)
        
        # Evaluate JS
        await ws.send(send("Runtime.evaluate", {
            "expression": "document.title"
        }))
        resp = json.loads(await ws.recv())
        title = resp.get("result", {}).get("result", {}).get("value")
        
        # Check login state
        await ws.send(send("Runtime.evaluate", {
            "expression": "!!document.querySelector('[data-testid=\"SideNav_AccountSwitcher_Button\"]')"
        }))
        resp = json.loads(await ws.recv())
        logged_in = resp.get("result", {}).get("result", {}).get("value", False)
        
        # Extract tweets
        await ws.send(send("Runtime.evaluate", {
            "expression": """JSON.stringify(Array.from(
                document.querySelectorAll('[data-testid="tweetText"]')
            ).map(el => ({
                text: el.textContent.trim(),
                link: el.closest('a[href*="/status/"]')?.getAttribute('href') || ''
            })))"""
        }))

asyncio.run(cdp_via_websocket())
```

### Step 4: Scroll loop for full tweet collection

```python
seen = {}
empty_runs = 0
MAX_SCROLLS = 60

for i in range(MAX_SCROLLS):
    # Scroll
    await ws.send(send("Runtime.evaluate", {
        "expression": "window.scrollTo(0, document.body.scrollHeight)"
    }))
    await asyncio.sleep(2.5)
    
    # Extract
    await ws.send(send("Runtime.evaluate", {
        "expression": """JSON.stringify(Array.from(
            document.querySelectorAll('[data-testid="tweetText"]')
        ).map(function(el){
            var a=el.closest('article');
            var ti=a ? a.querySelector('time') : null;
            var li=el.closest('a[href*="/status/"]');
            return{
                text: el.textContent.trim(),
                time: ti ? ti.getAttribute('datetime') : '',
                link: li ? li.getAttribute('href') : ''
            };
        }))"""
    }))
    resp = json.loads(await ws.recv())
    raw = resp.get("result", {}).get("result", {}).get("value", "[]")
    
    tweets = json.loads(raw)
    before = len(seen)
    for t in tweets:
        if t.get("link") and t.get("text") and len(t["text"]) > 3:
            seen[t["link"]] = {"text": t["text"], "time": t.get("time", "")}
    
    new = len(seen) - before
    print(f"Scroll {i+1}: {len(tweets)} on page, {new} new, {len(seen)} total")
    
    if new == 0:
        empty_runs += 1
    else:
        empty_runs = 0
    if empty_runs >= 8:
        break

# Save results
import json, os
results = [{"link": k, "time": v["time"], "text": v["text"]} 
           for k, v in seen.items()]
with open(os.environ.get("TEMP", ".") + "/marclou_cdp.json", "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
```

### Step 5: Fetch results back to Linux

```python
fetch = '[System.Convert]::ToBase64String([System.IO.File]::ReadAllBytes("$env:TEMP\\marclou_cdp.json"))'
r = run(fetch)
clean = [l for l in r.split('\n') if l.strip() and not l.startswith('#<') and not l.startswith('<O')]
tweets = json.loads(base64.b64decode(clean[0]).decode('utf-8'))
```

## Cookie encryption caveat (important!)

The cloned profile's cookie database IS copied (the `Network/Cookies` file is there), but Chrome encrypts session cookies with a key derived from the **original profile's directory path**. When you launch Chrome with `--user-data-dir=<clone_path>`, Chrome generates a NEW encryption key for the new path. The old cookies become undecryptable.

**This means the cloned profile will NOT have the X login session even though the cookie file exists on disk.**

To get a working login in the cloned Chrome:
1. Launch the clone Chrome (it opens a window on the desktop)
2. **Log into X manually** in that window — this creates new cookies encrypted with the clone's key
3. **Do NOT force-kill Chrome** (`Stop-Process -Force` skips writing cookies to disk)
4. Instead, close the window normally, OR leave it running and connect via WebSocket to scrape immediately
5. If Chrome is killed ungracefully, the user must log in again

Using the WebSocket approach while Chrome is still running (don't close it) lets you scrape the live session without worrying about cookie persistence.

## Chromium process reuse and CDP launch failure

When Chrome is already running on the system (even under a different user), launching a new Chrome instance with `Start-Process -ArgumentList @(...)` may silently route to the existing process instead of creating a new debug-enabled instance. Symptoms: you get a PID from `Start-Process`, the PID exits after ~1 second, and no CDP port is bound.

**More reliable launch pattern for a separate Chrome instance:**

```powershell
# Use Invoke-Expression with start (not Start-Process with argument array)
$Chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$Args = '--remote-debugging-address=127.0.0.1 --remote-debugging-port=<port> --user-data-dir="<path>" --no-first-run --no-default-browser-check --new-window <url>'
Invoke-Expression ("`"" + $Chrome + "`" " + $Args)
```

This was more reliable during testing, though still subject to Chrome's process reuse when the target `--user-data-dir` is not brand-new.

**For maximum reliability, ensure NO Chrome is running on the system** before launching the debug instance. On Windows Server, the "Chrome SxS" Canary installer may leave a `--from-installer` Chrome process running — kill it too.

## Completed script

A full working CDP WebSocket scraper for X.com tweet collection is available at `scripts/cdp-ws-scraper.py` in this skill directory. It implements the complete scroll+extract loop with configurable max scrolls, pause timing, and empty-run detection. Use it with a fresh temp profile (not a clone) for best results.
