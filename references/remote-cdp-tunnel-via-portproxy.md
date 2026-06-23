# Remote CDP tunnel via netsh portproxy

Tunnel a remote Chrome CDP endpoint to your Hermes browser tools.

## ⚠️ Security warnings

**Do NOT expose CDP to all interfaces or open inbound firewall rules.**
Chrome's DevTools Protocol gives full control over the browser — execute JS, read pages, manipulate login sessions, steal cookies. Any peer that can reach the CDP port can take over the browser.

**Required mitigations:**
- Bind the portproxy to the **agent's Tailscale IP only**: `listenaddress=<agent-ts-ip>`
- Restrict the firewall rule to **the agent's Tailscale IP only**: `remoteip=<agent-ts-ip>`
- **Never** use `listenaddress=*` or omit `remoteip`.
- Clean up the portproxy and firewall rule immediately after the session.
- Prefer SSH local port forwarding or a Tailscale funnel over netsh portproxy.

## Flow

1. **Scan Chrome processes for the CDP port** (don't assume the port — it varies):

   ```powershell
   Get-WmiObject Win32_Process -Filter "Name = 'chrome.exe'" | Select-Object ProcessId, CommandLine | Format-List
   ```

   Look for `--remote-debugging-port=<port>`.

2. **Verify CDP is alive** from inside Windows (it binds to 127.0.0.1):

   ```powershell
   Invoke-WebRequest -Uri http://127.0.0.1:<port>/json/version -UseBasicParsing
   ```

   Extract `webSocketDebuggerUrl` from the response — you'll need the browser UUID.

3. **Tunnel via netsh portproxy** — scoped to the agent's Tailscale IP:

   ```powershell
   $agentIp = "<agent-tailscale-ip>"  # e.g. 100.x.x.x

   netsh interface portproxy add v4tov4 `
     listenaddress=$agentIp listenport=<ext-port> `
     connectaddress=127.0.0.1 connectport=<cdp-port>

   netsh advfirewall firewall add rule name="CDP <ext-port>" `
     dir=in action=allow protocol=TCP `
     localport=<ext-port> remoteip=$agentIp
   ```

4. **Wire Hermes browser tools** in config.yaml:

   ```yaml
   browser:
     cdp_url: 'ws://<windows-tailscale-ip>:<ext-port>/devtools/browser/<uuid-from-step-2>'
   ```

5. **Verify** by navigating to any URL with `browser_navigate`.

6. **Clean up immediately when done:**

   ```powershell
   netsh interface portproxy delete v4tov4 listenaddress=$agentIp listenport=<ext-port>
   netsh advfirewall firewall delete rule name="CDP <ext-port>"
   ```

## Verification

```bash
# Check portproxy is active
netsh interface portproxy show v4tov4

# Verify cleanup
netsh interface portproxy show v4tov4  # should be empty after cleanup
```

## Pitfalls

- Scripts and automation that set up portproxy + firewall rules **must** include cleanup in a `finally` block or equivalent.
- The Chrome Browser UUID changes on restart. Always re-fetch from `/json/version`.
- Chrome 148+ requires WebSocket for CDP commands — HTTP POST returns empty body.
- If you use `curl` from the Windows host to test, note Chrome 148+ HTTP CDP is half-functional (GET works, POST returns empty).
