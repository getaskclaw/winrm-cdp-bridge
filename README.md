# winrm-cdp-bridge

> Remote Windows automation over WinRM + live Chrome CDP — control logged-in browser sessions without killing Chrome or stealing cursor focus.

A toolkit for driving a remote Windows machine (VPS, dedicated box, or colleague's desktop) from Linux over Tailscale. Connect via WinRM for PowerShell commands, launch and control Chrome via CDP WebSocket, scrape X/Twitter with rate-limit-aware scroll harvesters, and use OpenCLI Browser Bridge for cookie-based data extraction.

Built and battle-tested over 6+ weeks of daily X/Twitter signal collection across 15,000+ posts.

## What's in here

### Scripts

| Script | What it does |
|---|---|
| `cdp-ws-scraper.py` | CDP WebSocket scraper for X profile timelines. Rate-limit detection, adaptive backoff, periodic checkpoint saving, multi-selector login check. |
| `cdp-ws-search-scraper.py` | CDP WebSocket scraper for X search results. Digs deeper historically than the profile timeline (~3 months vs ~14 months). |
| `winrm_ps.py` | WinRM PowerShell helper — base connection wrapper with NTLM auth. |
| `enable_cdp_no_clipboard.py` | Enables Chrome CDP on a remote Windows host without clipboard interference (avoids DPAPI cookie destruction). |
| `refresh_chrome_policy.py` | Refreshes Chrome group policy on Windows. |
| `install_opencli_windows.py` | Installs OpenCLI on a remote Windows host via WinRM. |
| `winrm_uia_collector.py` | WinRM + UI Automation tweet collector template. |
| `winrm_uia_live_collector.py` | WinRM + UI Automation live profile timeline collector template. |

### References

| File | Topic |
|---|---|
| `chrome-control-windows-runbook.md` | Quick-reference runbook for Chrome on Windows: CDP, OpenCLI, safety rules, quoting patterns, decision flow |
| `remote-cdp-tunnel-via-portproxy.md` | Discovering a remote Chrome CDP port, tunneling via netsh portproxy + firewall rule, wiring browser tools |
| `cdp-via-powershell-httpclient.md` | CDP operations via PowerShell .NET HttpClient POST — quick operations without a Python WebSocket client |
| `chrome-148-cdp-profile-clone.md` | Chrome 148+ CDP limitations, profile cloning, and WebSocket fallback |
| `cookie-profile-transfer.md` | Cookie-only profile transfer (copy Local State + Network/Cookies without full clone) |
| `existing-cdp-port-reuse.md` | Reusing an existing CDP Chrome from a prior session instead of launching a new one |
| `opencli-profile-auto-detect.md` | Runtime detection of active OpenCLI browser bridge profile |
| `opencli-tweets-vs-search-collection.md` | OpenCLI `tweets` vs `search` endpoints — different caps, date filters, rate limits |
| `x-api-caps-rate-limits.md` | X/Twitter API caps, rate limit thresholds, cooldown times, detection patterns |
| `x-search-vs-timeline-coverage.md` | Date-range coverage limits of X search vs profile timeline — how they complement each other |
| `vxtwitter-quick-lookup.md` | Quick single-tweet lookups via public vxtwitter API — no CDP or auth needed |
| `cdp-x-scraping.md` | Full CDP-based X scraping reference |
| `x-collector-rate-limits-and-batching.md` | Rate limit management and batch collection patterns |
| `actors-db-pattern.md` | SQLite schema and collection pattern for X actor/follower data |
| `pain-point-signal-discovery.md` | Using the toolkit for small business pain signal discovery |

### Docs

| File | Topic |
|---|---|
| `26429.md` | Example host facts sheet (sanitized — no passwords) |
| `chrome-control-windows.md` | Full Chrome CDP control runbook (16KB) |
| `chrome-cdp-live-session.md` | CDP live session setup guide |

## Architecture

```
Linux host (your machine)
  ├── WinRM over Tailscale → Windows host (Port 5985)
  │   ├── PowerShell commands (run_ps)
  │   ├── Chrome launch (scheduled task, interactive session)
  │   ├── OpenCLI Browser Bridge (cookie/intercept strategies)
  │   └── File transfer (base64 or temporary HTTP server)
  │
  ├── CDP WebSocket → Chrome on Windows (Port 9222/9250)
  │   ├── Navigate, evaluate JS, scroll, click
  │   ├── Rate-limit-aware tweet harvesting
  │   └── Login state detection (multi-selector)
  │
  └── netsh portproxy tunnel (optional)
      └── Expose CDP port to Linux for remote browser tools
```

## Key Safety Rules

1. **Never kill Chrome with `Stop-Process -Name chrome -Force`** — this destroys DPAPI-encrypted cookies in ALL instances, logging users out of X and other sites. Target specific PIDs by port.
2. **Bind CDP to localhost** — remove temporary portproxy/firewall exposure after use.
3. **Never print credentials** — the credential file is read by scripts, never by the agent.
4. **Use Chrome Canary for coexistence** — launching a second Chrome with `--remote-debugging-port` alongside an existing Chrome merges processes on Chrome 148+. Canary is a separate binary and doesn't merge.
5. **Non-default `--user-data-dir` required for Chrome 136+** — Chrome ignores `--remote-debugging-port` with the default profile path.

## Setup

1. **Prerequisites on Linux:** `pywinrm`, `requests_ntlm`, Tailscale connected to the Windows host.
2. **Prerequisites on Windows:** Chrome (stable + Canary recommended), Python 3.12+ with `websockets`, OpenCLI (optional).
3. **Credentials:** Set `$WINRM_CREDENTIALS` to your credentials file path, or pass `--credentials` to each script. See `.credentials.example` for format. Never commit real credentials.
4. **Test WinRM:**
   ```python
   import winrm
   # Use HTTPS (5986) with certificate pinning in production, not HTTP
   sess = winrm.Session("http://<tailscale-ip>:5985/wsman", auth=("user", "pass"), transport='ntlm')
   r = sess.run_ps("hostname")
   print(r.std_out)
   ```
   **WinRM security:** HTTP (5985) sends credentials and commands in cleartext. For production, use HTTPS (5986) with a pinned certificate and a non-admin service account. Do not set `LocalAccountTokenFilterPolicy=1` — prefer UAC elevation per-operation.

## What we learned (30+ documented pitfalls)

The references directory contains 30+ documented pitfalls from production use, including:

- Chrome 148+ process merging (can't run two same-binary instances)
- CDP HTTP API half-broken (GET works, POST returns empty — need WebSocket)
- WinRM quoting hell (Python → WinRM → PowerShell → CDP JSON nesting)
- Profile cloning doesn't preserve X login (DPAPI encryption is path-bound)
- `StandardOutput.ReadToEnd()` blocks until process exit (WinRM times out on long scrapers)
- `asyncio.wait_for` on `ws.recv()` is mandatory (without it, scrapers hang forever on rate limits)
- OpenCLI `[intercept]` commands silently return empty output when CDP is unavailable (no error, no timeout)
- PowerShell `2>&1` changes output type from string to ErrorRecord[]

See the reference files for full details and fixes.

---

Built with 🜂 by [AskClaw](https://x.com/GetAskClaw)