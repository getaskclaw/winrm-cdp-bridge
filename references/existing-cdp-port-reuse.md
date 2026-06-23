# Reusing an Existing CDP Chrome Instance

## When to use

A Chrome with `--remote-debugging-port` is already running from a prior session attempt (or leftover from previous automation). The user is logged into a **different** Chrome (no CDP) and doesn't want you to launch yet another Chrome.

Rather than launching a new instance, reuse what's already there.

## Detection — scan all common ports

Before asking the user to do anything (including `chrome://inspect`), check for running CDP:

```powershell
# From the Windows host via WinRM:
foreach ($port in @(9222, 9229, 9240, 9250, 9221, 9230, 9333)) {
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$port/json/version" -TimeoutSec 2 -ErrorAction Stop
        Write-Output "CDP on $port — $($resp.Browser)"
        # Check what pages are open
        $pages = Invoke-RestMethod -Uri "http://127.0.0.1:$port/json" -TimeoutSec 2
        foreach ($p in $pages) {
            Write-Output "  Tab: $($p.title) | $($p.url.Substring(0, [Math]::Min($p.url.Length, 120)))"
        }
    } catch { }
}
```

## Checking login state via CDP

Once a CDP port is found, check if the user is logged into the target site:

1. Get the page WS URL for the target tab (via `/json` endpoint — look for the right `url` or `title`).
2. Connect via Python WebSocket on the Windows host:

```python
import json, urllib.request, asyncio, websockets

async def check_login(ws_url):
    """Multi-selector login check — more reliable than any single selector."""
    async with websockets.connect(ws_url) as ws:
        js = """
        (() => {
            const selectors = [
                '[data-testid="SideNav_AccountSwitcher_Button"]',
                '[data-testid="SideNav_NewTweet_Button"]',
                '[data-testid="AppTabBar_Profile_Tab"]',
                '[data-testid="AppTabBar_Profile"]',
                'header[role="banner"] nav a[href*="/settings"]'
            ];
            return selectors.some(s => document.querySelector(s) !== null);
        })()
        """
        msg = json.dumps({"id": 1, "method": "Runtime.evaluate",
            "params": {"expression": js, "returnByValue": True, "awaitPromise": False}})
        await ws.send(msg)
        resp = json.loads(await ws.recv())
        return resp.get("result", {}).get("result", {}).get("value", False)
```

**CRITICAL: Always use the multi-selector approach, not a single selector.** In practice, `AppTabBar_Profile` can return `False` even when the user IS logged in — it may not render on certain page types (e.g. when viewing another user's profile, the profile tab in the sidebar may not be focused or rendered). THIS HAPPENED IN PRODUCTION: `AppTabBar_Profile` returned `False` while `SideNav_AccountSwitcher_Button` returned `True` — the user was legitimately logged in but the `AppTabBar_Profile` selector alone would have incorrectly reported them as logged out.

The multi-selector `some()` pattern is the only safe way — `scripts/cdp-ws-scraper.py` has the authoritative implementation combining 5 overlapping selectors.

**When `check_login` returns ambiguous results**: navigate to `x.com/home` and re-check. The home timeline always renders the account switcher and tweet button when logged in. If that still returns False, the user genuinely needs to log in.

If not logged in, ask the user to log into X (or the target site) in that specific window. They don't need to know it's "port 9250" — just say "the Chrome window already showing marclou / the target site on your desktop."

## Pitfalls

- **Don't kill the CDP Chrome to "restart" it.** The DPAPI cookies in the temp profile can't survive a force-kill. If the user logs in, keep that Chrome running. Your WebSocket scraper can reconnect if disconnected.
- **Don't launch another Chrome if one already has CDP.** Two CDP-enabled Chimes mean two places the user might need to log in, and two ports to track. Reuse the one you find.
- **Check CDP ports before checking anything else.** This session's mistake was: 1) killed Chrome, 2) launched new Chrome, 3) killed again, 4) asked user to enable inspect, 5) only *then* found there was already a CDP Chrome on port 9250. Scanning ports first would have saved 4 steps.
- **If the CDP Chrome shows x.com/marclou but no login, the user just needs to log in there.** Don't navigate away from marclou's profile — the scraper starts from wherever the page is.
- **`AppTabBar_Profile` is an unreliable single login indicator.** Even on a fully logged-in X session, this element may not appear in the DOM when viewing another user's profile page. Always pair it with `SideNav_AccountSwitcher_Button` and other fallback selectors using the `some()` pattern.
