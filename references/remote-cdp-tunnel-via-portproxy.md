# Remote CDP Tunnel via netsh Portproxy

## When This Applies

Chrome is running on a remote Windows host (Tailscale 100.117.164.91, hostname `to6429`) with `--remote-debugging-port` bound to `127.0.0.1`. The user can't see the Chrome window. The Hermes browser tools (running on a Linux agent) need to connect to Chrome's CDP through WinRM tunneling.

## The Pattern

**Discover → Tunnel → Wire → Verify → Clean**

---

## Step 1: Discover the CDP Port

The port changes between sessions. Don't assume 9222, 9223, 9227, or any fixed value. Scan Chrome process command lines:

```python
import winrm
s = winrm.Session('100.117.164.91', auth=('winrm_user', password), transport='ntlm')
ps = '''Get-WmiObject Win32_Process -Filter "Name = 'chrome.exe'" | Select-Object ProcessId, CommandLine | Format-List'''
r = s.run_ps(ps)
```

Look for `--remote-debugging-port=NNNN` in the output. Example from a real session:

```
ProcessId   : 11792
CommandLine : "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9250
              --user-data-dir=C:\Temp\mc_direct --no-first-run --no-default-browser-check --new-window
              https://x.com/login
```

**Port found: 9250** (not 9227 as used in previous sessions).

## Step 2: Verify CDP Is Alive

```python
ps = '''Invoke-WebRequest -Uri http://127.0.0.1:9250/json/version -UseBasicParsing | Select-Object -ExpandProperty Content'''
r = s.run_ps(ps)
```

Response includes:
```json
{
   "Browser": "Chrome/148.0.7778.168",
   "webSocketDebuggerUrl": "ws://127.0.0.1:9250/devtools/browser/6f213c78-ccdc-4a85-91b5-223d7882391c"
}
```

**Save the UUID** (here: `6f213c78-ccdc-4a85-91b5-223d7882391c`) — you need it for the Hermes config.

Also check what page(s) are open:
```python
ps = '''Invoke-WebRequest -Uri http://127.0.0.1:9250/json -UseBasicParsing | Select-Object -ExpandProperty Content'''
```

Returns targets with `title`, `url`, `type` (page/iframe/service_worker). The main page tab has `type: "page"`.

## Step 3: Tunnel via Portproxy

Forward external port 9251 → 127.0.0.1:9250:

```python
# Delete any existing rule first
s.run_ps('netsh interface portproxy delete v4tov4 listenport=9251 2>&1 | Out-Null')
# Add new rule
s.run_ps('netsh interface portproxy add v4tov4 listenport=9251 connectaddress=127.0.0.1 connectport=9250')
# Add firewall rule for the forwarded port
s.run_ps('netsh advfirewall firewall add rule name="CDP 9251" dir=in action=allow protocol=TCP localport=9251')
# Verify
r = s.run_ps('netsh interface portproxy show v4tov4')
```

Result:
```
Listen on ipv4:             Connect to ipv4:
Address         Port        Address         Port
--------------- ----------  --------------- ----------
*               9251        127.0.0.1       9250
```

## Step 4: Wire Hermes Browser Tools

From the Linux agent, verify the tunnel works:

```bash
curl -s --connect-timeout 5 http://100.117.164.91:9251/json/version
# Should return the same JSON as step 2
```

Update `~/.hermes/config.yaml`:

```yaml
browser:
  cdp_url: 'ws://100.117.164.91:9251/devtools/browser/6f213c78-ccdc-4a85-91b5-223d7882391c'
```

Then use `browser_navigate(url)` — the browser tools connect to the remote Chrome via CDP WebSocket through the tunnel.

## Step 5: Verify

- `browser_snapshot` shows page content from the remote Chrome
- `browser_vision` captures screenshots of the remote display
- The user's logged-in Chrome session is fully controllable from the Linux agent

## Step 6: Clean Up

```python
s.run_ps('netsh interface portproxy delete v4tov4 listenport=9251')
s.run_ps('netsh advfirewall firewall delete rule name="CDP 9251"')
```

Verify cleanup:
```python
r = s.run_ps('netsh interface portproxy show v4tov4')
# Should show empty table
```

---

## Pitfalls

### Port changes between sessions
Chrome doesn't use a consistent CDP port. Previous session used 9227, this session used 9250. Always scan process command lines — don't hardcode.

### Chrome 148 HTTP POST returns empty body
Chrome 148's CDP HTTP API is half-functional: `GET /json` and `GET /json/version` work, but `POST /devtools/page/<id>` returns HTTP 200 with `Content-Length: 0`. You MUST use WebSocket for full CDP control. The Hermes browser tools use WebSocket internally, so this is handled — but if you're sending raw CDP commands, use WebSocket not HTTP POST.

### `netsh portproxy` needs firewall rule
The portproxy makes the port listen on all interfaces (`*:9251`), but the Windows firewall (Private/Public profile, BlockInbound) drops external connections. You must add an explicit `netsh advfirewall firewall add rule` to allow inbound traffic on the forwarded port.

### Portproxy binds to `*` (all interfaces)
The portproxy listens on all network interfaces, including any public-facing ones if the machine has a public IP. On a Tailscale-only machine (no public IP) this is fine, but be aware and clean up afterward.

### WebSocket URL path must be correct
The `cdp_url` format is `ws://<ip>:<port>/devtools/browser/<uuid>`. Using just `ws://<ip>:<port>` without the browser UUID path segment will fail. The UUID comes from `/json/version` → `webSocketDebuggerUrl`.

### Chrome not visible doesn't mean not running
The user may say "there is no chrome visible" while Chrome processes exist with CDP active. This happens when:
- Chrome was launched via `Start-Process` without a visible window context
- Chrome merged into an existing process (Chrome 148 merges same-binary launches)
- The window is behind other windows or in a different virtual desktop
- The window was spawned in session 0 (SYSTEM context) instead of the user's interactive session

**Rule: if CDP responds, the browser tools can connect. Window visibility is not a prerequisite.**
